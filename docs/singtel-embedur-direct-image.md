# EmbedUR `direct` 与 `image`：接收分派和固件分片

本轮只做静态反汇编，未运行目标、连接 broker 或设备。材料是交接归档内已提取的 `erm_agent/rrm_bcm_arm`，SHA-256 为 `05976d3c211fbf0107aa4f858bb16b5e7ce22d24441ab46c70a5374071de1325`。工具为 `readelf -SW`、`r2`，并用 ARM `BL` immediate 解码交叉检查直接调用点。下述函数名除导入符号外均为分析用描述名，不声称恢复了原始符号。

## 已解：`image` 并不是 JSON payload

`0x7040c` 构造 `devices/%s/image`，把接收函数 `0x70034` 注册到 topic handler 表，再调用通用 subscribe。这个 callback 将第二参数当作 payload 地址、第三参数当作字节长度，没有调用 `json_loads`。

接收分成两种消息：

1. 以 ASCII `len:` 开头的消息：用 `atoi(payload + 4)` 得到预期总长。此前必须已有非空 image filename；否则输出 `firmware: No image name`。它构造 `/tmp/%s`，以 `open(..., 0x241, 0x1f8)` 创建/截断输出文件，并将 packet 计数置 1、已接收字节数清零。
2. 其余消息：作为原始 binary fragment，直接 `write(fd, payload, payload_len)`。累计的是 `write` 实际返回值；累计值达到预期长度后关闭 fd，检查落盘文件长度是否恰好等于预期值，相等才置完成标志。这里没有 JSON envelope、base64 或分片序号解析。

因此旧文档中 `image` payload 留空应补充为「ASCII length announcement + binary fragments」。这一结论只覆盖本样本 callback；MQTT 发送端如何分包、是否允许重传仍未解。

## 已解：固件 metadata 来自 JSON `firmware` 数组

JSON 处理路径在 `0x55374–0x553d8` 读取 `firmware` 字段，随后调用 `0x70544`，传入本地 model、current version、current MD5，以及第五参数 1。`0x70544`：

- 要求输入为非空 JSON array，遍历元素并读取 `model`，用 `strcmp` 与本地 model 匹配。
- 匹配项要求存在 `version`、`filename`、`md5` 三个节点。
- `version` 字符串与当前版本用 `strcmp` 比较；MD5 字符串与当前 MD5 用 `strcasecmp` 比较。这里是「不相等」判定，不是语义版本高低比较。
- 新 MD5 字符串复制到全局状态 `0x2a06ac + 0x10`，filename 复制到 `+0x0c`；需要升级时置 `+0x20 = 1`。
- 此调用传第五参数 1，因此设置 `+0x08 = 1`，没有在 `0x70840` 立刻 tail-call 请求函数；请求由其余调度路径触发，完整时序尚未恢复。

`0x7040c` 请求时生成的文本模板是 `/firmware?_device_id=%s&filename=%s`，发布函数调用为 `0x5a884(request, "firmware")`。这里保留原始 query key `_device_id` 的前导下划线。

上述 MD5 比较是 metadata 的升级决策，不能等同于已验证下载镜像内容的 MD5，更不能等同于签名验证。

## 已解：topic callback 优先，普通 JSON fallback

通用 MQTT 接收路径在 `0x5ca0c–0x5ca28` 按 topic handler 表调用 `callback(topic, payload, len)`。没有专用 callback 时，`0x5ca58–0x5cafc` 对 payload 加 NUL，转交 `0x58d2c`；后者通过 `sendto` 发送到本地 JSON socket。普通 JSON fallback 有 `0x10000` 字节上限。

本轮 `aaa` 的直接调用检索只发现 `image` 和 `adornment` 注册专用 handler，`direct` 订阅本身位于 `0x59e68`。结合 callback 表分派，**推断** `direct` 通常进入 JSON fallback；未穷尽所有间接注册/动态状态，不把这个有界搜索说成全程序证明。

## 已解：`action.type = command` 在此 build 中不执行

大型 JSON handler 内 `0x5448c–0x544b4` 读取当前对象的 `action`，再读取 `action.type` 和 `action.command`。当 type 为 `command` 且 command 节点存在，`0x54d78–0x54dcc` 只走日志分支，日志原文为 `Not executing command - removed from build`，随后进入共同后续处理，没有把该 command 字符串传给 `system`。

这修正了根据 `direct` 名字或 `command` 字符串推断「云端任意 shell command」的做法。其他 action 分支的确有 `system` 调用；本结论只针对这个明确的 `command` 分支。当前对象的完整 JSON 层级、所有 action 类型及其 build 条件仍需继续追踪，不提供未经确认的完整可发送 payload。

`0x272ac` 构造的是回报 JSON：`type=accesspoint`、`statetype=runtime`、`category=device`，在 `common.direct` 放入整数 `id`、字符串 `status`、字符串 `response`，随后以 `runtime` 类别提交给 `0x5d4e0`。这是上报结构，不能倒推成下发结构。

## 已解：接收后的一个安装路径；未找到可复用打包器

直接调用检查发现 `0x49688` / `0x49844` 查询完成条件 `0x703c8`，随后 `0x496ac` / `0x49864` 调用 `0x6fc78`。`0x6fc78` 若 filename 含 `.bz2`，构造把 `/tmp` 下文件移到 `/data/embedur/erm_agent.tar.bz2` 的命令；成功后切断 filename 中 `.bz2` 子串。其后设置 60 秒 alarm，执行包含清除 runtime、结束启动进程、调用 `/sbin/arc_embedur start` 的安装流程。它是现有代理包的安装/重启路径，不是 recovery-mode 整机固件打包器。

本轮没有证明所有 `image` 接收结果都必须经过 `image_manager`，也没有恢复 `image_manager` 的完整 argv。不能把其签名/解密机制自动套到这里每一条路径，更不能据此生成可刷写镜像。关于容器本身已有 [image_manager 分析](singtel-embedur-image-format.md)。

## 未解

- `direct` 下发的完整 envelope 与每个 action 的配置落点。
- `firmware` 数组所属的完整 JSON 层级、延迟请求调度、下载内容 MD5 的全部检查链。
- 分片重复、乱序、短写、超时的完整状态行为；本轮未做运行验证。
- `image_manager` argv、AES key 来源与 recovery-mode 镜像兼容性；没有可复用的新镜像打包器证据。

## 证据索引

此 ELF 的 `.text` / `.rodata` 均满足 file offset = VA − `0x10000`；下表显式列关键起点，范围内其他 VA 可同式换算。BSS 地址不对应文件内容。

| 结论 | VA / file offset | 指令或原始字符串 |
|---|---|---|
| 样本布局 | `.text` VA `0x16a50` / off `0x6a50`；`.rodata` VA `0x1bd088` / off `0x1ad088` | `readelf -SW` |
| image callback 注册 | `0x70484` / `0x60484` | `ldr r1, [0x70534]` → `0x70034`；`bl 0x5cb48`；随后 subscribe |
| length 消息 | `0x70048` / `0x60048` | `strncmp(..., "len:", 4)`；`0x700bc–0x700c8` 调用 `atoi` 并存总长 |
| 输出文件创建 | `0x700f4` / `0x600f4` | `snprintf(..., "/tmp/%s", filename)`；`0x70140–0x70158` 调用 `open` |
| 原始分片 | `0x7024c` / `0x6024c` | `mov r2,r5; mov r1,r8; bl write` |
| 收齐/精确长度 | `0x702fc` / `0x602fc` | 累加 write 返回值；`0x7033c cmp r0,r3`；`0x70344 streq ...,[r4,0x1c]` |
| firmware JSON 入口 | `0x55374` / `0x45374` | `json_object_get(...,"firmware")`；`0x553d8 bl 0x70544` |
| model 匹配 | `0x70618` / `0x60618` | `json_object_get(...,"model")`；`0x70640 strcmp` |
| metadata 字段 | `0x706a0` / `0x606a0` | `version`；`0x706c8 filename`；`0x706e0 md5` |
| 升级判断 | `0x7072c` / `0x6072c`；`0x70798` / `0x60798` | `strcmp(new_version,current_version)`；`strcasecmp(new_md5,current_md5)` |
| 请求文本 | `0x1d633e` / `0x1c633e` | `/firmware?_device_id=%s&filename=%s` |
| topic 分派/JSON fallback | `0x5ca0c` / `0x4ca0c`；`0x5cac8` / `0x4cac8` | 间接 callback；复制 payload 并 `bl 0x58d2c` |
| direct 订阅 | `0x59e74` / `0x49e74` | `ldr r0,... "direct"`；tail-call `0x59a04` |
| action 字段 | `0x5448c` / `0x4448c` | `action` → `type` / `command` |
| command 被移除 | `0x54d78` / `0x44d78`；字符串 `0x1ce261` / `0x1be261` | 比较 `command`；`Not executing command - removed from build\n` |
| 回报字段 | `0x27418` / `0x17418` 至 `0x27494` / `0x17494` | `id`、`status`、`response` → `common.direct`；类别 `runtime` |
| 完成后安装 | `0x49688` / `0x39688`；`0x496ac` / `0x396ac`；另 `0x49844`、`0x49864` | 直接 `BL 0x703c8` / `BL 0x6fc78` |
| 代理包路径 | `0x6fca8` / `0x5fca8`；`0x1d5f28` / `0x1c5f28` | `.bz2`；`cd /tmp && mv %s /data/embedur/erm_agent.tar.bz2` |
| 安装重启路径 | `0x6fe14` / `0x5fe14` | `alarm(0x3c)`；`0x6fe38 bl 0x86d10`；命令字符串 `0x1d5fed` / `0x1c5fed` |

`r2 aaa` 对若干 switch/basic block 提示不完整；本页结论依据列出的逐条 ARM 指令及直接调用点，不把自动函数覆盖率当作完整恢复证明。
