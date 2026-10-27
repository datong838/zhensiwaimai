@echo off
cd /d "%~dp0"

if not exist ".venv" (
    echo [+] 首次运行：创建虚拟环境并安装依赖...
    python -m venv .venv
    call .venv\Scripts\activate.bat
    pip install -r requirements.txt
) else (
    call .venv\Scripts\activate.bat
)

if "%WECHAT_AGENT_TOKEN%"=="" (
    echo [!] 未设置 WECHAT_AGENT_TOKEN，请先执行：
    echo     set WECHAT_AGENT_TOKEN=换成一段强随机字符串
    exit /b 1
)

echo [+] 启动 wechat-windows-agent（监听 0.0.0.0:8731）...
python server.py
