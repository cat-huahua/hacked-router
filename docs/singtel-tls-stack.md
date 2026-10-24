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

## 6. 证据索引

| 内容 | 位置 |
|---|---|
| TLS 库 | `/usr/lib/libarc-ssl.so.0.1`（OpenSSL 1.0.1t） |
| 封装 | `as_client_*` / `as_load_key_cert` / `as_setup_verify` |
| cipher list | `ALL:!EXPORT:!LOW:!aNULL:!eNULL:!SSLv2` |
| TR-069 TLS | `libssl.so.1.0.0` + `libsslap.so.0.1` |
| OWL TLS | `libgnutls.so.30`（GnuTLS 3.4） |
| 证书 | `singtel-certificates.md` |
