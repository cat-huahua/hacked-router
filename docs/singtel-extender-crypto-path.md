# Extender squashfs：真实 crypto 路径是两层 byte 变换

本轮静态对象为解压后的 MIPS little-endian kernel，大小 7,743,232 bytes；SHA-256：
`9ccc2e7356de88658bbd1c905035695fc032f4784e697ec28cc3cc5c2cd4fb7a`。
uImage load address 是 `0x81001000`，本篇所有 kernel VA 都按
`VA = file offset + 0x81001000` 换算。未运行 kernel 或访问设备。

## 已解：纠正旧文的地址和 AES 推断

旧文中 file `0x53a878` 的 `get_decrypt_keys` 是 **ASCII 字符串**，不是函数代码。
它的 VA 是 `0x8153b878`，也不是用旧基址推算的 `0x8153a878`。

实际引用在 `0x81134f50–0x81134f58`，调用 `printk` 的位置在 `0x81134f64`。
它处于 `squashfs_xz_uncompress` 内部，是 byte 处理异常路径打印的函数名。
本轮没有发现一个独立 kallsyms 符号叫 `get_decrypt_keys`；将其视作内联 helper
是**推断**，其真实代码已经直接由引用点和控制流定位。

**静态事实：** 此路径先对 compressed input 做固定 XOR/rotate，再调用 XZ decoder，
然后对 decoder 输出做固定、逐 byte 的 substitution。两层变换代码都直接位于明文
kernel；这条路径没有从 flash 取 AES key 的调用，也没有调用 AES/ECB。
`CONFIG_CRYPTO_AES/ECB` 启用并不能证明 squashfs 实际使用 AES。
此前“遍历候选 AES key 不命中，所以必须 SPI dump”的论证不成立。

这不证明固件其它加密设施没有设备 key，完整提取的验证结果见下文。
本篇记录的变换需结合 squashfs block/fragment 结构使用，不能盲目应用到完整镜像。

## 已解：kallsyms 地址表的精确配对

旧 `kallsyms_extract.py` 在这份样本有两个限制：错从真实 names 起点前 23 bytes
开始，产生一个 garbage 条目；又因合法符号名超过工具的 80 字符限制而提前停止。

| 表/计数 | file offset | 静态校验 |
|---|---:|---|
| addresses | `0x55a140` | 32,911 个 little-endian u32，整体非递减 |
| num_syms | `0x57a380` | u32=`32911` |
| names | `0x57a390` | 每项单 byte 长度+token索引，按num_syms完整解码 |
| names 结束 | `0x5d8d87` | 最后符号为 `bklist_remove_lock` |
| markers | `0x5d8d90` | 129 项，全部等于每第256个name相对names起点的偏移 |
| token_table | `0x5d8fa0` | 256个NUL结束token |
| token_index | `0x5d9320` | 256个u16，精确指回每个token |

前三个 address/name 对分别为 `_text=0x81001000`、
`run_init_process=0x81001400`、`_stext=0x81001400`。
`addresses + 32911*4 = 0x57a37c`，距 num_syms 有4字节padding。
这些检查联合排除了“错位一项但看似有效”的配对。

## 已解：compressed input 的第一层

`squashfs_xz_uncompress` 从 buffer_head 数据复制一段输入到临时 buffer，
对该段的每一个 byte 原地执行：

```python
def decode_compressed_byte(x):
    v = x ^ 0x45
    return ((v >> 3) | (v << 5)) & 0xff
```

证据：`0x81134e48–0x81134e5c` 调用 `memcpy`；
`0x81134e6c–0x81134e8c` 的 `lbu → xori → sll 5 → srl 3 → or → sb` 循环。
这里的常量是算法指令立即数，不是读取出的设备凭据。
转换后 buffer 被放到 XZ input 结构：`+4=input`、`+8=input_pos=0`、
`+0xc=input_size`，随后调用 `xz_dec_run`。

用旧文已经记录的第一个数据块前六 bytes 作离线一致性检查：第一层输出
恰好是 `fd 37 7a 58 5a 00`，即 XZ magic。这是静态算法的已知格式核对，
比“启用了ECB，所以猜AES”的证据更直接。后续已完成全rootfs提取，见下文。

## 已解：XZ output 的第二层

`xz_dec_run` 返回后，代码计算本次 output buffer 新增的字节数并原地转换。
准确的 byte 变换为：

```python
def decode_output_byte(x):
    v = x
    if (v & 1) == 0:
        v ^= 0xda
    if v & 0x80:
        v ^= 0x55
    m = v & 0x28
    if m == 0:
        v ^= 0x76
    elif m == 8:
        v ^= 0x5e
    elif m == 0x20:
        v ^= 0xab
    elif m == 0x28:
        v ^= 0xd5
    return v
```

证据范围：`0x81134f0c–0x81134f34` 定位本次新增输出区间；
`0x81134f84–0x81134fcc` 及 `0x811350b8–0x811350c0` 执行转换。
注意 MIPS branch delay slot：`0x81134f3c`、`0x81134f48`、`0x81134fb4`、
`0x81134fc8` 的 XOR 必须随前面的条件分支一起读，不能把文本顺序当高级语言顺序。

对全部256个输入值作穷举，这个函数有256个不同输出，是 bijection；
它不是 involution，不能用“同一个函数再跑一次”完成反向编码。
这项检查只验证恢复的 byte 函数性质，不执行固件代码。

`v&0x28` 只可能是 `0/8/0x20/0x28` 四种值；异常日志路径
`0x81134f4c–0x81134f70` 不会被合法 byte 的这组分支命中。
`get_decrypt_keys` 字符串是在这条防御性日志中使用，并不表示此处会从外部取key。

## 证据索引

| 符号/对象 | VA | file offset | 用途 |
|---|---:|---:|---|
| `squashfs_read_data` | `0x811307c0` | `0x12f7c0` | block读取入口；不能误认为crypto函数 |
| `squashfs_fill_super` | `0x811341dc` | `0x1331dc` | mount/superblock逻辑 |
| `squashfs_decompressor_init` | `0x81134bf4` | `0x133bf4` | 建立decompressor |
| `squashfs_xz_uncompress` | `0x81134cc0` | `0x133cc0` | 包含两层转换的真实函数 |
| compressed-byte循环 | `0x81134e6c` | `0x133e6c` | XOR+rotate |
| output-byte循环 | `0x81134f84` | `0x133f84` | 条件XOR substitution |
| output高位分支 | `0x811350b8` | `0x1340b8` | 第二层的bit7条件 |
| `get_decrypt_keys`（原字符串） | `0x8153b878` | `0x53a878` | 日志中的helper名称 |
| 字符串引用 | `0x81134f50` | `0x133f50` | `lui a1,0x8154; addiu a1,-0x4788` |
| `printk` | `0x81526314` | `0x525314` | helper异常日志调用 |
| `xz_dec_reset` | `0x811755e4` | `0x1745e4` | XZ状态reset |
| `xz_dec_run` | `0x811756c4` | `0x1746c4` | 解压调用，在函数内有两处 |
| `memcpy` | `0x8116ca40` | `0x16ba40` | 将读取到的compressed输入复制至临时buffer |

复核可使用 `r2 -q -a mips -b 32 -m 0x81001000 -e cfg.bigendian=false` 打开 raw
kernel，然后 `pd` 上述地址；避免自动检测把 raw binary映射到错误基址。

## 已解：完整 rootfs 提取验证

样本 `WE410443-ST_v6.02.00_build14.trx` 的 squashfs 起点为 `0x2d001c`。
提取出的 squashfs 大小11,677,668 bytes，SHA-256：
`b5b3a1cfb4591c72cf17fd8af2ccdc454547e750fdb996811afae3ba1042c935`。

`extender_rootfs.py` 编译 host-only `arc_xz_shim.c`，仅在子进程环境中设置
`LD_PRELOAD`，由原生 `unsquashfs` 读取metadata/block/fragment。
shim拦截 `lzma_stream_buffer_decode`：识别完整6-byte encoded XZ magic后才转换输入，
liblzma验证并解压成功后转换新增output；标准XZ流直接透传。
不执行任何固件ELF，不改动原始镜像，不覆盖既有输出目录。

```sh
python3 extender_rootfs.py /path/to/rootfs.sqsh /path/to/private/new-rootfs
```

本机真实样本两次完整提取均成功，无error：

| 对象 | 实测结果 |
|---|---|
| files | 1247 |
| directories（包括根目录） | 98 |
| symlinks | 334 |
| 普通文件总长度 | 36,718,027 bytes |
| `bin/busybox` | MIPS32 rel2 LE ELF，853516 bytes |
| busybox SHA-256 | `4832a3cb81c5ffd7df7ef2326db5cd82b278ad7e7904ccca493d79e4c4465e19` |
| `usr/sbin/autofw` SHA-256 | `8933428ea737eab326bae33b9bf69ecf5cdd12749fe1c0dc3235e82a38154027` |
| `usr/sbin/httpd` SHA-256 | `f0e4028bb4ced6c08615828e274b3e77f6d94ac9d08957560021cc369cdf553e` |

完整输出保存在仓库外私有目录，不上传rootfs、凭据或密钥。
合成测试覆盖全部256种明文byte经逆substitution、XZ、逆rotate编码后还原，
另验证标准XZ透传和坏流拒绝。成功提取确认本样本需要的metadata/fragment均可读取。

## 未解与后续验证边界

- 尚未构建反向打包工具；能提取不代表修改镜像满足容器CRC/签名/flash布局。
- 未逐项审计全部文件内容、symlink目标与xattr；提取不等于恢复原始源代码。
- `get_decrypt_keys` 在源码中是否为单独inline函数仍是推断；已确认日志引用与byte代码。
- recovery mode接受条件与bootloader写入权限尚未由本篇证明。
- DNS重定向改变连接目标，是否能取得固件还要检查HTTPS证书、更新协议与最终镜像验证。
