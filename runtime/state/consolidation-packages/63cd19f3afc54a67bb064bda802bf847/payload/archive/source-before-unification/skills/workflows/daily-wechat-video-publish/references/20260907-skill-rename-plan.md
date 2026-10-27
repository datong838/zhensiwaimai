# Skill 改名方案

## 目的
技能将覆盖微信视频号、抖音、快手和小红书，原先只包含抖音平台含义的名称已不能表达完整范围。目录和 Skill 标识统一改为 `daily-wechat-video-publish`。

## 修改范围
- 目录：原抖音专用名称目录 → `skills/daily-wechat-video-publish`
- `SKILL.md` 的 `name` 与示例绝对路径
- `scripts/package.json` 的包名
- 引用文档里的技能目录示例
- `scripts/lib/__init__.py` 注释

## 不变范围
本次不新增四平台发布逻辑，不修改下载、扫描、去重、文案、发布或状态机行为，不迁移 `/Users/ddt/work/臻肆/视频/` 下的业务状态。

## 验证
改名后全仓搜索旧名称必须为零；新目录存在、旧目录不存在；Python 测试全部通过；Python 文件可编译；Node 脚本语法检查通过。
