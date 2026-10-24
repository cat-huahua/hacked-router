# EmbedUR broadband_ssl：实际入口、TLS 计时与保留函数

材料：WG9116AEAC23-ST 云代理包中的 ARM ELF `broadband_ssl`。
SHA-256：`90a037c53afd80afadeca57c900de9f7a65b1c15a5a6bb63b49dab00578899b0`。
只分析该 ELF 的应用层函数，没有执行它，也没有连接外部服务器。

## 已解：main 实际执行 HTTPS 探测

文件里存在 `speedtest_download`、`download_thread`、`get_ping_results`，
但这些名字不能证明入口会执行测速。
本样本 `main` 的可达流程是：

```text
解析 argv → 检查 argv[2] 包含大写 HTTPS
  → 对 argv[1] 做 IPv4 DNS 查询并记日志
  → 构造 argv[1]:443
  → 开始计时 → init_openssl → connect_encrypted
  → write_to_stream("GET / HTTP/1.0\r\n\r\n")
  → 结束第一段计时，写 /tmp/https_result
  → 重新开始计时 → read_from_stream(最多 256 字节)
  → 记录读取字节数 → 结束第二段计时，写 /tmp/ttfbs_result
```

### 参数

| 参数 | `main` 中用途 |
|---|---|
| `argv[1]` | hostname；直接拼接 `:443`，也传给 DNS helper |
| `argv[2]` | 模式；用 `strstr(value, "HTTPS")`，区分大小写的子串匹配 |
| `argv[3]`、`argv[4]` | 有条件存到全局变量，当前执行路径未使用 |

`argc<=1` 直接 `exit(1)`；`argc==2` 跳到末尾错误日志。
`argc>=3` 才检查模式。只有 hostname 非空且模式含 `HTTPS` 才走探测。
不要把这里当作接收完整 `https://.../path` URL 的通用下载器；
入口直接使用 hostname、固定端口 443 和固定 `/`。

实际 TLS 内发送的 HTTP 请求没有 Host / User-Agent header：

```http
GET / HTTP/1.0

```

字节为 `GET / HTTP/1.0\r\n\r\n`。
下面保留函数中的带 Host header 模板不是这条入口的请求。

### 两份结果的精确含义

| 文件 | 写入 / 实际范围 |
|---|---|
| `/tmp/https_result` | DNS 信息或 `ERROR FAILED DNS LOOKUP`；`ERROR Connect Failed`；`RESULTS <整数>`；读取字节数日志 |
| `/tmp/ttfbs_result` | `RESULTS <整数>` 或 `ERROR NO_STREAM_RESPONSE` / `ERROR NO_RESPONSE` |

`RESULTS` 是 `timeval_diff` 返回的微秒值除以 1000，即整数毫秒。
第一段从 OpenSSL 初始化之前到请求写入之后，包含初始化、BIO 建连、TLS
及请求写入，不能只称 TLS handshake time；显式 DNS helper 在计时之前，
而 BIO 仍以 hostname 建连。

第二段从重置 timer 到一次 read 后的停止 timer；在停止计时前还执行了
`system("echo ... >> /tmp/https_result")` 记录读取字节数，因此**包含该次 shell
日志开销**。这是等待首批数据的近似值，不是严格的 socket 首字节时间。
没有解析 HTTP status、响应 header、Content-Length 或完整页面。

显式 DNS 失败只写日志，仍然尝试 BIO 连接。read 返回 0（EOF）也会进入
`RESULTS` 分支，而不要求至少读到一个字节。
`read_from_stream` 对负返回值一直重试，见下节；所以主函数中为负值准备的
`NO_RESPONSE` 路径不能据此认定会被正常触发。

返回码也不能按常见 CLI 约定解读：成功计时路径最终落入打印
`ERR_EXIT` 并返回 1 的尾部；connect / write 失败分支可返回 0。
调用方应结合结果文件判断，不能只看 exit status。

## 已解：TLS 与 BIO wrappers

| 函数 | 行为 |
|---|---|
| `init_openssl` | 进程内一次性加载 error strings、SSL library、BIO strings 和算法 |
| `connect_encrypted(hostport, unused, ctx_out, ssl_out)` | `SSLv23_client_method` → `SSL_CTX_new` → `BIO_new_ssl_connect`；取 SSL 指针，`SSL_ctrl(0x21,4,0)` 设置 mode；设连接 hostname；`BIO_ctrl(0x65,0,0)` 执行连接状态机 |
| `read_from_stream(bio, buf, size)` | `BIO_read`；返回值≥0 就返回；负值时检查 retry flag，即使不可 retry，也只打印 error 后继续循环 |
| `write_to_stream(bio, buf, size)` | `BIO_write`；正值立即返回，0 返回，负值检查/打印后继续循环；没有对短写做补齐 |
| `print_ssl_error` / `print_ssl_error_2` | 输出格式化提示和 OpenSSL error queue |
| `timeval_diff` | 计算 `(end.sec-start.sec)*1000000 + end.usec-start.usec`；先用 32 位算术，再符号扩展到 64 位返回 |

应用层 wrapper 没有调用 CA trust 加载、verify 配置、hostname 校验或 SNI 设置；
不能把“BIO 连接成功”解释成已经验证对端身份。
`SSLv23_client_method` 名称本身也不能证明实际协商的是 SSLv2 / SSLv3；
实际 TLS version / cipher 需要运行时观测。
wrapper 中没有显式 timeout、重试次数或退避；持续错误时存在不终止路径。

## 已解：文件中保留的其他应用函数

这些函数体已恢复，但扫描可执行 section 中 ARM 直接 `B/BL` 指令，没有发现
指向下面五个入口的直接分支。`main` 同样没有调用它们。
这仅是静态直接调用证据，不排除外部或间接调用。

| 函数 | 已恢复行为 |
|---|---|
| `get_ipv4_addr(host, out, port)` | `getaddrinfo` 限定 AF_INET / SOCK_STREAM；遍历 IPv4 结果向 out 复制 16 字节 sockaddr，最后一个匹配覆盖前面结果；成功返回 1，失败 0 |
| `get_http_file(addr, host, path, filename)` | TCP connect；发送下述 HTTP/1.0 GET；输出到 `/tmp/<filename>`；8192 字节分块接收；返回 1/0 |
| `get_https_file(unused, hostport, path, filename, extra)` | 使用上述 BIO wrappers，发送同一 GET 模板，8192 字节分块读取并写 `/tmp/<filename>`；额外 stack 参数作为 connect wrapper 的未使用参数 |
| `download_thread(index_ptr)` | 读取 `thread[index]`，步长 `0x11c`；用其中 sockaddr 发普通 TCP HTTP GET，单次 recv 最多 65536 字节，mutex 保护累加接收字节；结束清 slot active 字段 |
| `speedtest_download(record_ptr)` | 处理记录中的 URL / sockaddr，构造替换 `upload.` token 的下载路径 `random3500x3500.jpg`，复制到全局 thread slot；函数体没有创建 pthread、等待线程或计算吞吐率 |
| `get_ping_results(url)` | 从 `http://%[^/]` 提取 host，`popen` 执行 IPv4 ping 3 包，取 `round-trip` 后 `= ` 起的第一个 `/` 分隔值，`atof()*1000` 返回 double；是第一个值，不是 avg |
| `get_uptime` | 尾调用 `time(NULL)`；名称不能当作 monotonic uptime |
| `broadband_test` | 仅返回常量 1，8 字节 stub |

保留下载函数的请求模板为：

```text
GET /%s HTTP/1.0\r\n
Host: %s\r\n
User-Agent: status\r\n
Accept: */*\r\n
\r\n
```

HTTP/HTTPS 文件下载 helper 对每个接收块分别用 `strstr(...,"\r\n\r\n")`
找 header 结束；找到后用 `strlen` 写余下数据，否则写整个块。
没有跨块拼接 header 的状态机，这不是完整的 HTTP parser，含 NUL 的正文也可能
受 `strlen` 分支影响。普通 HTTP helper 在检查 `select` 返回值之前就执行
`recv`，不能把设置的 3 秒 select timer 视为整个传输的可靠 timeout。

`download_thread` 在第一次正数 recv 后累加字节，检查 stop flag 后就走退出路径，
没有回到接收循环的边；不能仅凭函数名声称它实现了持续多线程吞吐率测速。

## 未解与修正边界

- 云代理构造 `broadband_ssl` 命令的确切调用点、外层结果文件清理和超时策略尚未追到。
- 完整测速逻辑可能在同包的 `speedtest` / `broadband` 中；它们是独立 ELF，不能
  用它们的行为补全此文件的 stub 或未被调用函数。
- 本文不声称还原了静态链接 OpenSSL 的每个内部函数，只覆盖应用逻辑和调用边界。
- 未做运行时 TLS/网络互操作测试。

## 证据索引

本 ELF 所列代码与只读字符串的 file offset = VA - `0x10000`。

| 内容 | 符号 / VA | file offset 或原文 |
|---|---|---|
| 参数、模式与实际流程 | `main` `0x14478` | `0x4478`；模式比较 `0x144e8–0x144f4` |
| 固定端口、请求 | `main` `0x1455c–0x145dc` | 字符串 `0x10698d` `%s:443`；`0x1069a3` `GET / HTTP/1.0\r\n\r\n` |
| 第一段计时 | `main` `0x1456c–0x14644` | `timeval_diff` 后除 `0x3e8` |
| 第二段计时 | `main` `0x14648–0x146ec` | read `0x14670`；日志 system `0x1468c`；停止 timer `0x146b4` |
| 成功 / 错误返回码 | `main` `0x146f4–0x14714` | 0 / 1 两条尾部 |
| DNS | `get_ipv4_addr` `0x148d8` | `0x48d8` |
| 时间差 | `timeval_diff` `0x1487c` | `0x487c`；32 位 `mla` `0x148bc` |
| HTTP 文件下载 | `get_http_file` `0x149b4` | `0x49b4`；GET 模板 `0x1066d3`；header 分隔符 `0x10670e` |
| TLS 初始化 / 连接 | `init_openssl` `0x14d04` / `connect_encrypted` `0x14d38` | `0x4d04` / `0x4d38` |
| BIO read / write | `read_from_stream` `0x14e10` / `write_to_stream` `0x14e6c` | `0x4e10` / `0x4e6c` |
| HTTPS 文件下载 | `get_https_file` `0x14ed0` | `0x4ed0` |
| 下载线程 | `download_thread` `0x15058` | `0x5058`；mutex 与累加 `0x15270–0x1528c` |
| stub / 下载初始化 | `broadband_test` `0x15330` / `speedtest_download` `0x15338` | `0x5330` / `0x5338`；图片路径 `0x1065dc` |
| ping | `get_ping_results` `0x15514` | `0x5514`；`0x1068d1` `ping -4 -c 3 %s | grep -ri 'round-trip'` |
| 模式 / 输出格式 | `.rodata` | `0x106909` `HTTPS`；`0x1069eb` `echo RESULTS %lld >> /tmp/https_result`；`0x106a4f` `echo RESULTS %lld >> /tmp/ttfbs_result` |

复核时读取单个 ELF，不需要读取代理目录中的证书或私钥：

```sh
readelf -sW "$SAMPLE" | rg 'main|broadband_test|stream|encrypted|speedtest|download|ping|ipv4|uptime'
r2 -q -e scr.color=0 -e bin.relocs.apply=true \
  -c 'aa; pdf @ main; pdf @ sym.connect_encrypted; pdf @ sym.read_from_stream; pdf @ sym.speedtest_download' \
  "$SAMPLE"
```
