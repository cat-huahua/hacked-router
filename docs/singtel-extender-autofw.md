# Extender autofw：本机兼容更新服务协议

静态对象：已恢复 extender rootfs 的 `usr/sbin/autofw`，MIPS32 little-endian ELF。
SHA-256：`8933428ea737eab326bae33b9bf69ecf5cdd12749fe1c0dc3235e82a38154027`。
本文未运行目标、未连接路由器、未发送更新请求。所有示例只用占位值。

## 已解：服务端的三条接口

客户端从 JSON 配置中的 `Url` 取 base URL（注意大小写），以字符串拼接后缀。
默认配置路径为 `/etc/autofw.conf`，可由 `autofw -f <conf_file>` 指定。
`/etc`为运行时目录；固件模板位于`/usr/share/config/etc/autofw.conf`。
模板本身不能证明真机最终URL，仍需追踪配置生成者。

| 方法 | 路径（base之后） | 请求内容 | 响应 |
|---|---|---|---|
| POST | `/GetFirmwareVersion` | 当前设备版本信息 | `Result` / `New Version` / `Image Location` |
| POST | `/FirmwareDownloadResult` | 下载/处理结果信息 | `Result` |
| POST | `/FirmwareUpgradeResult` | 升级结果文件中的JSON | HTTP成功状态；完整结果消费见限制 |

三者 POST 使用 `Content-Type:application/json;charset=UTF-8`。字段名包含空格，
不能替换成常见的 `serial_number`、`version` 等名称。

版本查询请求的准确字段形态：

```json
{
  "Serial Number": "<serial>",
  "Product Class": "<product-class>",
  "Current Version": "<current-version>"
}
```

这些值来自 autofw_options 的 `+0xa4`、`+0x124`、`+0x1a4`；
base URL 位于 `+0x24`。配置 parser 将 `Url`、`SerialNum`、`ProductClass`、
`CurrentVersion` 作为对应字符串来源。

## 已解：更新响应最小schema

`0x404abc` 开始的定时检查函数先查询服务端，再解析响应对象：

```json
{
  "Result": 0,
  "New Version": "<advertised-version>",
  "Image Location": "http://<local-server>/firmware/<image-file>"
}
```

| 字段 | 读取函数 | 控制行为 | 证据 VA / file offset |
|---|---|---|---|
| `Result` | `json_object_get_int` | 必须存在且值为0才继续下载检查 | `0x404bf8–0x404c44` / `0x4bf8–0x4c44` |
| `New Version` | `json_object_get_string` | 非NULL后调用 `is_new_version` | `0x404c48–0x404c9c` / `0x4c48–0x4c9c` |
| `Image Location` | `json_object_get_string` | 非NULL后直接传给 `upgrade_to_new_firmware` | `0x404d14–0x404d5c` / `0x4d14–0x4d5c` |

**静态事实：** `is_new_version` (`0x402610`) 只有 `jr ra` 和 delay-slot
`li v0,1`，没有字符串或版本数比较。因此这个二进制并不靠 `New Version`
防止相同版本或降级。它要求字段可读取，不等于验证版本字符串的语义。
`Result=2` 进入不下载路径；其它非0值也不会到达下载调用。本篇不赋予其它值未经
证实的业务名称。若仅实现不触发更新的兼容服务，可返回 `{"Result":2}`。

返回下载URL是独立完整URL，不是相对base的路径：调用链直接把它传给curl URL选项。
实际执行前还检查内存条件；成功返回schema不保证一定开始刷写。

## 已解：HTTP与TLS行为

`post_json_data` 与 `download_file` 均调用公共 helper `0x401d80`，第三参数均传1。
helper 设置以下curl选项，数字来自实际 `curl_easy_setopt` 参数：

| 选项数字 | 对应选项 | 实际值 | 代码 VA |
|---:|---|---|---:|
| 10002 | `CURLOPT_URL` | 调用者传入URL | `0x401db0–0x401dc0` |
| 41 | `CURLOPT_VERBOSE` | 1 | `0x401dc8–0x401ddc` |
| 13 | `CURLOPT_TIMEOUT` | 300秒 | `0x401de4–0x401df8` |
| 64 | `CURLOPT_SSL_VERIFYPEER` | 1 | `0x401e0c–0x401e14` |
| 81 | `CURLOPT_SSL_VERIFYHOST` | **1** | `0x401e1c–0x401e30` |
| 10097 | `CURLOPT_CAPATH` | `/usr/cert/` | `0x401e34–0x401e48` |

**结论的边界：** 如果真机配置用 HTTPS，改DNS到PC只改变连接目标，不能单独满足
服务端证书的CA链验证。样本显式开启 VERIFYPEER，而没有设为0。
另一方面，VERIFYHOST的实际值是1；不能把它写成现代常用的2，或未核对便声称
完整hostname匹配已启用。捆绑 `libcurl.so.4` 含 `libcurl/7.19.6` 字符串，历史版本
和厂商补丁的具体hostname行为需继续查看该libcurl实现。

如果通过合法的本机配置控制 `Url` 为 HTTP，则这条服务链支持HTTP，TLS选项对HTTP
不会建立TLS会话。二进制本身还有内置HTTP测试地址默认值（此处不复制地址）。
这并不证明用户当前设备的配置可通过DNS改变scheme：DNS本身不能把https改成http，
也不能改变使用IP字面值的URL。

POST设置 `CURLOPT_HTTPHEADER=10023`、`CURLOPT_POSTFIELDS=10015`、
WRITEFUNCTION=20011、WRITEDATA=10001。POST与下载均在perform成功后读取
`CURLINFO_RESPONSE_CODE=0x200002`，只把 **HTTP 200** 作为成功。
这不是只要求2xx，也没有由本轮证据确认开启FOLLOWLOCATION。
兼容本机服务应直接响应200，并避免依赖301/302跳转。

## 已解：结果回报

`/FirmwareDownloadResult` 请求来自 `0x404138` 附近的构造代码，格式字符串为：

```json
{
  "Serial Number": "<serial>",
  "Product Class": "<product-class>",
  "Current Version": "<current-version>",
  "New Version": "<advertised-version>",
  "Result": 0
}
```

`Result` 是客户端实际处理结果的整数，不一定为0。
服务端兼容响应为 `{"Result":0}`；客户端在 `0x4042e0–0x404384`
解析并返回服务端Result。缺字段或无法解析进入失败/默认处理，不宜返回空body。

升级后回报读取 `/tmp/autofw_reboot` JSON并序列化，POST至
`/FirmwareUpgradeResult`。该文件构造时包含 `Serial Number`、`Product Class`、
`Current Version`、`Previous Version`、`Result`；这与下载结果的
`New Version` 字段并不相同。本机服务可接收并保存解析后的对象，返回200与JSON对象；
本轮未完整确定这一接口是否另要求业务Result，因此不能把这个建议称为实机验证。

## 已解：接受URL不等于接受固件

`upgrade_to_new_firmware` (`0x405344`) 顺序是：

1. `download_file(Image Location, "/tmp/FirmwareImage")`。
2. 成功才调用 `validate_firmware_image` (`0x402618`)。
3. 校验通过才进入 `0x404f60` 的上传/升级封装。
4. 最后删除临时镜像。

因此本机服务协议只能让客户端取得文件；它没有绕过镜像格式、CRC或下游升级工具
的校验。本篇不建议修改bootloader，也没有证据表明DNS重定向可修改bootloader。
对是否适合目标机型的镜像，仍需独立核对其容器/flash布局/校验约束。

## 证据索引

本ELF代码及rodata的映射为 `VA=file offset+0x400000`。

| 符号/原字符串 | VA | file offset | 证据用途 |
|---|---:|---:|---|
| 公共curl helper | `0x401d80` | `0x1d80` | URL、timeout、TLS设置 |
| `post_json_data` | `0x401e8c` | `0x1e8c` | JSON POST、HTTP200检查 |
| `download_file` | `0x4020bc` | `0x20bc` | 文件下载，调用相同TLS helper |
| `is_new_version` | `0x402610` | `0x2610` | 始终返回1 |
| `validate_firmware_image` | `0x402618` | `0x2618` | 下载后的独立验证 |
| query请求构造 | `0x404000` | `0x4000` | base/path、JSON来源映射 |
| check定时函数 | `0x404abc` | `0x4abc` | 响应schema、调用下载 |
| `upgrade_to_new_firmware` | `0x405344` | `0x5344` | 下载→校验→升级 |
| `/usr/cert/` | `0x405abc` | `0x5abc` | CA目录 |
| `Content-Type:application/json;charset=UTF-8` | `0x405ac8` | `0x5ac8` | POST header |
| `Url` | `0x405e50` | `0x5e50` | 配置字段名 |
| `SerialNum` / `ProductClass` / `CurrentVersion` | `0x405e54`, `0x405e60`, `0x405e70` | `0x5e54`, `0x5e60`, `0x5e70` | 身份/版本字段来源 |
| `%s/GetFirmwareVersion` | `0x406170` | `0x6170` | query接口 |
| query JSON原格式 | `0x406188` | `0x6188` | 三字段精确名称 |
| `%s/FirmwareDownloadResult` | `0x4061f4` | `0x61f4` | 下载回报接口 |
| 下载回报JSON原格式 | `0x406210` | `0x6210` | 五字段精确名称 |
| `Result` | `0x406298` | `0x6298` | 响应业务状态 |
| `%s/FirmwareUpgradeResult` | `0x4062a0` | `0x62a0` | 升级回报接口 |
| `New Version` / `Image Location` | `0x4063cc` / `0x4063f4` | `0x63cc` / `0x63f4` | 更新响应字段 |
| `/tmp/FirmwareImage` | `0x406600` | `0x6600` | 下载临时文件 |

## 未解

- 真机运行时的Url与接口路由；配置生成者与出厂公共URL已在后续补充确认。
- libcurl 7.19.6厂商构建对VERIFYHOST=1的精确实现，以及CA目录运行时内容。
- 结果回报所有数值的业务意义、重试/重启窗口的完整状态机。
- HTTP响应buffer边界、超长/异常JSON容错；本轮未做fuzz或目标执行。
- 完整footer验证的离线复现仍未完成；后续flash路径已补充，仍需与recovery链分开验证。

## 本机服务代码与验证

`autofw_server.py` 实现上述三条POST接口，以及固定 `/firmware.bin` 下载路径。
默认仅监听loopback，返回`Result=2`；不保存或输出请求中的设备身份字段。

```sh
# 只验证协议，不提供更新
python3 autofw_server.py --bind 127.0.0.1 --port 8080

# 提供已有镜像；以下地址与路径均为占位示例
python3 autofw_server.py --bind 192.0.2.10 --port 8080 \
  --firmware /private/original.trx --version '<version>' \
  --image-url http://192.0.2.10:8080/firmware.bin
```

第二条须替换为本机真实局域网地址及目标机型镜像。服务代码不执行DNS变更、
不连接设备、不生成新签名、不调用flash命令；启动服务也不能保证设备会发起查询。
HTTPS可传`--cert`和`--key`，但证书仍必须满足设备现有trust设置。
没有以生产服务身份获得有效证书的证据，因此目前不能声称只改DNS即可工作。

Loopback合成测试覆盖默认无更新、精确响应schema、原字节下载、结果回报、
坏schema和其它路径拒绝。实际设备互通与改写镜像刷入尚未验证。

## 后续静态解码：CRC之后还有独立的footer验证关卡

本节补充上文未解项。**恢复rootfs并重算CRC，不足以证明重打包镜像能通过正常autofw路径。**
后续链已经定位为：

```text
autofw validate_firmware_image
  → _eval(["arcupload", image_path, "linux", NULL])
  → arcupload startup
  → /tmp/arc_uploadhelper start linux [可选参数]
  → helper 生成 /etc/update.conf
  → helper verify_firmware_signature
  → startup成功才进入arcupload update_image
  → 再次检查]Cot CRC → erase/write指定MTD
```

此链属于运行中Linux的正常更新器。它不等同bootloader recovery mode，不能由这条链
的校验规则推导recovery mode一定采用相同容器或接受相同镜像。

### ]Cot容器与CRC的实际范围

`autofw:validate_firmware_image` 先读取28 bytes，检查：

- `+0x00` little-endian magic=`0x746f435d`，即 `]Cot`。
- `+0x04` 声明长度至少28。
- `+0x08` 预期CRC值。
- 从 header `+0x0c` 开始的16 bytes先参与CRC，初始state为`0xffffffff`。
- 随后从file `+0x1c`继续读内容并更新同一个CRC state，最后与`+0x08`比较。
- `+0x0c` 的 bit0改变循环的长度记账：置位先把声明长度减28；未置位则第一轮
  把已读28-byte header加入计数字节，但这28 bytes不重复参与CRC。

因此两分支均排除了头12 bytes，实际CRC覆盖 header最后16 bytes和其后声明范围内的
payload。代码以最多1024-byte chunk读入。CRC的具体poly/最终异或应由其导入实现
核对，不应误用libz的常见参数次序：本函数调用形式是 `crc32(pointer,size,state)`。

证据：autofw `0x402730–0x402748`（magic/length），`0x4027d0–0x402810`
（header CRC与bit0），`0x40282c–0x4028e0`（读入/累计），
`0x4028fc–0x402960`（CRC和长度比较）。
`arcupload` 内 `0x401090` 另有同形态的CRC校验，并由 `update_image` 内 `0x402e20`调用。
这些检查没有代替下述helper验证。

### footer与加密封装验证

`arc_uploadhelper:main` 在 `start linux` 分支，先调用 `0x401d74`，成功后调用
`verify_firmware_signature` (`0x40201c`)；函数返回失败会变成helper进程非零返回。
`arcupload:main` 检查 `startup` 的 `system()` 返回，非零便不调用 `update_image`。

验证函数读取完整文件，先核对 `]Cot`，根据头部长度定位一个 `0x290`-byte footer。
footer末尾四个字符逐byte比对为 `HDR0`（`0x4023d4–0x402424`）。它还检查
footer中的索引和长度范围，分别在 `0x402440–0x40247c`。
原始错误字符串包括 `no signature.`、`can not find signature magic number.`、
`Wrong key index or no signature.`。

随后有两次 `0x4011a0` 的封装解码调用；该内部函数调用 `R_OpenInit`、
`R_OpenUpdate`、`R_OpenFinal`，不是直接比较一个明文SHA值。
`verify_firmware_signature` 再调用导出名为 `sha256_hash` 的函数，分别处理
一个 `0x14c`-byte记录与声明长度的镜像数据，并对解码结果作word比较。
两次比较循环上界均是 `0x14`，即比较20 bytes（`0x402508–0x40253c`、
`0x4025c0–0x40260c`）。

**静态事实与未知分界：** 本样本确有比CRC更深的footer/hash/加密封装验证；
本轮没有完整验证每个key slot、封装算法参数和异常输入分支，也没有导出任何key。
不能只因二进制导出RSA/DES符号便将这个格式简写为“标准RSA签名”，更不能声称
保留旧footer后任意修改payload仍会通过。重打包镜像目前只能视为离线研究产物，
尚无这条完整验证链可接受它的证明。

### flash去向与配置生成

`arc_uploadhelper:0x401d74` 生成的linux更新配置原格式为：

```ini
[method]
tools=default
[erase]
partitions=<selected-kernel-partition>
[write]
<selected-kernel-partition>=0x0:-
```

候选分区名为 `Kernel`、`Kernel2`，由 `0x401b78` 返回的bootpartition状态选择。
这里只确认A/B镜像分区选择；本轮不把返回值和真机当前bank绑定。
`0x401d74` 写出配置后，`arcupload:update_image` 从 `/etc/update.conf`读取，
由 `/proc/mtd`取得名称/大小映射并通过 `merge_sector_info`合并。
默认writer `do_default_update` (`0x4023c4`) 打开相应MTD，使用ioctl操作并分段
`write`；实际写调用位于 `0x402680–0x40268c`，每次最多`0x2800` bytes。
程序还包含nandwrite/ubi替代后端，但本次linux配置明确选`tools=default`。

这补充了镜像最终写到哪个类别分区的证据；不能由这条linux路径推断bootloader被修改。

## 后续静态解码：配置生成者与默认公共服务

已找到出厂模板 `/usr/share/config/etc/autofw.conf`，它是待启动时复制/重写的模板，
不是前述缺失的运行时 `/etc/autofw.conf`。模板末尾有trailing comma，直接用严格
Python JSON parser会报错；这不等于目标所用json-c一定拒绝它。

真正配置生成者是 `/usr/agents/arca-autofw-agent.so:start_autofw` (`VA 0x0d70`)。
它通过 `mapi_ccfg_get_str` 读取精确键 `ARC_SYS_AUTOFW_Url`，再按
`"Url": "%s",`写进配置（`0x0e9c–0x0ed0`）。这个SO第一段映射基址为0，
上述VA也等于file offset。

出厂 `usr/share/config/etc/config/glbcfg.dft` 的对应项为：

```text
ARC_SYS_AUTOFW_Url=https://firmware.singnet.com.sg
```

这是固件内公共服务域名，不含设备标识或凭据。文件还出现另一个全大写后缀`URL`
的不同项；agent实际读取的是混合大小写`Url`，不能把两者混淆。
真机的持久化配置、运营商迁移或用户修改仍可覆盖出厂值，当前运行URL尚未观测。

## 后续证据索引

| 样本 | SHA-256 |
|---|---|
| `sbin/arcupload` | `182ee1ce0639c4e99a3c00cc2da06c467e4f91d762a8b4722e410034f617f8c2` |
| `sbin/arc_uploadhelper` | `3e8c63e6ec8949adbc480f01b4af05c21e6f29ab3216d836052ec77c2d8d1814` |

上述两个EXEC文件代码/rodata均为VA−`0x400000`得到file offset。

| 样本/证据 | VA | file offset |
|---|---:|---:|
| autofw CRC函数 | `0x402618` | `0x2618` |
| autofw构造arcupload argv | `0x405174–0x405194` | `0x5174–0x5194` |
| autofw `_eval`调用 | `0x40521c–0x40522c` | `0x521c–0x522c` |
| arcupload `startup` | `0x40313c` | `0x313c` |
| arcupload startup失败阻止update | `0x400e64–0x400ea4` | `0x0e64–0x0ea4` |
| `/tmp/arc_uploadhelper start %s`原格式 | `0x403e80` | `0x3e80` |
| arcupload重复CRC函数 | `0x401090` | `0x1090` |
| arcupload `update_image` | `0x402cc0` | `0x2cc0` |
| arcupload `do_default_update` | `0x4023c4` | `0x23c4` |
| helper `start linux`验证调用 | `0x401444–0x401490` | `0x1444–0x1490` |
| helper `verify_firmware_signature` | `0x40201c` | `0x201c` |
| helper config writer | `0x401d74` | `0x1d74` |
| config原格式字符串 | `0x40d27c` | `0xd27c` |
| `Kernel2` / `Kernel` | `0x40d254` / `0x40d25c` | `0xd254` / `0xd25c` |
| helper内部封装decoder | `0x4011a0` | `0x11a0` |
| helper `sha256_hash` | `0x40cd84` | `0xcd84` |

尚缺的最终验证是：对原厂样本复现完整footer校验，然后对离线重打包产物复现同一检查；
在此之前不宣布修改后的镜像可供recovery或正常更新安全刷写。

## 已解：本样本 `]Cot` 头 +8 的 CRC（2026-10-24）

按上文恢复的真实覆盖范围，对原厂样本执行：

```python
length = int.from_bytes(image[4:8], 'little')  # 0xde3000
crc = zlib.crc32(image[12:length]) ^ 0xffffffff
# 0xd5e90d3b，与header +8完全一致
```

这里不把length再加28，也不覆盖最后64KiB footer。先前多种CRC猜测没有命中，
不能据此认为算法未知或需要硬件材料；真实范围是关键。

`usr/lib/libarc-shared.so.0.1` 的导出 `crc32` 位于VA/file `0x7818`，
长度80 bytes。`0x7834–0x785c` 实现reflected查表更新，输入state为第三参数，
直接返回state，没有末尾取反。table位于VA/file `0xa3d8`，前四项为
`00000000 77073096 ee0e612c 990951ba`，对应reflected CRC-32表。
这支持上面的zlib等价式：初始raw state=FFFFFFFF，最终保留raw state。

本结果覆盖当前原厂样本的flag bit0=0分支；其它flag/长度异常组合仍按代码独立验证。
CRC恢复不解决footer封装或签名接受问题。
