# Extender 强制改密：真实页面流程与旧脚本混淆

本页分析 **WE410443-ST v6.02.00 build14** 刚解出的原始 rootfs，
并对照 Claude 归档及本机旧脚本。只读静态分析，未执行页面/固件、未登录或改动设备。
本文不包含实际口令、节点名称、MAC 或 SSID。

## 结论

已确认 `change_pwd.htm` 先请求 `syncpasswdconfig2`，返回 `ok` 才调用公共
`subForm`。**不能只看到隐藏表单的 `action=login.exe` 就认定浏览器第二阶段
一定 POST `login.exe`。** 本 build 的 `subForm` 默认 `genfrm=1`，会生成另一个
提交到 `apply_abstract.cgi` 的表单，并用它替换传入的 `frm`。

旧改密脚本直接 POST `login.exe`，且复用前一次请求的 token；它们没有完整复刻
这个公共 helper。归档中“`.exe` 全废了”“`syncpasswdconfig2` 只清闸门不写密码”
“漏最后提交导致半提交”的说法，**目前没有充分证据成立**，不再作为已查实 rootcause。

用户确实观察过改密失败，旧脚本也记录新旧密码不匹配；这些现象应保留。
它们不能单独说明密码最终存了什么，或是哪一步造成失败。

## 已解：强制改密页面的两阶段控制流

`www/change_pwd.htm` 的源代码可直接读取：

1. `50–82`：检查两次输入一致、非空、非空白以及密码规则。
2. `87–97`：禁用输入，将 `encode(pwd)` 放入名为 `pws` 的元素，读取
   `ArcBase._t()`，向 `/cgi-bin/toplogy.cgi` POST：
   `httoken`、`cmd=syncpasswdconfig2`、`data=encoded_password`。
3. `98–103`：只在响应文本严格等于 `ok` 时调用
   `subForm({frm:document.tF2,next:'index.htm',uploadtype:0,wait:7})`。
   非 `ok` 分支重新启用输入并提示失败。
4. `204–208`：页面确有隐藏表单 `tF2`，其 action 是 `/cgi-bin/login.exe`，
   包含 `url`、空 `name`、`pws`。但调用者没有指定 `genfrm:0`，因此应继续读
   `subForm` 的实现，而不是把该 action 当作最终网络请求。

`www/js/global.js` 给出实际 helper 语义：

| 位置 | 静态行为 |
|---|---|
| `1639` | 每次调用都先置 `top.G_option.genfrm=1` |
| `1642–1648` | 默认 `cmd=""`、token=`ArcBase._t()`、`to="apply_abstract.cgi"` |
| `1657–1661` | 仅将调用者显式提供的已知 option 覆盖进去；本页没有覆盖 `genfrm` / `to` |
| `1664–1666` | `genfrm=1` 时调用 `genForm('OUT',top.G_option)`；只有 `genfrm=0` 才为原表单加 token |
| `1383–1386` | `frmHead` 生成 POST 表单，action 取 `option.to`，带 `action`、`httoken`、`submit_button` |
| `1413–1423` | 从公共 `CA` 配置数组和额外表单元素生成其余字段 |
| `1675–1676` | 将 `top.G_option.frm` 覆盖为新生成的 `document.OUT` |
| `1425–1431` | `subForm_T()` 等进度状态后，对该表单调用 `.submit()` |

因此，本 build 这条强制改密路径的公共 helper **静态上选择了生成表单路径**，
目标为相对 URL `apply_abstract.cgi`。本页没有给它指定非空 `cmd`。
生成表单具体还包含哪些 `CA` 字段取决于初始化/动态 CGI 数据；本轮未穷尽。
它是否承担“落盘”、等待状态还是其他收尾功能，需要后端进一步验证。

这也是为什么“`login.exe` 的请求失败”不能直接证明浏览器原始流程失败于同一点。

## 已解：旧脚本与页面不一致

以下是现有旧脚本的只读核查结果。本页只记代码机制，不复制配置值或凭据：

| 文件与行号 | 行为 | 对结论的影响 |
|---|---|---|
| `chpwd2.py:29–40` | 从强制改密页取 `TOK`，POST `syncpasswdconfig2` | 第一阶段与页面结构相符 |
| `chpwd2.py:43–46` | 直接 POST `/cgi-bin/login.exe`，再次带同一 `TOK` | 绕过了 `subForm` 的 `genfrm/to` 逻辑；也混入 token 重用因素 |
| `do_chpwd.py:55–78` | 同样先同步、再直接 POST `login.exe`，复用 `TOK` | 不能称为完整浏览器复刻 |
| `chpwd.py:46–62` | 最多 20 轮重复测试新旧登录，没有先检查 `wait_secs` | 这些失败会影响登录锁状态，不能当成独立、无副作用的验证 |
| `login_once.py:47–79` | 先确认 `wait_secs=0`，只登录一次，失败后回读锁状态 | 后期已有更谨慎的单次诊断脚本；本轮没有运行 |
| `final_apply.py:55–116` | 接受强制改密会话，分别用新 token 写 WiFi 和节点配置 | 当时网络配置恢复不等于管理密码已修好 |

归档 `chat/transcript.md:12405` 明确记录：登录消耗 token 后，复用它向配置 CGI
提交导致字面 `error` / `BadStatusLine`；`20879` 再次总结这一修正。
这建立了 token 重用的历史混淆，但**不证明所有端点都以完全相同方式消费 token**。
因此本页不声称重新取 token 就必然能修复改密。

公共 helper 本身也从页面读 token，并没有在上述代码中额外 GET 一个新页面；
它与旧脚本最明确、最直接的差异是**第二阶段生成并提交的表单路径**。
是否存在请求后 token 更新、特殊 CGI 豁免或异步状态关系，仍需后端核查。

## 已解：普通改密页面是另一条路径

读取原始 `www/system_p.htm` 及先前保存的页面可见：

- 普通路径先向 `setpwd.cgi` 提交表单，字段包括 `pws=ArcMD5(new)`、
  `chk=ArcMD5(old)`、`usr=ArcMD5(user)` 等。
- 轮询 `cgi/setpwd_result.js` 成功后，再向 topology CGI 请求
  `syncpasswdconfig`，数据包含编码后的旧、新密码。
- 该路径的普通表单提交处显式指定 `genfrm:0`，与强制改密页省略该 option 不同。

这证明存在两套前端流程，**不能由此倒推 `syncpasswdconfig2` 从不写本地密码**。
要解释真实配置写入，必须继续追后端处理函数和 commit 路径。

## 历史观察与尚未证明的解释

| 归档位置（`chat/transcript.md`） | 可以保留的内容 | 不能直接升级为事实的解释 |
|---|---|---|
| `12405` / `20879` | token 重用曾导致脚本请求失败 | 不代表其他失败必然也是同一原因 |
| `12615` / `12714` | 记录了两个候选密码被拒 | 未证明 flash 里写成哪个值 |
| `12716` | 当时提出“半提交”假设 | 没有配置快照或写调用链支持该状态 |
| `17218` | 用户明确提出修复 password-change bug 的需求 | 不能仅重刷同版本就保证修好 |
| `17875–17942` | 改密后闸门消失，直接 `.exe` 请求失败；发现普通路径 | 原始 `subForm` 控制流未被旧脚本完整复刻 |
| `29600–29640` | 最新记录网络正常、管理密码仍不匹配 | “最可能半提交”仍属推断 |

登录锁也应单独区分：`wait_secs=-1` / 持久配置锁与 password-change 失败不是同一个
已证明 rootcause。对已锁状态重复登录，甚至不会进入普通凭证比较。

## 未解

- MIPS extender `httpd` / OWL 库中 `syncpasswdconfig2`、`setpwd.cgi` 的完整配置写入链。
- `syncpasswdconfig2` 返回 `ok` 的精确条件、是否表示同步/本地写/落盘成功。
- 原始 helper 第二阶段生成表单中动态 `CA` 字段、空 action 的后端语义。
- 每条相关端点的 token 校验/消费、异步响应和权限规则。
- 本机当时密码最终值与失败根因；没有 flash 读回证据。

本轮对 `httpd` 做了符号/字符串及小范围反汇编。发现含日志标签
`check_and_setpwd` 的函数 `0x42b29c`，其中 `0x42b3bc–0x42b3d4` 在相应比较成功
分支调用 `arc_cfg_set`，配置数字 ID 为 `0x60010`。**尚未建立该函数到强制改密
入口的完整调用关系**，所以不能据此宣称强制路径已恢复或将此 ID 直接当修复接口。

## 证据索引

| 材料 | SHA-256 / 定位 |
|---|---|
| Extender 原始 `www/change_pwd.htm` | `6bdc02e3f8fb594abf2c6ebb417c9a8896ba70a2c695caa01894c1e1fd9dc8a7`；`50–109`、`204–210` |
| Extender 原始 `www/js/global.js` | `0e1295c5a110a621da66fcd76edeba1dd50945d541e36740520378e9972dca4d`；`1383–1424`、`1425–1431`、`1637–1682` |
| Extender 原始 `usr/sbin/httpd` | `f0e4028bb4ced6c08615828e274b3e77f6d94ac9d08957560021cc369cdf553e`；MIPS32 little-endian ELF |
| httpd 密码相关字符串 | `syncpasswdconfig2` VA `0x4493ac` / off `0x493ac`；`check_and_setpwd` VA `0x4499e0` / off `0x499e0`；`sys_setpwd_cgi` VA `0x449a0c` / off `0x49a0c` |
| httpd 有界写调用观察 | VA `0x42b3bc–0x42b3d4` / file off `0x2b3bc–0x2b3d4`；`lui a1,6; addiu a1,a1,0x10`；导入 `arc_cfg_set` |
| 本机旧脚本 | `singtel_mesh/chpwd2.py:29–46`、`do_chpwd.py:55–78`、`chpwd.py:46–62`；只读，未复制其中配置 |
| 原始流程对照 | Extender `www/system_p.htm`；历史保存页面 `pages/system_p__system_p.htm:163–177,321–340` |
| 历史现象与推断 | 本地 Claude 归档 `chat/transcript.md` 上表所列行号；含敏感内容，未上传归档 |

证据边界：本页是原始页面和 ELF 的静态解释，不表示已经抓到真实浏览器请求，
也不表示修改镜像或设备验证通过。
