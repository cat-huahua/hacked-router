# Singtel Mesh Router 的证书体系

> 设备：Arcadyan WG9116AEAC23-ST（v5.02.00 build09b）
> 材料：`/usr/sbin/cert.pem`、`/usr/sbin/key.pem`、`/usr/lib/server.crt`、
> `/usr/lib/server.key`、`/usr/lib/ca.crt`、`/etc/config/cert/`、
> `create-*-cert.sh` / `restore-certificates.sh`
> 一句话：**固件里带了多套私钥，其中一套是自签的 `www.singtel.com` 证书。**

---

## 1. 静态证书（随固件发布）

| 文件 | 主体（CN） | 签发者 | 有效期 | 用途 |
|---|---|---|---|---|
| `/usr/sbin/cert.pem` + `key.pem` | `www.singtel.com` | 自签（O=Singtel） | 2021-07 ~ 2031-07 | **httpd HTTPS** |
| `/usr/lib/server.crt` + `server.key` | `TS-Mesh-WLAN.home` | `/usr/lib/ca.crt` | 1970 ~ 2118 | **OWL 本地 HTTPS** |
| `/usr/lib/ca.crt` | `TS-Mesh-WLAN.home` | 自签（C=CA, O=telus） | 2018-03 ~ 2118-02 | OWL 客户端证书的 CA |
| `/usr/sbin/public.pem` | — | — | — | 与上述 key 不配对 |

### 1.1 `cert.pem` / `key.pem`（httpd）

```
subject = C=SG, ST=Singapore, L=Singapore, O=Singtel, OU=Singtel, CN=www.singtel.com
issuer  = 同上（自签）
notBefore = Jul  5 01:54:58 2021
notAfter  = Jul  5 01:54:58 2031
```

- **证书与私钥模数一致**（已核对）；
- `httpd` 的 `init_ssl` 引用 `/usr/sbin/cert.pem` 和 `/usr/sbin/key.pem`；
- 也就是说：**管理界面的 HTTPS 默认用的是“www.singtel.com”的自签证书**，
  不是路由器 IP/主机名 —— 浏览器会报名称不匹配/自签警告。

### 1.2 `server.crt` / `server.key`（OWL）

```
subject = C=CA, ST=van, O=telus, OU=telus, CN=TS-Mesh-WLAN.home
issuer  = /usr/lib/ca.crt
```

- `libArcOWLcore.so` 用 GnuTLS + libmicrohttpd 起本地 HTTPS；
- 客户端证书由 `ca.crt` 校验（`gnutls_certificate_verify_peers2`）；
- `cert_auth_get_dn` 取客户端证书 DN，用于识别 App；
- **CA 私钥不在固件里**，只有 `ca.crt`。

---

## 2. 动态证书（`/etc/config/cert/`）

出厂配置包里：

```
config/cert/RootCA/rootca.crt.pem       (CA:TRUE)
config/cert/RootCA/rootca.key.pem       ← 私钥（无口令）
config/cert/WebServer/webserver.crt.pem
config/cert/WebServer/webserver.key.pem ← 私钥（无口令）
config/cert/WebServer/webserver.req.pem
```

这些是**开机/首次配置时生成**的：

### 2.1 `create-root-ca-cert.sh`

```sh
openssl genrsa -out rootca.key.pem <bits>
openssl req -new -key rootca.key.pem -subj "/C=.../CN=..." ...
openssl x509 -req -days <n> -sha1 -extensions v3_ca -signkey rootca.key.pem ...
create-webserver-cert.sh
create-ftps-cert.sh
```

★ **用的是 `-sha1`**（不是 SHA-256）。

### 2.2 `create-webserver-cert.sh`

- 从 `ccfg_cli` 读 `Certificate` 段：国家/州/城市/O/OU/CN/SAN/密钥长度/有效期；
- 如果 DDNS 关闭：CN = `IPv4_Addr`；
- 如果 DDNS 开启：CN = `CommonName`，SAN = `DNS:<DomainName>`；
- 生成 `webserver.key.pem` / `.req.pem` / `.crt.pem`，由 RootCA 签发。

### 2.3 `create-ftps-cert.sh`

把 WebServer 证书软链成 FTPS 证书，并拼成 `pure-ftpd.pem`
（`key.pem` + `crt.pem`）。

### 2.4 `restore-certificates.sh`

恢复 `/etc/config/cert/Ftps/` 的软链：

```
ftps.crt.pem -> WebServer/webserver.crt.pem
ftps.key.pem -> WebServer/webserver.key.pem
ftps.req.pem -> WebServer/webserver.req.pem
pure-ftpd.pem = ftps.key.pem + ftps.crt.pem
```

---

## 3. 哪些服务用哪套证书

| 服务 | 证书 |
|---|---|
| httpd（管理界面 HTTPS） | `/usr/sbin/cert.pem` + `key.pem`（默认） |
| OWL 本地 HTTPS | `/usr/lib/server.crt` + `server.key` |
| OWL 客户端认证 | `/usr/lib/ca.crt` |
| FTPS（pure-ftpd） | `/etc/config/cert/Ftps/pure-ftpd.pem` |
| TR-069 / 其他 | `/etc/config/cert/WebServer/*` |

> 实际是否切换到 `/etc/config/cert/...` 取决于 httpd 配置/上传流程；
> 静态的 `/usr/sbin/cert.pem` 是默认值。

---

## 4. 安全观察

1. **多套私钥随固件发布**（无口令保护）：
   - `www.singtel.com` 自签证书的私钥；
   - `TS-Mesh-WLAN.home` 服务端私钥；
   - RootCA / WebServer 私钥（在出厂配置包里）。
2. **管理界面默认证书是 `www.singtel.com`**：
   - 浏览器会警告（名称不匹配/自签）；
   - 如果客户端信任了这张证书，任何拿到固件的人都能冒充 `www.singtel.com`。
3. **生成证书用 SHA-1**（`-sha1`），现代浏览器/客户端会拒绝。
4. **OWL 的 CA 私钥不在固件里**，所以无法伪造客户端证书；
   但服务端私钥在固件里。
5. **FTPS 复用 WebServer 证书**，私钥同样落在 `/etc/config/cert/`。

---

## 5. 证据索引

| 内容 | 位置 |
|---|---|
| httpd 证书 | `/usr/sbin/cert.pem` / `key.pem`（`httpd` `init_ssl`） |
| OWL 证书 | `/usr/lib/server.crt` / `server.key` / `ca.crt` |
| 动态证书 | `/etc/config/cert/{RootCA,WebServer,Ftps}/` |
| 生成脚本 | `/usr/sbin/create-root-ca-cert.sh` / `create-webserver-cert.sh` / `create-ftps-cert.sh` |
| 恢复脚本 | `/usr/sbin/restore-certificates.sh` |
| openssl 配置 | `/etc/config/cert/openssl.config` / `openssl-altname.config` |
