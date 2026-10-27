# 移动端 UI 自动化工程（美团外卖 / 淘宝闪购 / 微信）

基于 **uiautomator2** 的业务自动化骨架，目标设备为 **荣耀 9X / HarmonyOS 3.0（安卓兼容层）**。
通过电脑端 Python 脚本 + ADB 驱动真机。当前验证基线 uiautomator2 3.7.0 主要部署 `u2.jar` 与输入法辅助组件，运行时按需启动设备侧服务，**无需自行开发 App**；旧版资料所述 ATX/minicap/minitouch 组合不作为当前必备条件。

固定真机运行时为 Python 3.12.13：

```text
/Users/ddt/work/projects/ai_agent/.venvs/harmonyos3-phone-control/bin/python
```

涉及 `uiautomator2`、设备探针、环境自检和真机业务执行时必须使用该解释器，不使用系统默认 `/usr/bin/python3`。

通用设备控制、页面快照、定位、安全动作与故障处理由
`skills/skills/app-controler/harmonyos3-phone-control` Skill 统一定义；本目录只保存美团外卖、淘宝闪购、微信的业务适配、流程编排与业务字段。

## 目录结构

```
zhensi_waimai/
├── README.md
├── requirements.txt
├── config.py                 # 设备、包名、稳健交互参数（唯一配置入口）
├── driver.py                 # u2 连接 / healthcheck / 亮屏解锁
├── human.py                  # 稳健交互：界面等待 + 安全定位容错 + 退避
├── mobile_runtime/           # 动作合同、授权门与确定性收据
├── platforms/                # 美团、淘宝闪购、微信的业务适配包
├── anti_popup.py             # 业务弹窗与经授权的系统权限处理
├── locator.py                # 混合定位：text -> resourceId -> XPath -> 坐标
├── vision.py                 # 截图 + OCR + 模板匹配兜底
├── extractors.py             # 从 OCR 文本块提取结构化字段
├── meituan_client.py         # 旧调用兼容入口
├── taobao_flash_client.py    # 旧调用兼容入口
├── wechat_client.py          # 旧调用兼容入口
├── main.py                   # 编排入口（三应用可选）
└── tests/
    ├── test_env.py           # 环境自检
    ├── test_locator.py       # 定位器单测
    └── unit/                 # 动作合同、收据和平台边界测试
```

## 快速开始

```bash
# 1. 手机：开发者选项 -> 开启 USB调试 + USB调试(安全设置)
adb devices   # 确认 device 已授权

# 2. 安装依赖
pip install -r requirements.txt

# 3. 首次初始化（uiautomator2 3.7.0 不支持 --mirror）
/Users/ddt/work/projects/ai_agent/.venvs/harmonyos3-phone-control/bin/python -m uiautomator2 init

# 4. 环境自检
/Users/ddt/work/projects/ai_agent/.venvs/harmonyos3-phone-control/bin/python -m tests.test_env

# 5. 运行（在 config.py 里选 PLATFORM）
/Users/ddt/work/projects/ai_agent/.venvs/harmonyos3-phone-control/bin/python main.py
```

## 合规边界（务必阅读）

- 仅限 **有权操作的账号与设备**，控制频率并保留审计证据；先在测试对象验证
- 禁止：批量爬取、竞品监控、营销群发、自动抢红包、抓取聊天记录
- 尊重平台规则与用户授权，控制调用频率并保留审计记录；OCR 宜在电脑/云端运行（Kirin 810 本地运行较慢）。
- 本工程为 **技术验证骨架**：`SELECTORS` 指纹池、`_ensure_address` 等需在 weditor 实测后填充，部分方法预留 `NotImplementedError` 防止未校准就跑
- 发送消息、下单、支付、发布、删除、确认收货等属于 `EXTERNAL_EFFECT`，默认 fail-closed，最终动作前必须获得明确授权

详见同批交付的 `技术方案文档.md`。
