# Singtel 的 TLS 栈（`libarc-ssl` / OpenSSL 1.0.1t）

> 设备：Arcadyan WG9116AEAC23-ST（v5.02.00 build09b）
> 材料：`/usr/lib/libarc-ssl.so.0.1`（约 1 MB，静态 OpenSSL + 薄封装）
> 一句话：**全机 TLS 基于 OpenSSL 1.0.1t（2016 年），外加一层 `as_*` 客户端封装。**

---

## 1. 版本与封装

`strings` 里直接写着：

```
AES part of OpenSSL 1.0.1t  3 May 2016
ASN.1 part of OpenSSL 1.0.1t
Big Number part of OpenSSL 1.0.1t
...
```

Arcadyan 自己的封装函数：

```
as_client_init / as_client_deinit
as_client_open / as_client_close
as_load_key_cert / as_unload_key_cert
as_setup_verify
```

即：`as_client_*` 管连接生命周期，`as_load_key_cert` 管证书/私钥，
`as_setup_verify` 管对端校验。

---

## 2. 密码套件策略

字符串里有一条显式 cipher list：

```
ALL:!EXPORT:!LOW:!aNULL:!eNULL:!SSLv2
```

含义：

| 排除项 | 效果 |
|---|---|
| `!EXPORT` | 去掉出口级弱加密 |
| `!LOW` | 去掉低强度 |
| `!aNULL` / `!eNULL` | 必须有认证/加密 |
| `!SSLv2` | **只禁了 SSLv2** |

★ 注意：**没有 `!SSLv3`、没有 `!TLSv1`、没有 `!RC4`** ——
所以 SSLv3/TLS1.0/RC4 是否可用，取决于运行时和 OpenSSL 默认。
OpenSSL 1.0.1t 本身也**不支持 TLS 1.3**。

---

## 3. 谁在用

| 服务 | TLS 实现 |
|---|---|
| httpd HTTPS | `libarc-ssl`（`init_ssl`） |
| TR-069（`tr69`） | 自己的 `libssl.so.1.0.0` + `libsslap.so` |
| OWL 本地 HTTPS | **GnuTLS 3.4**（`libgnutls.so.30`） |
| `libhttpclt`（HTTP 客户端） | 依赖 `libssl` |
| 自动升级（`autofw`） | libcurl + 系统 OpenSSL |

即：**同一台设备上有 OpenSSL 1.0.1t 和 GnuTLS 3.4 两套 TLS 栈**。

---

## 4. 证书/密钥来源

- `/usr/sbin/cert.pem` + `key.pem`（Singtel 自签 `www.singtel.com`）
- `/usr/lib/server.crt` + `server.key`（OWL）
- `/etc/config/cert/{RootCA,WebServer,Ftps}/`（动态生成）
- `as_load_key_cert` 负责把 cert/key 载入 SSL_CTX

详见 [singtel-certificates.md](singtel-certificates.md)。

---

## 5. 安全观察

1. **OpenSSL 1.0.1t 是 2016 年的版本**：之后有多个 CVE（1.0.1 系列已 EOL）。
2. **cipher list 只禁了 SSLv2**：没有禁 SSLv3/RC4/TLS1.0。
3. **不支持 TLS 1.3**。
4. **两套 TLS 栈**（OpenSSL + GnuTLS）意味着补丁面翻倍。
5. **`as_setup_verify` 的校验强度**决定 HTTPS 客户端是否会被中间人；
   具体是否 `SSL_VERIFY_NONE` 需要看调用方（httpd/tr69/autofw）。
6. **证书/私钥在固件里是明文**（见证书文档）。

---

## 6. `libsslap`：Arcadyan 的 SSL 封装

`/usr/lib/libsslap.so.0.1` 同时提供客户端和服务端 SSL：

```
Init_SSLClient / Init_SSLClient_Data / sslc_conf_init
init_ssl_client_connection
Init_SSLServer / Init_SSLServer_Data / ssld_conf_init
init_ssl_connection
LoadCACertificate / LoadCACertificateFromFile       ← 加载 CA
LoadServerCertAndKey / FromFile / FromPKCS12Format  ← 加载服务端证书
GetSSLClientCertificateError / GetSSLServerCertificateError
FreeSSLClientSession / FreeSSLServerSession
```

- 支持 **最多 3 个 CA**（`1stCA / 2ndCA / 3rdCA`）；
- 支持 PEM 和 PKCS#12；
- 还有 FTP / POP3 / SMTP / WebDav 的 SSL 客户端封装
  （`Init_FTP_SSLServer`、`Init_POP3_SSLClient`、`Init_SMTP_SSLClient`、
  `Init_WebDav_SSLClient`）。

内部字符串：

```
CaCert.pem
MyCertificate=%s
[%d] CaCertificate=%s
[%d] fn_caCertificate=%s
[%d] fn_myCerttificate=%s
```

即证书路径/内容由调用方传入。

---

## 7. `libhttpclt`：HTTP/HTTPS 客户端

`/usr/lib/libhttpclt.so.0.1`：

```
http_clt_get / http_clt_post / http_clt_download
http20_apns_post
parse_url / parse_url_get_host_path
connect_web_server
ht_build_request_header / ht_client_send / process_http_response
ht_update_cookie / ht_search_cookie / ht_clear_cookie
DigestCalcHA1 / DigestCalcResponse / parse_digest_challenge
```

特性：

- HTTP/1.x，支持 **Digest 认证**（`WWW-Authenticate`、nonce、qop=auth/auth-int）；
- Cookie（`Set-Cookie`、`HttpOnly`）；
- 重定向（`%s: redirect to %s, close current socket`）；
- HTTPS 通过 `libsslap` 的 `init_ssl_client_connection`；
- `http20_apns_post` 用：

```
-cert /etc/postapns/cacert.pem -token %s -payload %s -port 443 -debug -tvoice
```

> ★ `/etc/postapns/cacert.pem` 在 rootfs 里**不存在** ——
> 说明这个 APNS 路径要么是别的机型用的，要么运行时才生成。

安全相关：

```
SSL_get_verify_result
pSSL=0x%x, SSL->verify_result=%ld
route add -host %s dev %s
route add -host %s gw %s dev %s
```

即：会读 `SSL_get_verify_result`，并给目标主机加一条 host 路由；
**是否强制 `SSL_VERIFY_PEER` 取决于 `libsslap` 的 `sslc_conf_init` 实现**
（字符串层看不到 `SSL_VERIFY_NONE` 的硬编码）。

---

## 8. `arc_util_cert_gen`：嵌入式证书/密钥生成器

`/usr/sbin/arc_util_cert_gen` 把**编译进二进制的证书数据**写到 `/tmp/<name>`：

```
SSLAP_server_PKCS12_DATA
SSLAP_client_PKCS12_DATA
SSLAP_server_CA_DATA
SSLAP_client_CA_DATA
SSLAP_3RDCA_DATA
SSLAP_VERISIGNCA_DATA
```

行为：

```
SSLAP_write_all_keys> create %s successful.
SSLAP_write_all_keys> open %s failed!!
/tmp/%s
/tmp/myPass
```

即：它会生成/写出 server/client 的 PKCS#12、CA 证书，以及一个口令文件
`/tmp/myPass`。

★ **二进制里有一个 32 位十六进制的硬编码口令常量**（此处不公开），
用于保护/导入这些 PKCS#12。**该值只记录在私有笔记里**。

这解释了为什么 rootfs 里没有 `libsslap` 需要的客户端证书文件 ——
它们由这个工具在运行时从二进制里“释放”出来。

---

## 9. 证据索引

| 内容 | 位置 |
|---|---|
| TLS 库 | `/usr/lib/libarc-ssl.so.0.1`（OpenSSL 1.0.1t） |
| 封装 | `as_client_*` / `as_load_key_cert` / `as_setup_verify` |
| cipher list | `ALL:!EXPORT:!LOW:!aNULL:!eNULL:!SSLv2` |
| TR-069 TLS | `libssl.so.1.0.0` + `libsslap.so.0.1` |
| OWL TLS | `libgnutls.so.30`（GnuTLS 3.4） |
| 证书 | `singtel-certificates.md` |
