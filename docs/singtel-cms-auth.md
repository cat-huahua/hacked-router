# CMS 控制台的认证（`cmsDal_authenticate`）

> 设备：Arcadyan WG9116AEAC23-ST（v5.02.00 build09b）
> 材料：`libcms_dal.so` 的 `cmsDal_getCurrentLoginCfg` / `cmsDal_setLoginCfg` /
> `cmsDal_authenticate`
> 结论：**CMS 控制台有 3 个账号槽位，口令以明文 `strcmp` 比较。**

---

## 1. `LOGIN_CFG` 对象

对象 ID：**`0xC30`**（`cmsObj_get(0xC30, ...)`）。

结构（从 `getCurrentLoginCfg` 的 `strcpy` 偏移反推）：

| 对象偏移 | 内容 | 说明 |
|---:|---|---|
| `+0x04` | username1 | 槽位 1 |
| `+0x08` | password1 | 槽位 1 口令 |
| `+0x10` | username2 | 槽位 2 |
| `+0x14` | password2 | 槽位 2 口令 |
| `+0x1C` | username3 | 槽位 3 |
| `+0x20` | password3 | 槽位 3 口令 |

`getCurrentLoginCfg(out)` 把它们展开到：

```
out+0x00 = username1    out+0x10 = password1
out+0x40 = username2    out+0x50 = password2
out+0x80 = username3    out+0x90 = password3
```

---

## 2. 认证逻辑

`cmsDal_authenticate(int *out, int type, const char *user, const char *pass)`：

```
对象 = cmsObj_get(0xC30)

if (type == 2) {
    if (user == username2 && pass == password2) {
        *out = 2;
        return 1;
    }
}
else if (type == 1 || type == 3) {
    if (user == username1 && pass == password1) {
        *out = 0x0A;
        return 1;
    }
    if (user == username3 && pass == password3) {
        *out = 1;
        return 1;
    }
}
else return 0;

return 0;
```

★ **全部是 `strcmp` 明文比较** —— 没有 MD5/SHA/crypt，也没有加盐。

### 结果码

| `*out` | 含义 |
|---:|---|
| `0x0A` (10) | 槽位 1 认证成功 |
| `2` | 槽位 2 认证成功 |
| `1` | 槽位 3 认证成功 |
| `0` | 失败 |

### type 的含义（推断）

| type | 使用的槽位 | 可能角色 |
|---:|---|---|
| 1 / 3 | 槽位 1（失败再试槽位 3） | admin / support |
| 2 | 槽位 2 | user |

> 字符串里有 `admin` 和 “username cannot be admin,support,user or nobody”
> （添加账号时的保留名），与此对应。

---

## 3. `setLoginCfg` 只改口令

`cmsDal_setLoginCfg(in)`：

```
cmsObj_get(0xC30)
free(password1); password1 = strdup(in+0x10)
free(password2); password2 = strdup(in+0x50)
free(password3); password3 = strdup(in+0x90)
cmsObj_set(...)
```

即：**只更新三个口令**，用户名由别的路径设置（默认值/工厂数据）。

---

## 4. 与 web 管理密码的区别

| 系统 | 账号 | 存储 | 比较方式 |
|---|---|---|---|
| **CMS / consoled** | 3 个槽位 | `LOGIN_CFG` 对象（config flash） | **明文 `strcmp`** |
| **web 管理界面** | `admin` | `.glbcfg` 的 `ARC_SYS_Password` | 页面 `ArcMD5` 算法 |
| **SSH/root** | `admin` | `/data/passwd` | 系统 `crypt()` |

三套是**独立**的，改一套不会自动改另外两套。

---

## 5. 安全观察

1. **CMS 口令明文存储**：只要拿到 config flash / `cfgview dump`，
   就能直接读出三个账号的口令。
2. **CRC 不是加密**：config flash 的 CRC 只防损坏，不防读取。
3. **`consoled` 用的是这套认证**：串口/本地控制台如果启用了 `consoled`，
   口令就是 CMS 的口令。
4. **结果码区分角色**：0x0A / 2 / 1 分别对应三个槽位，便于判断当前登录角色。
5. **`encodePassword` 存在但 `cmsDal_authenticate` 没用它** ——
   说明编码可能只用于 web/其他路径，CMS 这条是裸比较。

---

## 6. 证据索引

| 内容 | 地址/位置 |
|---|---|
| `cmsDal_authenticate` | `0x11264`（340 字节） |
| `cmsDal_getCurrentLoginCfg` | `0x7DC8` |
| `cmsDal_setLoginCfg` | `0x8DFC` |
| 对象 ID | `0xC30`（`LOGIN_CFG`） |
| 口令比较 | `strcmp`（无哈希） |
| 保留名 | `admin` / “username cannot be admin,support,user or nobody” |
