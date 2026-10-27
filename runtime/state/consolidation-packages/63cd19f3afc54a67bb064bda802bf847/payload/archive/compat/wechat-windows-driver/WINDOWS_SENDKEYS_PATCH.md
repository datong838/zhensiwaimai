# Windows 驱动 SendKeys 转义修复（针对「电销+直播攻坚组」打开会话失败）

> 适用对象：Windows 机器上**正在运行**的 `driver.py`（被 `server.py` 加载的那一份）
> 根因确定性结论：群名含 `+`，`uiautomation.SendKeys` 把 `+` 当 **SHIFT 修饰键**而非字面字符
> → 搜索词残缺 → 搜不到目标群 → 退回点错会话 → 报「打开会话失败，当前标题='昨天 10:33'，目标='电销+直播攻坚组'」。
> **重启微信无效**（这是代码逻辑 bug，不是会话/登录/网络状态问题，已用只读探针确认 Windows 微信健康、目标群在列表可打开）。

---

## 改动一：新增转义辅助函数（粘贴到模块顶层任意位置，例如 import 之后）

```python
def _sendkeys_escape(text):
    """转义 uiautomation.SendKeys 的特殊字符，使其被原样键入。

    SendKeys 把 + ^ % ( ) { } ~ 当作修饰键/语法（'+'=SHIFT）。群名
    '电销+直播攻坚组' 里的 '+' 会被当成 SHIFT，导致搜索词残缺、搜不到目标群、
    退回点错会话（2026-10-22 实测：光标进输入框但不发，报打开会话失败）。
    用花括号包裹这些字符即可原样输入。仅作用于 SendKeys 调用；ListItem 的
    Name 精确匹配仍用未转义的真群名。
    """
    if not text:
        return text
    return ''.join('{' + ch + '}' if ch in '+^%(){}~' else ch for ch in text)
```

## 改动二：在 `send_message` 里，把搜索框的 SendKeys 调用改为转义后传入

- **改前**（你当前文件里大约这一行）：
  ```python
  search.SendKeys(who, waitTime=1.0)
  ```
- **改后**：
  ```python
  search.SendKeys(_sendkeys_escape(who), waitTime=1.0)
  ```

> 仅此一行改动。其余**全部保留**：
> - `ListItemControl(Name=who)` 仍用**未转义的真群名**做精确匹配（不变）；
> - 你 Windows 版自带的「打开会话失败，当前标题=… ，目标=…」标题校验逻辑**原样保留**（它是好 guard，不要删）；
> - 消息正文 `edit.SendKeys(text)` 暂不改（商家 payload 为地址/电话，不含这些特殊字符）。

## 改动三：重启 `server.py`（必须，否则加载的是旧代码）

改完 `driver.py` 后重启微信驱动服务，让新代码被重新加载。

---

## 验证（改完告诉我，我这边经中继只读复测）

1. 我复测 `/health` + `current_chat` 确认服务在线；
2. daemon（pid 34067，运行中）下一个周期会自动补跑 `daily-agent-new-merchants-to-wechat`，
   应把 8 家新商家（524831612 / 545844412 / 1187665008 / 1235324595 / 537020312 /
   545921542 / 1353394981 / 1307479521）发到「电销+直播攻坚组」；
3. 我读最新 `workflow.json` 确认 `wechat.messageCount=8 & ok=true` 即成功。

---

## ⚠️ 不要做的事

- **不要**把 Mac 仓库里的 `driver.py` 整文件覆盖到 Windows。
  Mac 仓库版虽已含上面的转义修复，但**缺少你 Windows 版那套「打开会话失败」标题校验 guard**
  （它抛的是另一种错误信息）。整文件覆盖会丢掉这个 guard，属于倒退。
  只按上面「改动一 + 改动二 + 改动三」做外科手术式修改即可。
