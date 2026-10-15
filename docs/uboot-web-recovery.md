# u-boot 的 Web 恢复模式 —— 一条不经过密码的刷机入口

**状态：已从公开源码确认存在，尚未在真机上验证。** 2026-10-15。

## 为什么这条路重要

设备上所有的刷机入口都被两样东西守住了：

| 入口 | 拦路虎 |
|---|---|
| Web 管理界面上传固件（`/fwupload.cgi`） | 只收**官方签名**镜像（`arca_validateImage`） |
| 串口菜单的 TFTP | **bootloader 密码**（社区至今没解） |
| OpenWrt 刷机 | 同上，所以社区最后都去拆 SPI |

**但 u-boot 的 Web 恢复模式在 bootloader 层** —— 在操作系统**之下**，
所以：没有登录锁、没有会话、没有 `wait_secs`、**也可能没有签名校验**
（签名是上层 `/bin/fw_upgrade` 干的）。

## 证据：公开源码里有完整的实现

`ec-/u-boot-mt7621`（基于 **MediaTek SDK 5.0.1.0**，和设备上的
`Ralink UBoot Version: 5.a.0.1` 同源）源码里有一整个 `httpd/` 目录：

```
uboot-5.x.x.x/httpd/httpd.c          21KB   ← web 服务器本体
uboot-5.x.x.x/httpd/main.c                  ← uIP 主循环
uboot-5.x.x.x/httpd/vendors/general/index.html   ← 恢复网页
```

**关键：`httpd.c` 里 `uip_listen(HTONS(80))` —— 开在 80 端口，
而整个请求处理只有 GET/POST 解析，一行鉴权代码都没有。**

恢复页面提供的上传表单：

```html
<form enctype="multipart/form-data"><input type="file" name="uboot">    <input value="Update U-Boot"></form>
<form enctype="multipart/form-data"><input type="file" name="firmware"> <input value="Update Firmware"></form>
<form enctype="multipart/form-data"><input type="file" name="config">   <input value="Update Config"></form>
<form enctype="multipart/form-data"><input type="file" name="radio">    <input value="Update Radio"></form>
<form enctype="multipart/form-data"><input type="file" name="initramfs"></form>
```

**它能写 bootloader 本身、写固件、写配置 —— 而且表单里没有任何密码字段。**

README 的原话：

```
- U-Boot will perform switch to Web Recovery mode on flash content integrity fail.
- Alert LED(s) is blinking in Recovery mode and on erasing/flashing.
- Much enhanced Web Recovery functionality, ...
```

**"Much enhanced" 意味着【原厂本来就有】这个功能**，那个 fork 只是增强了它。

## 怎么进（按社区惯例）

| 项 | 值 |
|---|---|
| **触发** | 开机时按住 **WPS 键 2~3 秒**（有的厂商用 reset 键） |
| **设备 IP** | **`192.168.1.1`** |
| **你的电脑** | 静态 **`192.168.1.2/24`** |
| **入口** | `http://192.168.1.1`（80 端口） |
| **也可以** | `curl -F "firmware=@file.bin" 192.168.1.1` |
| **自动进入** | flash 内容完整性校验失败时 u-boot 自己切过去 |

**触发键和 IP 因厂商而异**（有的用 `192.168.0.1`，有的会自己开 DHCP）。

## 真机验证步骤（安全，不写任何东西）

```
① 电脑插 USB-网卡转接器，配成 192.168.1.2/24
② 把那台设备的网线从主路由上拔下来，只接电脑     ← 隔离，避免它的 DHCP 跟家里打架
③ 拔电源 → 按住 WPS → 插电源 → 按 2~3 秒松手
④ 抓包 / ping 192.168.1.1

   出现了 → 拿到 bootloader 层的写接口，可以用 curl 上传任意镜像
   没出现 → 它正常启动，什么也没发生，零损失
```

**风险极低**：这只是让它换一种启动模式，不写任何东西。
最坏情况是它照常启动。

## 如果成功，下一步能做什么

1. **先传一个不带密码的 u-boot 进去** → 从此串口菜单也自由了
2. **传 OpenWrt 的 initramfs** → 拿到一个完全可控的 Linux
3. Hmm — 也可以**读**：如果恢复模式有下载/备份功能，就能把 `config` 分区
   （里面有明文的管理密码）拿出来

## 待验证的问题

- [ ] 原厂 Arcadyan 的 u-boot 到底有没有开这个 httpd
- [ ] 触发键是 WPS 还是 reset
- [ ] IP 是 192.168.1.1 还是别的
- [ ] **它到底验不验签名**（这是最关键的一条）

## 参考

- <https://github.com/ec-/u-boot-mt7621> —— 含 httpd 恢复源码
- <https://github.com/Ser9ei/u-boot_mtk> —— 更广的 MTK u-boot fork，含 HTTPD failsafe repair
- <https://docs.gl-inet.com/router/fr/4/faq/debrick/> —— GL.iNet 的 u-boot 救砖流程（192.168.1.1）
