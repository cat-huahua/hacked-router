# WE410443-ST 静态安全与可靠性问题清单

范围：Singtel WE410443-ST v6.02.00 build14；核对日期 2026-11-09。
本页整理已有反编译证据，区分代码缺陷、待核查线索和未成立的利用假设。
它不是“所有 bug”清单，也不表示任何一项已在设备上成功利用或动态复现。
没有将主路由器 ARM 样本的问题直接套用到本 extender 的 MIPS 固件。

## 已确认的静态缺陷

| 编号 | 组件与缺陷 | 触发前提 / 影响边界 | 修复方向 |
|---|---|---|---|
| E-01 | `httpd` 密码同步的本机 HTTP 转发只检查连接是否建立，不检查 `write` 的错误或短写，也不读取后端响应；随后可向页面返回 `ok` | 已进入该转发流程，且传输或 OWL 后端保存失败。页面成功提示不能证明密码已持久化；未证明匿名可达或可控制当前密码 | 完整写入并检查错误，读取结构化后端结果；只有确认所有写入和 commit 成功后才提示保存成功 |
| E-03 | `autofw` 使用 `VERIFYHOST=1`；该 vendor libcurl 在无 SAN 的 CN fallback 中只在值大于 1 时拒绝 hostname mismatch | 必须进入 HTTPS、证书链通过、走无 SAN 且有可解析 CN 的 fallback；CN 不匹配本身不会终止。SAN 路径仍拒绝不匹配，不表示 DNS 改写足够或可跳过 firmware footer | 使用 `VERIFYHOST=2` 并升级受支持 TLS 栈，针对 CN/SAN 匹配与不匹配做回归验证 |
| E-02 | `uboot_env:saveenv` / `program_img_2` 在打开、ioctl 或短写失败后仍可返回成功状态 | 调用者已具有本地执行和相应 flash 权限；影响可靠保存与错误可见性。不是 TFTP/bootloader 认证绕过 | 逐层传播 errno/失败状态，拒绝短写；完成写入后读回核对，避免向调用者报告假成功 |

E-01 可以解释一类“收到 `ok` 但密码没有如预期生效”的现象，这是**推断**。
仍没有设备日志或 flash 读回证明用户此前的 login bug 正是该原因。
E-02 同样不能解释全部断电设置丢失问题；env 与普通配置持久化是不同路径。

## 已观察到但尚不足以认定可利用的问题

| 编号 | 已观察到的代码事实 | 缺失证据 / 不应得出的结论 | 后续验证或修复方向 |
|---|---|---|---|
| Q-01 | `owl_sys_save_login_password` 检查 commit 返回值，但未分别检查两次配置字段 setter 的返回值 | 尚未完整建立 setter 失败语义、事务回滚语义与实际可触发条件；不能宣称必然产生部分提交 | 检查每次 set 的结果，失败终止事务；用 mock 配置后端做失败注入验证 |
| Q-03 | extender footer 使用 SHA-256，但 header / region 比较循环均只比较前 20 bytes | 这把摘要比较限制在 160 bits；本轮没有证明可行碰撞、签名旁路或修改镜像可被接受。原厂样本完整 32-byte digest 实际匹配 | 比较完整 digest，严格验证解码长度及结构；将格式兼容性和安全检查分别验证 |

原 Q-02 已通过该 vendor libcurl 的 assembly 核对，升级为 E-03。实际 CA 集合、服务端证书和网络可达条件仍未验证。

Q-03 的长度事实不自动说明旧主路由 checker 的所有索引边界问题也存在于 extender。
跨型号相似函数必须分别核对二进制，不复用未经验证的漏洞结论。

## 已排除的过度结论与仍开放的边界

- rootfs 已解码、footer 已离线解开，不等于拥有当前管理密码或已验证的免登录刷写通道。
- 普通 multipart 上传路径在 `sys_upgrade` 调用前有 token 检查；不能因底层写 flash 函数没有密码比较便称其匿名可用。
- `uboot_env` 是运行中 Linux 的工具，本身不另外询问密码并非 bootloader 口令旁路；仍需要已有执行及 MTD 权限。
- 未取得 bootloader 本体、实际 recovery 阶段的调用链与流量对应。WPS 灯色、DHCP 失败、A/B 切换不能单独证明进入某个联网恢复客户端。
- N9/CR4 MCU payload 仍加密，不能声称已审计内部代码。本轮已确认的 reset-IV 字段不一致及三项带前提的 loader 缺陷见 [解密链](singtel-extender-mcu-decrypt-path.md)与 [loader 审计](singtel-extender-mcu-loader-audit.md)；默认 source mode、输入完整性和远程可达性限制仍须保留。
- 早期脚本重复尝试新旧密码会影响登录锁状态；这些观测不能视作独立、无副作用的密码验证。

## 证据索引

仅链接公开技术描述，不包含口令、key、真实节点标识或工厂测试 CGI 的端点/参数。
原始 pseudocode、assembly 和敏感字符串继续留在私有输出目录。

| 条目 | 符号 / VA / 文件偏移 / 字符串证据 | 详细来源 |
|---|---|---|
| E-01 | `httpd` 转发 helper `0x42f270`；`write` `0x42f3d0`、close `0x42f3e8`、返回 0 `0x42f3f4`；caller `0x433f7c–0x433ff0`；字符串 `ok` VA `0x448988` / off `0x48988` | [密码保存链](singtel-extender-password-change.md) |
| E-02 | `uboot_env:saveenv` VA `0x401358` / off `0x1358`，无条件成功 `0x401384`；`program_img_2` VA `0x401758` / off `0x1758`，末尾返回 `0x4018bc` | [boot access](singtel-extender-boot-access.md) |
| Q-01 | `libArcOWLcore.so:owl_sys_save_login_password` VA / off `0x68b00`；setter `0x68b4c`、`0x68b6c`；commit `0x68b84`，返回检查 `0x68b90` | [密码保存链](singtel-extender-password-change.md) |
| E-03 | `autofw` 设置点 `0x401e1c–0x401e30`；libcurl 原始 ELF VA/file `0x1b854–0x1b860` 保存选项，`0x1f100–0x1f144` 对 CN mismatch 的阈值为 2；SAN mismatch `0x1ef30` 仍失败 | [autofw vendor TLS 分支](singtel-extender-autofw.md) |
| Q-03 | `arc_uploadhelper:sha256_hash` VA `0x40cd84`；比较循环 `0x402508–0x40253c`、`0x4025c0–0x40260c`，终值 `0x14`；这些 RX 段 file offset = VA − `0x400000` | [footer 格式与验证](singtel-firmware-footer.md) |
| 上传限制 | `httpd` token 调用点 `0x41c73c`；失败分支 `0x41cdd4`；后续升级调用 `0x41c9b8`、`0x41c9f4` | [密码保存链的访问限制](singtel-extender-password-change.md) |
| MCU 未解边界 | `MT7615_FirmwareImage`、`MT7615_CR4_FirmwareImage`，三个 region 的 encryption bit 均置位 | [MCU 映像](singtel-extender-embedded-mcu.md) |

输入 TRX SHA-256：
`ac8b23b324798f6a52465b6d6857e4fa8297fbd6c2b602d69f13537ed73514df`。
各 ELF 身份 hash 见上述来源的证据索引。整理覆盖的是这些已追踪路径，
不是全固件认证、网络解析、内存安全及并发行为的完整审计。
