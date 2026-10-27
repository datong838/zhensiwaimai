# WeChat Windows Driver（UI 自动化 · 直连 IP）

Mac 侧（WorkBuddy）远程指挥 Windows 10 上的微信 3.9.x 发消息的兜底方案。
当 Mac 端微信 4.0.3 的 Accessibility 树不够用时启用。

**路线 A：UI 自动化（uiautomation）** —— 零注入、安全合规，依赖微信 3.9.x 暴露良好的 UI 树。

## 目录结构
- `server.py`   监听服务（HTTP + Bearer Token），接收指令并调用 driver
- `driver.py`   UI 自动化驱动（搜索→选联系人→输入→回车发送）+ `dump_tree` 诊断
- `requirements.txt`  依赖

## 环境要求（Windows 本机）
- Windows 10/11，Python 3.8+
- 微信 3.9.x **已登录**（最小化到托盘也行，但首次需在前台）
- 同一可信局域网（Mac 能直连本机 IP）

## 安装
```powershell
cd wechat-windows-driver
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## 配置（环境变量，务必改 TOKEN）
```powershell
$env:WECHAT_AGENT_TOKEN = "请换成一段强随机字符串"
$env:WECHAT_AGENT_HOST  = "0.0.0.0"      # 监听所有网卡（同局域网可达）
$env:WECHAT_AGENT_PORT  = "8731"
```

## 运行
```powershell
python server.py
# 看到 [wechat-windows-agent] listening on 0.0.0.0:8731 即成功
```

## 校准控件（首次必做）
1. 确保微信在前台、已登录。
2. 在 Windows 本机跑一次诊断，把输出贴回给 Mac 侧：
   ```powershell
   python driver.py
   ```
   或经服务调用：`POST /`  body `{"action":"dump_tree","params":{}}`
3. Mac 侧据此校准 `driver.py` 里的控件 Name（搜索框/输入框/发送）。

## Mac 侧调用示例（等你给 Windows IP 后）
```bash
# 健康检查
curl -s http://<WIN_IP>:8731/health

# 发消息
curl -s -X POST http://<WIN_IP>:8731/ \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"action":"send_message","params":{"who":"文件传输助手","text":"hello from mac"}}'
```

## 指令表
| action | params | 说明 |
|---|---|---|
| health | - | 探活 |
| dump_tree | {depth?} | 打印微信窗口 UI 树（校准用） |
| send_message | {who, text} | 给 who 发 text |
| list_chats | - | 列出左侧会话名 |

## 安全提醒
- **务必修改 WECHAT_AGENT_TOKEN**，不要用默认值。
- 仅限同一可信局域网，不要在公网暴露 8731 端口。
- 该服务能以外发消息——仅在你本机/可信网络使用。
- 若需跨 NAT/防火墙，改用反向 WebSocket 中转（本骨架未含，需要时再加）。

---

## Mac 侧客户端（mac_client.py）

从 Mac 上直接指挥 Windows 微信，**纯标准库、无需 pip install**，用 Mac 自带或 WorkBuddy 的 python3 即可运行：

```bash
export WIN_IP="192.168.x.x"            # Windows 局域网 IP
export WECHAT_AGENT_TOKEN="与 Windows 端一致的强随机串"
export WECHAT_AGENT_PORT="8731"        # 可选，默认 8731

python mac_client.py health                              # 探活
python mac_client.py dump                                # 打印微信 UI 树（校准用）
python mac_client.py chats                               # 列出左侧会话名
python mac_client.py send "文件传输助手" "hello from mac" # 发消息（who 含空格用引号）
```

> 底层仍是 `POST /` + Bearer Token；mac_client.py 只是把 curl 封装成一条命令。

## Windows 一键脚本

- `start_agent.bat`：首次自动建 venv + 装依赖，随后启动服务（需先 `set WECHAT_AGENT_TOKEN=...`）。
- `dump_tree.bat`：直接打印微信窗口 UI 树，复制整段贴回 Mac 侧校准。

## 校准流程（首次必做）

1. **Windows**：双击 `dump_tree.bat`（或 `python driver.py`），把 UI 树整段贴给 Mac 侧。
2. **Mac 侧**：据此确认/修正 `driver.py` 里搜索框(`Name="搜索"`)、输入框(`Name="输入"`/第 2 个 `Edit`)、发送(回车) 的定位器。
3. 之后即可用 `mac_client.py send` 自动发消息。

## 端到端操作步骤

**Windows 侧（你在本机操作）**
```powershell
cd wechat-windows-driver
set WECHAT_AGENT_TOKEN=换成一段强随机字符串
start_agent.bat          # 启动监听（保持窗口开着）
# 另开一个终端：
dump_tree.bat           # 取 UI 树，整段复制
```

**Mac 侧（把 Windows IP 和 TOKEN 给我 / 自己设环境变量）**
```bash
export WIN_IP="<WIN_IP>"; export WECHAT_AGENT_TOKEN="<TOKEN>"
python mac_client.py health          # 应返回 ok:true
python mac_client.py dump            # 与我之前的校准对照
python mac_client.py send "文件传输助手" "第一条来自 Mac 的自动消息"
```
