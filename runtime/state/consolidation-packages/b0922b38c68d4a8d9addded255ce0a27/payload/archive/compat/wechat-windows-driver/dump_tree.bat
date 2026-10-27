@echo off
cd /d "%~dp0"

if not exist ".venv" (
    echo [!] 尚未安装依赖，请先运行 start_agent.bat 完成安装与启动配置。
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat
echo [+] 打印微信窗口 UI 树（请把下方整段输出复制贴回 Mac 侧用于校准控件）...
python driver.py
echo.
echo [+] 已打印完毕。将上述 [ctrl+type] 内容整段发给 Mac 侧即可。
pause
