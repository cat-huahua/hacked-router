# Singtel Mesh 的登录锁 —— 完整机制

2026-10-14 反编译同厂 Singtel Mesh **Router** 的 `httpd`（ARM）逆出来的，
并在 Mesh **Extender**（WE410443-ST）上实测验证。

## 现象

登录失败几次后，登录页里会出现：

```js
var wait_secs = parseInt("-1");
```

| 值 | 含义 |
|---|---|
| `>0` | 倒计时。**期间连正确密码也不受理**，`login.cgi` 一律返回 `Location: /login.htm` |
| `=0` | 可以登录 |
| `=-1` | **永久锁**，登录按钮永远不启用，页面显示 `getLangM(1379)` |

## 实测排除掉的可能

| 假设 | 实测结果 |
|---|---|
| 重启能清 | ❌ 拔电源冷启动 70 秒后依然是 -1 |
| 跟设备时钟有关 | ❌ 把时钟从 2016 修到 2026，依然 -1 |
| 按来源 IP 记 | ❌ 换第二个源 IP 依然 -1 |
| 按 User-Agent 记 | ❌ 换 UA、换空 UA 依然 -1 |
| 按账号记 | ❌ 换 8 个用户名 × 若干密码，全部 -1 |

→ **锁是全局的、存在 flash 里的。**

## 真正的机制

函数注册表在 httpd 的 va `0x439e0`（`{名字指针, 函数指针}` 对），
`get_login_wait_sec` 的实现落在 va `0x39fe4`，它调用 `0x39f10`：

```c
int get_login_wait_sec_helper(void) {
    time_t now = get_time();
    if (some_check() == -1) return 0;

    char buf[...];
    if (mapi_ccfg_match_str(cfg, "ARC_SYS_LoginBlocked", buf) != 0)
        return -1;                      // ★★★ 配置里【存在】这个键 → 永久锁

    int count = *(int*)0x63f80;          // 失败计数（内存全局）
    // count <= 10 时按 2^(count-1) 秒退避
    ...
}
```

登录处理器（va `0x2e254`）：

```c
if (mapi_ccfg_match_str(cfg, "ARC_SYS_LoginBlocked", buf) != 0) {
    // 写一行 "Login function had been locked, waiting!" 到日志
    // 直接拒绝 —— 【根本不比对密码】
    goto reject;
}
if (get_login_wait_sec() == 0) { /* 才走正常认证 */ }
```

失败路径（va `0x2e698`）：

```c
int *p = (int*)0x63f80;
*p = *p + 1;                             // 计数 +1
*(time_t*)0x63f84 = get_time();          // 记最后一次失败时刻
if (*p > 9)                              // ★ 第 10 次
    goto 0x2e60c;                        //   → 写锁！
// 0x2e60c:
mapi_ccfg_set_str(cfg, "ARC_SYS_LoginBlocked", buf);
mapi_ccfg_commit(cfg);                   // 提交进 flash → 永久
```

成功路径（va `0x2e6e0`）：

```c
*(int*)0x63f80 = 0;                      // 计数清零
*(time_t*)0x63f84 = 0;
```

## 结论

1. **锁 = 配置分区里存在 `ARC_SYS_LoginBlocked` 这个键。** 值是什么无所谓，只有存在与否
2. **失败满 10 次就写进 flash 并 commit** —— 从此每次登录都在比密码**之前**被拒
3. **成功登录会把内存计数清零**，所以**只要密码对，重复登录是安全的**
4. **重启只清内存计数，清不掉 flash 里的锁**
5. **唯一可靠的清除办法是恢复出厂** —— 默认配置（`glbcfg.dft`）里没有这个键

## 附属发现

- 锁死期间 `login.cgi` **不评估凭证**：故意写错的密码也返回 `/login.htm`；
  正常未锁时错密码是 `loginpserr.htm`。**可以用这个区分"被锁"和"密码错"**
- `wait_secs` 是服务端烤进 HTML 的字面量，**改本地 HTML 没有任何用**
- 页面里的 `popup` / `pwderr` cookie 纯粹是客户端小旗子，跟锁无关

## 操作纪律（踩过坑之后的规矩）

```
每次尝试登录之前，先 GET /login.htm 读 wait_secs：
    不是 0 → 绝对不发登录请求
    是 0   → 只发一次，然后回读 wait_secs 确认没被加罚
连续失败接近 8 次时立刻停手，宁可拔电重启把内存计数清零
```

`singtel_mesh/login_once.py` 就是照这个纪律写的。

## 顺带一个免登录的只读通道

httpd 里有一张免登录路径白名单（va `0x53730`，共 26 条）。其中两条读 CGI
**不需要登录**（但需要从 `/login.htm` 取一个新鲜 token）：

```
GET /cgi/cgi_init.js?_tn=<token>&_t=<毫秒>
    → var def_product_name=("WE410443-ST"); var login_counter="10";
      （login_counter 是【阈值】不是当前计数）

GET /cgi/cgi_login.js?_tn=<token>&_t=<毫秒>
    → addCfg("password_reminder", ...);
      addCfg("fwversion1", ...); addCfg("fwversion2", ...);
```

## 另一个发现：整个固件升级流程是免登录的

```
/fw_upgrade.htm                200（免登录）
/firmware_upgrade_single.htm   200（免登录，含文件上传表单）
/chkpwd.cgi                    免登录（密码校验）
/fwcheck_single.cgi            免登录（固件预检）
/fwupload.cgi                  免登录（★ 写 flash 的接口）
/cgi/fwupgrade_status.js       免登录
/cgi/chkpwd_result.js          免登录
/cgi/fw_download_prg.js        免登录
```

表单字段：`owlsinglefile`（固件）、`resetFlag=1`、`reset=1`、`ConfirmPasswd`。
**`resetFlag=1` 是 JS 强制置位的** —— 也就是刷完固件会顺带恢复设置。

**很讽刺**：管理界面被一把锁焊死，但"上传固件并恢复出厂"这条最重的操作一步都不需要登录。
唯一的护栏是 `/bin/fw_upgrade` 用 `arca_validateImage` 验签，只收官方签名镜像。

---

# ★ 附：登录算法已从【可读源码】确认（2026-10-16）

早先这套算法是从 extender 那份**混淆过的 JS** 里逆出来的。后来在**同厂另一台设备**
（`Singtel-MeshRG`）的 **未加密 rootfs** 里找到了**没混淆的源码**，逐行核对**完全一致**。

## 1. `ArcMD5` —— `www/js/common/global.js`

```js
function ArcMD5(_s){
    var s = calcMD5(_s);                    // MD5，输出小写 hex
    var shaObj = new jsSHA(s, "ASCII");     // 拿 MD5 的 hex 字符串当输入
    s = shaObj.getHash("SHA-512", "HEX");   // 再 SHA-512，输出 hex
    return s;
}
```

即 `ArcMD5(x) = SHA512_hex( MD5_hex(x) )` ✓（与逆向结论一致）

## 2. 登录表单 —— `www/login.htm`

```js
document.tF2.user_name.value = ArcMD5( ArcMD5(userName)     + ArcBase._t() );
document.tF2.pws.value       = ArcMD5( ArcMD5(userPassword) + ArcBase._t() );
```

`ArcBase._t()` 就是 token 的 base64 形式：
`ArcBase._t = function(a){ var k = ArcBase._tt(); k = ArcBase.encode(k); return k }`

## 3. ★ token 从哪来 —— `ArcBase._tt()`（被 eval 混淆，已还原）

```js
ArcBase._tt = function(){
    var objs = document.getElementsByTagName("img");
    for (var i = 0, sz = objs.length; i < sz; i++) {
        x = objs[i].src;
        if (x.indexOf("data:") == 0) {
            return ArcBase.decode(x.substring(78));   // ★ 第一个 data: 图片的第 78 字符起
        }
    }
    return "";
}
```

**取页面里第一个 `src` 以 `data:` 开头的 `<img>`（那张 1×1 GIF），
对 `src.substring(78)` 做 base64 解码** → 得到 token（一个数字）。

> 混淆方式（顺带记录）：`enkripsi` 密文 → base64 解码 → **每字节 XOR 3**
> → `unescape` → 去掉前 19 个字符 → `eval("ArcBase._tt=function()" + ...)`。
> 变量名叫 `teksasli`（印尼语"原文"）—— 又一个厂商跨国复制粘贴的痕迹。

## 4. httpd 侧（同一个未加密 rootfs 的 `/usr/sbin/httpd`）

```
[%s] token=%lu from %s                     ← token 是个无符号长整数
[%s] check token before getting data
[%s] failed to pass token checking         ← 漏 httoken 字段就是这个
name="httoken"                             ← 表单必须带这个字段
httoken_output / ssi_httoken_output
ARC_UI_WEB_TOKEN_Disable                   ← 可以整个关掉
ARC_SYS_LoginEnable / ARC_SYS_LoginTimeout ← ★ 登录开关与超时（锁机制同一族）
```

**结论**：README 里写的那套登录流程（token 一次性、必须带 `httoken`、
必须带 Referer）现在每一条都有源码出处，不再是黑盒观察。
