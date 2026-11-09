# WE410443-ST：嵌套 EmbedUR 包解码

本篇针对 extender v6.02.00 build14，不是此前主路由器 ARM 样本。完整提取 squashfs 后，`usr/bin/embedur/erm_agent.tar.bz2` 仍不能直接用 BZip2 解压；这是文件内部的第二层 byte substitution。现在已静态还原并验证，无需设备执行权限或 flash key。

## 已解

`sbin/arc_embedur` 在解包前调用 `arc_swap`，然后用同目录的 `.sha256sum` 验证输出，再调用 `bunzip2` 和 `tar`。`sbin/arc_swap` 的 `main` 把只读段中的 256-byte table 复制到栈，循环读入一个 byte，写出 `table[input_byte]`。该 table 是 0–255 的排列，不是 AES key。

对 1,504,540-byte 原始包逐 byte 替换后，得到以 `BZh91AY&SY` 开头的标准 BZip2 流。输出 SHA-256 与固件自带校验文件完全一致，BZip2 解码到正常 EOF，无额外尾部数据，解压后的 tar 为 5,416,960 bytes。

安全提取结果：40 个 tar 成员，包括 1 个目录、39 个普通文件，没有 symlink、hardlink 或设备节点。其中有 15 个 ELF、11 个 shell script、4 个普通文本文件，其余为证书/密钥材料。后者仅保留在私有目录，不进入公开仓库。

这 15 个 ELF 包括 extender 自己的 `rrm_arcadyan_mtk`、`image_manager`、测速工具以及 MQTT/JSON 组件。尤其是 `image_manager`：本次已取得该 MIPS 版本的可读 ELF；不能把之前 ARM 样本的容器/key 未解问题直接套用为“此 ELF 仍加密”。ELF 可读也不表示它处理的所有外部加密镜像都已解开。

仓库工具 [decode_embedur.py](../re_tools/decode_embedur.py) 不执行固件程序：读取已核对版本的 `arc_swap` table，验证包内 SHA-256，限制解压大小与成员数量，拒绝路径穿越、重复路径、文件/目录冲突、链接和特殊文件。输出必须是 Git 外的新目录；不保留 archive 中的可执行位或所有权。

```sh
python3 re_tools/decode_embedur.py /path/to/extracted-rootfs /path/to/private/new-output
```

现有样本已通过此工具再次提取，与首次独立解码得到相同校验结果。

## 全 rootfs 文件分类与其他解码

对 rootfs 的 1,247 个普通文件逐一执行静态类型识别：258 个 ELF、110 个 POSIX shell script，另有 ASCII/Unicode/HTML/JavaScript 等文本和普通图片。`file` 标记为 `data` 的仅三个：上述 EmbedUR 包与两个相同 hash 的 512-byte WLAN EEPROM 模板。EEPROM 是二进制配置数据，类型未被 `file` 识别不构成“加密”的证据。

另已静态展开四个 web 文件中的五个已识别混淆块：三个文件里的四个 Dean Edwards packer block，以及 `global.js` 的 base64 → XOR 3 → JavaScript `unescape` wrapper。解码没有调用 `eval` 或执行页面。原始和解码后的文件、hash 与清单均保留私有；这只是已识别 wrapper 的覆盖，不证明不存在其他编码数据。

可复用工具为 [decode_web_assets.py](../re_tools/decode_web_assets.py)，扫描了166个web文本文件。自动筛选另报两个 `unresolved_candidate`，人工核对均没有静态 packed payload：`jquery.arctransform.js:201–208` 的 `arcTransInputHover` 执行 DOM focus/blur callback 字符串；`menu.htm:174–184` 的 `JumpMainMenu` 根据参数构造 frame 属性查询。这两个标签不是“仍加密”的证据；来源核对保留于私有 `web-tool-verified/runtime-eval-review.json`。

## 未解与边界

- 普通文件与嵌套包提取成功，不等于所有 ELF 都已逐函数理解；反编译覆盖另见 [覆盖记录](singtel-extender-decompile-coverage.md)。
- 两个 WLAN EEPROM 模板的逐字段语义尚未全部解释；未据熵或文件后缀猜测加密算法。
- 没有因此取得 bootloader 本体，也没有生成可接受签名的 custom 固件。
- `image_manager` 可执行文件的反编译，与它读取的外部加密容器/运行时 key，是不同的工作项。

## 证据索引

| 对象 | 证据 |
|---|---|
| 调用链 | `sbin/arc_embedur`：41/51 行调用 `arc_swap`，42/52 行核对 SHA-256，47/56 行 `bunzip2`，58 行 `tar xf` |
| table 初始化 | `arc_swap:main` VA `0x4006c0`；`0x400700` 指定 table VA `0x400be0`，`0x400704` 长度 `0x100`，`0x400708` 调用 `memcpy` |
| substitution | `0x400814` 读取输入 byte，`0x40081c` 计算 table 地址，`0x400824` 调用 `fwrite` 输出一字节 |
| table file offset | `0xbe0`，长度 `0x100`，256 个值均不同 |
| `arc_swap` SHA-256 | `4d34d38795f353519aeb417e10617efe0dd3341f3baa5a83c95de504a006bc58` |
| 原始嵌套包 SHA-256 | `352aa18da1e1a7c60d24d172447d0d055b346333a8ba2976a9849b5b9ff9da2d` |
| 解码后 BZip2 SHA-256 | `40c75d7a69d8dae985c98cd03c93405c52cddda04ffc4d3734283770de8fc006`，与自带 `.sha256sum` 匹配 |
| 私有完整清单 | `router-notes-private/decode-all-20261109/rootfs-file-types.json`、`embedur-archive-members.json`、`embedur-file-types.json`、`web-decoded/manifest.json` |

所有地址/偏移属于本篇明确的 `arc_swap` build；工具对其他版本拒绝沿用该 table offset。
