# 微信自动发送服务 · 使用手册（调用方版）

> 这份文档给**需要通过 Windows 微信发消息/发文件的人**看。
> 你只需说清「发给谁、发什么」，微信窗口的搜索、点击、上传、发送全部由服务端完成。
>
> 环境：Python 3（Mac / Linux / Windows 均可），**无需安装任何依赖**，只需一个 `client.py` 文件。

---

## 目录

1. [它能做什么](#1-它能做什么)
2. [三分钟上手](#2-三分钟上手)
3. [核心概念（务必先读）](#3-核心概念务必先读)
4. [完整 API 参考](#4-完整-api-参考)
5. [常见场景示例](#5-常见场景示例)
6. [文件路径与上传目录 inbox](#6-文件路径与上传目录-inbox)
7. [怎么知道结果](#7-怎么知道结果)
8. [排错表](#8-排错表)
9. [限制与安全](#9-限制与安全)
10. [FAQ](#10-faq)

---

## 1. 它能做什么

| 能力 | 支持 | 说明 |
|---|---|---|
| 发文字 | ✅ | 发给群或联系人 |
| 发图片 | ✅ | png/jpg/gif/bmp/webp，微信内可直接预览 |
| 发文件 | ✅ | Excel / Word / PDF / 压缩包… 显示为文件卡片 |
| 发给群 | ✅ | 群名前缀匹配，带图标/表情也能命中 |
| 批量派活 | ✅ | 一份清单，多个群发不同内容 |
| 查询 | ✅ | 会话列表、当前会话、最近消息、服务状态 |
| 读历史消息 | ⚠️ | 只能读**当前打开的那个会话** |
| 主动收消息 | ❌ | 不是机器人，不提供消息推送 |
| 撤回 | ❌ | 发出去撤不回 |

---

## 2. 三分钟上手

### 第 1 步：拿到 `client.py`

从服务端项目目录 `wechat-windows-driver/` 拷贝 `client.py` 到你自己的机器。
它是纯标准库写的，不需要 pip install 任何东西。

### 第 2 步：填连接信息

| 项目 | 值 |
|---|---|
| 服务地址 | `http://192.168.110.185:8731` |
| 认证方式 | HTTP 头：`Authorization: Bearer <TOKEN>` |
| TOKEN | 向服务端持有人索取 |
| 协议 | HTTP + JSON（UTF-8）；指令 POST 到 `/`，探活 GET `/health`（探活无需认证） |
| 网络 | 需与服务端在**同一局域网**；跨网请先协商穿透方案，**不要裸暴露公网** |

推荐用环境变量（避免把 token 写进代码）：

```bash
export WIN_IP="192.168.110.185"
export WECHAT_AGENT_TOKEN="<向服务端索取>"
```

Windows PowerShell 写法：

```powershell
$env:WIN_IP="192.168.110.185"
$env:WECHAT_AGENT_TOKEN="<向服务端索取>"
```

### 第 3 步：发第一条

```python
from client import WeChat

wx = WeChat()                       # 读环境变量
print(wx.health())                  # 探活
print(wx.send("文件传输助手", "你好，来自另一台机器"))
```

看到 `{'ok': True, 'data': {'sent': True, ...}}` 就成了。

也可以不设环境变量，显式传：

```python
wx = WeChat("192.168.110.185", "<TOKEN>")
```

---

## 3. 核心概念（务必先读）

### 3.1 `who` —— 用前缀匹配

微信里的群名常带图标、表情、"已置顶"、"N条新消息"等后缀。这里一律**前缀匹配**：

```python
wx.send("臻肆测试群", "hi")     # 可命中 "臻肆测试群 (3)"、"臻肆Test群已置顶32条新消息"
```

不确定真实群名？先查：

```python
wx.sessions()      # 列出所有会话，看真实名字
wx.current()       # 当前服务端打开的是哪个会话
```

### 3.2 `path` —— 是谁的路径？

这是跨机器最容易搞混的地方。**两个概念要分清：**

- **服务器路径**：服务端那台 Windows 上的路径，如 `C:\reports\日报.xlsx`
- **你本地路径**：你自己机器上的路径，如 `/Users/me/Desktop/日报.xlsx`

`send_file` / `send_image` / `send_auto` / 批量任务 → **要服务器路径**
`send_local_file` / `upload` → **给你本地路径**（内部自动上传）

不确定就用 `send_local_file`，它帮你搞定一切。详见[第 6 节](#6-文件路径三种玩法)。

### 3.3 串行与耗时

服务端一次只处理一件事，**并发调用会排队**（不丢，但会变慢）。

| 操作 | 大致耗时 |
|---|---|
| 发文字 | 3 ~ 6 秒 |
| 发文件 / 图片 | 8 ~ 20 秒 |

客户端默认超时 180 秒。传大文件可调大：`WeChat(timeout=600)`。

### 3.4 服务端必须就绪

服务端 Windows 需**已登录 + 微信已启动且已登录**。查状态：

```python
wx.health()
# {'wechat_running': True,  进程在不在
#  'logged_in': True,       是否已登录（主窗口在不在）
#  'ready': True}           两个都为真才可干活
```

微信刚重启还没扫码登录时，`wechat_running=True` 但 `logged_in=False`，这时要等：

```python
wx.wait_ready(timeout=300)     # 最长等 5 分钟，期间每 3 秒查一次
```

---

## 4. 完整 API 参考

所有方法返回 dict，形如 `{'ok': True, 'data': {...}}` 或 `{'ok': False, 'error': '...'}`。

### 查询类

| 方法 | 参数 | 返回 / 说明 |
|---|---|---|
| `wx.health()` | — | `{'ok':True,'wechat_running':bool,'logged_in':bool,'ready':bool}`，**无需鉴权** |
| `wx.wait_ready(timeout=300, poll=3)` | — | 轮询直到微信就绪；超时返回 `{'ok':False,'error':'等待微信就绪超时'}` |
| `wx.current()` | — | `{'data':{'title':'臻肆测试群 (3)'}}` 当前打开哪个会话 |
| `wx.read()` | — | 当前会话最近消息（最多 50 条） |
| `wx.sessions()` | — | 左侧会话列表（含未读数） |
| `wx.last()` | — | 服务端最后一次任务的结果 |
| `wx.list_dir(path=None, pattern='*')` | 服务器目录、通配符 | `{'data':{'items':[{'name','path','size','mtime'}]}}`，省略 path 列上传目录 |

### 发送类

| 方法 | 参数 | 说明 |
|---|---|---|
| `wx.send(who, text)` | 目标、文字 | **只发文字** |
| `wx.send_file(who, path)` | 目标、**服务器路径** | 强制按文件发 |
| `wx.send_image(who, path)` | 目标、**服务器路径** | 强制按图片发 |
| `wx.send_auto(who, content)` | 目标、**服务器路径或文字** | 自动识别：图片→图片，其他文件→文件，否则→文字。返回里 `data.auto` 说明实际类型 |
| `wx.send_local_file(who, local_path)` | 目标、**你本地路径** | 自动上传 + 自动识别 + 发送（推荐） |
| `wx.upload(local_path)` | **你本地路径** | 只上传不发送，返回服务器路径 |

### 批量类

```python
wx.run(tasks, dry_run=False, stop_on_error=False, interval=1.0, out=None)
```

- `tasks`：清单，见下
- `dry_run=True`：只校验不发送（**强烈建议先跑一次**）
- `stop_on_error=True`：遇错即停
- `interval`：两条之间间隔秒数
- `out="result.json"`：结果写入文件

返回：

```python
{'ok': True, 'data': {
   'total': 3, 'ok': 2, 'failed': 1, 'dry_run': False,
   'results': [
     {'index':1,'who':'群A','type':'text','status':'ok','result':{...}},
     {'index':2,'who':'群B','type':'file','status':'ok','result':{...}},
     {'index':3,'who':'群C','type':'file','status':'error','error':'文件不存在: ...'}
   ]}}
```

---

## 5. 常见场景示例

### 5.1 发一段文字

```python
wx.send("臻肆测试群", "今天的日报已生成，请查收")
```

### 5.2 用 `send_auto` 一个函数发所有类型（服务器路径）

```python
wx.send_auto("臻肆测试群", "C:\\reports\\日报.xlsx")   # .xlsx → 按文件发
wx.send_auto("臻肆测试群", "C:\\imgs\\海报.png")       # 图片后缀 → 按图片发
wx.send_auto("臻肆测试群", "今天的日报已发，请查收")     # 不是文件 → 当文字发
print(r["data"]["auto"])     # 'file' / 'image' / 'text'
```

Excel 走文件通道（微信里显示为文件卡片，对方点开能用 Excel/WPS 打开），**不是**在线表格预览。

### 5.3 发 Excel（你本地文件）

```python
r = wx.send_local_file("臻肆测试群", "/Users/me/Desktop/日报.xlsx")
print(r["data"]["auto"])              # 'file'
print(r["data"]["server_path"])       # 落到服务端哪了
```

Excel 在微信里显示为**文件卡片**（对方点开用 Excel/WPS 打开），不是在线表格。

### 5.4 发图片（你本地文件）

```python
wx.send_local_file("臻肆测试群", "/Users/me/Pictures/海报.png")
# auto = 'image'，微信内可直接预览
```

### 5.5 一次给多个群发不同内容

```python
tasks = [
    {"who": "臻肆测试群", "type": "text",  "text": "今日日报"},
    {"who": "客户群A",   "type": "file",  "path": "C:\\docs\\报价单.pdf"},
    {"who": "客户群B",   "type": "image", "path": "C:\\imgs\\海报.png"},
    {"who": "客户群C",   "type": "file",  "path": "C:\\docs\\资料包"},    # 目录→展开所有文件
    {"who": "客户群D",   "type": "file",  "path": "C:\\docs\\*.pdf"},     # 通配符
]

print(wx.run(tasks, dry_run=True))    # ① 先空跑，看有没有错
print(wx.run(tasks))                  # ② 确认无误再实跑
```

> 批量里的 `path` 必须是**服务器路径**。是你本地的文件就先 `upload()` 拿路径再填。

### 5.6 发之前先确认发给谁

```python
print(wx.current())      # {'data': {'title': '臻肆测试群 (3)'}}
```

### 5.7 上传一次，发给多个群

```python
path = wx.upload("/Users/me/Desktop/日报.xlsx")["data"]["path"]
for who in ["群A", "群B", "群C"]:
    wx.send_file(who, path)
```

---

## 6. 文件路径与上传目录 inbox

### A. 文件在你自己机器上 —— 最省事

```python
wx.send_local_file("群名", "/Users/me/Desktop/日报.xlsx")
```

内部流程：读本地文件 → base64 上传 → 服务端存到 `inbox/` → 自动识别图片/文件 → 发出。
**你完全不需要知道服务端磁盘长什么样**（关于 `inbox/` 详见本节 D 部分）。

返回里两端的路径都给你：

```python
{'sent': True, 'auto': 'file',
 'uploaded_from': '/Users/me/Desktop/日报.xlsx',                       # 你这边
 'server_path':   'C:\\...\\wechat-windows-driver\\inbox\\日报.xlsx'}  # 服务端那边
```

实测（中文名文件）：

```
上传  -> {'path': '...\\inbox\\对方做的报表 2026.xlsx', 'size': 1699}
图片  -> auto=image, 落到 inbox\对方的截图.png
表格  -> auto=file,  落到 inbox\对方做的报表 2026_1.xlsx   (重名自动加 _1)
```

### B. 文件本来就在服务端机器上

先看有什么，再发：

```python
wx.list_dir("C:\\reports")                 # 列目录
wx.list_dir("C:\\reports", "*.xlsx")       # 按通配符找
# {'data': {'count': 2, 'items': [{'name':'日报.xlsx','path':'...','size':12345}, ...]}}

wx.send_auto("群名", "C:\\reports\\日报.xlsx")
```

不传目录时 `wx.list_dir()` 列的就是上传目录 `inbox/`（详见 D 部分）。

### C. 批量任务里

`tasks` 里的 `path` 必须是服务器路径。你本地的文件先 `upload()` 换路径。

### D. `inbox/` 是什么？（上传文件落在哪）

用 `send_local_file()` 或 `upload()` 时，你上传的文件会被服务端**统一存放在一个固定目录**里，叫 `inbox`：

```
C:\work\projects\ai_agents\wechat-windows-driver\inbox\
```

| 问题 | 答案 |
|---|---|
| 什么时候会往里放东西？ | 你调用 `send_local_file()` 或 `upload()` 时 |
| 文件名怎么定？ | 保持你原来的文件名；**同名自动加序号**（`日报.xlsx` 已存在则存为 `日报_1.xlsx`），不会覆盖 |
| 我能看里面有什么吗？ | 能，`wx.list_dir()` 就是列这个目录（不传参数时） |
| 我能直接用里面的文件发吗？ | 能，`wx.send_file("群名", "C:\\...\\inbox\\日报.xlsx")`，或 `wx.list_dir()` 拿到 `path` 再发 |
| 文件保留多久？ | **7 天**，超期自动清理（守护进程启动清一次 + 每 24 小时一次） |
| 能当网盘用吗？ | 不能，它只是中转目录，别放重要东西 |

完整链路一眼看懂：

```
你机器上 /Users/me/日报.xlsx
   │  base64 上传（HTTP）
   ▼
服务端 C:\...\inbox\日报.xlsx      ← 7 天后自动清理
   │  自动识别：.png/.jpg → 图片；其他 → 文件
   ▼
微信里发出去（[图片] / [文件]）
```

---

## 7. 怎么知道结果

**不需要额外的回调或消息队列**，三种方式选一个就够：

| 方式 | 写法 | 场景 |
|---|---|---|
| 同步返回值 | `r = wx.send(...)` / `wx.run(...)` | 默认，绝大多数场景 |
| 查最后一次 | `wx.last()` | 事后复查，或不方便一直等 |
| 结果落盘 | `wx.run(tasks, out="result.json")` | 要留痕、丢共享目录 |

---

## 8. 排错表

| 现象 | 原因 | 处理 |
|---|---|---|
| `连接超时 / Connection refused` | 服务没起，或防火墙拦了 | 确认服务端已登录、微信在跑；让服务端放行防火墙 |
| `HTTP 401 unauthorized` | token 不对或没带 | 检查 `WECHAT_AGENT_TOKEN` |
| `微信进程在运行，但主窗口未出现…尚未完成登录` | 微信重启后**还没扫码登录** | 服务端完成扫码；或用 `wx.wait_ready(300)` 等 |
| `找不到微信主窗口 / 微信未启动` | 微信没启动 | 启动微信（守护进程会自动拉起服务） |
| `打开会话失败，当前标题=...` | 群名搜不到 | 用 `wx.sessions()` 核对真实群名；确认你是该群成员 |
| `文件不存在: ...` | 把本地路径当服务器路径用了 | 改用 `send_local_file`，或先 `upload()` |
| `未知任务类型` | type 写错 | 只支持 `text` / `file` / `image` |
| `bad request: invalid continuation byte` | 用 curl 发中文被按 GBK 编码 | 改用 `client.py`（固定 UTF-8） |
| 消息发到了别的会话 | 群名前缀撞车 | `who` 写完整些；发前 `wx.current()` 确认 |
| `等待微信就绪超时` | 一直没扫码登录 | 服务端登录后再调 |

---

## 9. 限制与安全

- **不可逆**：发出去的消息撤不回。批量前一定先 `dry_run=True`；首次对接新群建议先发「文件传输助手」试一次。
- **串行执行**：一次一个任务，并发会排队。
- **需要图形会话**：服务端 Windows 必须已登录、微信已启动且已登录。
- **只在可信局域网使用**：这个接口能在别人的微信上给任意群发消息，**不要暴露到公网**。
- **token 保管好**：不要提交到公开仓库。泄露就让服务端改 `.token` 并重启服务。
- **大文件**：base64 会膨胀约 33%，几十 MB 的文件请调大 `timeout`。

---

## 10. FAQ

**Q：能同时给 10 个群发吗？**
能，但串行。用 `wx.run(tasks)`，10 条文字大约 1 分钟。

**Q：群名有表情/图标怎么办？**
前缀匹配，写前半段就行：`"臻肆测试群"` 能命中 `"臻肆测试群 (3)"`。

**Q：我不知道服务端有什么文件？**
`wx.list_dir("C:\\某个目录")`，或 `wx.list_dir()` 看上传目录。

**Q：上传的文件会覆盖同名文件吗？**
不会，自动加序号（`日报_1.xlsx`）。

**Q：上传的文件会一直在服务端吗？**
不会。**超过 7 天自动清理**（守护进程启动时清一次，之后每 24 小时一次），日志记在 `logs/daemon.log`。
想立即清理或改保留天数，让服务端执行 `python cli.py cleanup --days 7`（加 `--dry-run` 可先看会删哪些）。

**Q：服务挂了怎么办？**
服务端有守护进程，每 5 秒检查一次，会自动拉起（实测 kill 后 5 秒内恢复）。

**Q：微信重启后要重新配置吗？**
不用。守护进程常驻，检测到微信在就拉起服务。只是重启后要**扫码登录**，登录后 `wx.wait_ready()` 就能继续用。

**Q：能发语音/视频/表情包吗？**
语音、视频走的是文件通道（可按文件发，但不能微信内嵌播放）。表情包不行。

**Q：能读别人发来的消息吗？**
只能读**当前打开的会话**的最近消息（`wx.read()`）。不是机器人，没有消息推送能力。

**Q：一次能发多大文件？**
微信本身限制约 100 MB（文件）/ 10 MB（图片）。传输上 base64 会膨胀 33%，超大文件建议直接放服务端本地再用 `send_file`。
