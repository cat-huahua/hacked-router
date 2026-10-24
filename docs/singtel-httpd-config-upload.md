# Singtel httpd：配置上传与恢复分支

材料：主路由 WG9116AEAC23-ST `/usr/sbin/httpd`。
只恢复静态路径；未向设备发送上传、restore 或 reboot 请求。
本篇不涉及工厂测试 CGI。

## 已解：multipart 类型分派

上传主体解析后，扫描 `Content-Disposition` 一行的子串：

| 字段 / 条件 | 内部 type | 后续路径 |
|---|---:|---|
| `name="file"` 且同一行不含 `.rom` | 1 | helper `0x26ec8`，最后一个参数为 0 |
| `name="file"` 且同一行含 `.rom` | 4 | 记录日志；同一 helper，最后一个参数为 1 |
| `name="restore"` | 2 | 写配置临时文件并调用 restore 流程 |
| `name="plcfile"` | 6 | 已有固件上传路径 helper `0x27640` |
| 未命中且扫描结束 | 3 | fallback / 错误路径；不能当作任意文件保存接口 |

这里是 `strstr` 检查，`.rom` 不是严格的文件扩展名解析；type 4 也不能只根据日志
就写成“立即拒绝”，代码仍会进入 helper。类型 1/4 的具体镜像规则继续参见
[固件升级链](singtel-firmware-update.md)，并保留 helper 内部行为待查。

公共处理以最多 `0x400` 字节的行缓冲区跳过 multipart header，检测空行。
如果 Content-Type 含 `boundary=`，以其后字符串长度加 8 作为尾部长度扣减；
这说明这里靠预先调整剩余字节数截取 body，不能推断为完整的流式 MIME parser。

## 已解：type 2 的文件与事务路径

```text
multipart body
  → helper 0x2738c(request, "/tmp/glbcfg.user", stream, &remaining)
  → helper 0x2d53c("/tmp/glbcfg.user", "/tmp/glbcfg")
  → 仅当该 helper 返回 0 且 access("/tmp/glbcfg", F_OK)==0
       mapi_ccfg_restore(transaction, "/tmp/glbcfg")
       mapi_tmp_set(transaction, "VAR_RESTORE_BACKUP_FLAG", "1")
       mapi_ccfg_commit(transaction)
```

`0x2d53c` 是配置准备/转换 helper，内部包含配置查询、shell 命令和条件分支，
不能简化为一次无条件 AES 解密。既有备份加密算法见
[配置恢复](config-recovery.md)；这里不复制任何固定口令或完整含凭据的命令模板。

`mapi_ccfg_restore` 的返回值**没有被检查**，随后调用 commit 并将 commit 的返回值
保存为结果。因而“页面结果为 0”并不单独证明每个 restore 操作都成功。
准备 helper 返回非零、或输出文件不存在时，type 2 不会走上述 restore+commit 分支。

另有 type 3 到 `mapi_ccfg_restore(transaction, "/etc/config/glbcfg.dft")` 的代码分支，
随后共用 commit。正常未知字段分派 / 错误路径还有多处跳转；当前没有证明普通
未知字段请求必然可达该默认配置分支，不能直接将其描述为恢复出厂 API。

## 已解：写临时文件的 helper

`0x2738c` 接受目标路径、输入 stream、剩余长度指针。确定行为：

- 用长度为 `0xff` 的 `snprintf` 构造目标文件名，然后 `fopen`。
- 对普通 stream 获取并保存 fd flags，设置 `O_NONBLOCK`；结束时恢复 flags。
- request 特殊读模式走 `as_read`，普通模式走 `waitfor(fd,5)` 和 `safe_fread`。
- 分块最大 `0x400` 字节；写 `safe_fwrite`，更新剩余长度。
- 关闭输出文件，普通模式恢复输入 flags；路径中有 0、-1 和 `0x16` 返回值。
  上传调用点只做 signed 非负/负判断，不能把所有非负返回值都解释成已完整接收。

这里没有把用户给出的原始 filename 拼成目标路径；type 2 的目标是固定临时文件。
仍需进一步审计短读、短写、超时和并发上传时的状态，不能据此宣称整个上传流程安全。

## 已解：结果与 reboot

公共结束路径写临时结果，并将数值写入配置 ID `0x0006003a`。
既有字段映射将其识别为 `ARC_SYS_TempUpgradeResult`。
函数还调用响应输出 / 连接收尾 helper；内部结果为 0 时继续：

```text
mng_action("reboot", "") → sleep(8) → kill(1, 15) → pthread_exit(2)
```

所以成功配置恢复会与固件上传共用最终 reboot 收尾，不能当作“只写配置、无需重启”。
这只是代码行为描述，没有在设备上执行。

## 未解

- type 1/4 helper 的完整镜像判定、type 5 的来源以及 torrent / VPN 独立上传处理。
- `0x2d53c` 中每个配置模式的全部分支；本文只确认调用与成功判断。
- type 3 默认配置分支的完整外部可达条件。
- 本篇不证明认证绕过、远程可利用性或所有错误路径均已覆盖。

## 证据索引

以下为 ELF VA；可执行 LOAD 中 file offset = VA - `0x10000`。

| 内容 | VA / 符号 | 字符串 / 证据 |
|---|---|---|
| 字段与 type | `0x25ff0–0x260b8` | `.rodata` VA `0x4b8e0` `name="file"`、`0x4b8ec` `.rom`、`0x4b930` `name="restore"`、`0x4b940` `name="plcfile"` |
| header 空行 / 尾长 | `0x26124–0x261ec` | `0x400` buffer，LF/CRLF，`boundary=` |
| helper 分派 | `0x26230–0x262dc` | `0x26ec8` / `0x2738c` / `0x27640` |
| 固定临时路径 | `0x2629c` / `0x2630c–0x2631c` | VA `0x4b998` `/tmp/glbcfg.user`；`0x4b9ac` `/tmp/glbcfg` |
| 准备与存在检查 | `0x2631c–0x2633c` | helper `0x2d53c`，`access` |
| restore 与 flag | `0x263a0–0x263c4` | `mapi_ccfg_restore`；VA `0x4b9d8` `VAR_RESTORE_BACKUP_FLAG` |
| 默认配置分支 / commit | `0x2643c–0x26454` | VA `0x4ba08` `/etc/config/glbcfg.dft`；`mapi_ccfg_commit` |
| 临时文件写入 | helper `0x2738c–0x2763c` | `as_read` / `safe_fread` / `safe_fwrite` / `waitfor` |
| 数值结果 | `0x26558–0x26588` | `arc_cfg_set_long`，ID `0x6003a` |
| reboot 收尾 | `0x265c4–0x265f8` | `mng_action`、`sleep(8)`、`kill(1,15)`、`pthread_exit(2)` |

样本 SHA-256：`231e1b7d2b8de4c6f2d884d33a92e78f9f69ecbeb574a2e7e089380e580f1096`。
