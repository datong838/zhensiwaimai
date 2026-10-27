# 请求与回执

唯一请求结构：schemaVersion=1，operation=send（可省略），groupName，items，context。未知字段拒绝。items 顺序即发送顺序，每项 itemId 唯一；text 使用 text，image/file/video 使用绝对 path。

```json
{
  "schemaVersion": 1,
  "groupName": "臻肆测试群",
  "items": [{"itemId": "text-1", "type": "text", "text": "用户确认的完整正文"}],
  "context": {
    "workflowId": "wechat-messaging-acceptance",
    "eventId": "用户已授权的独立测试事件",
    "accountAlias": "main-wechat",
    "channel": "desktop",
    "deadlineAt": 1790000000
  }
}
```

示例截止时间只是结构示例，必须由本次实际预算产生，不照抄。默认最多20项、单文件100MiB、文字20000字符；这是当前执行器本地限制，不是微信平台上限声明。

validate 返回 requestDigest。授权单独 JSON 包含 schemaVersion=1、requestDigest、accountAlias、groupName、channel、expiresAt（Unix秒）、authorizationRef（实际用户授权的可查引用）。填写引用不产生授权，只能记录已获得的授权。运行策略还需精确列入本请求摘要，拒绝任意字符串绕过。

账号别名必须绑定当前人工确认的登录账号。当前桌面实现不能自动读取可信账号唯一标识，因此验收时须核对会话；不能声称已经完成跨账号自动识别。

## 防重

事件键由账号别名、完整群名、workflowId、eventId构成；整个有序载荷绑定到该事件。itemId形成逐项键。路径、runId和通道不参与身份，因此不能借换端/换路径重发；内容、名称、顺序变化发生冲突。

账本在技能 `.runtime/events/`，结果在 `.runtime/receipts/`，每项保存冻结载荷、底层 attempted、截图和回读。私有文件0600、目录0700；不输出正文到公共日志。账本保留失败记录，不自动清理。不要复制旧业务生产事件到新账本：正式迁移前必须导入旧发送事实，当前未实现自动历史导入。

## 核验证据

图片质量原则：源图不设最低宽高、DPI或总像素硬门槛，以正常查看时关键内容清晰可辨为准，不强制原图/高清，不自动放大或重制。当前没有自动清晰度评分器。聊天截图中的80×60候选区域限制用于定位回读对象，不代表源图质量要求；无法定位时报告证据不足，不能据此宣称图片模糊或未发送。

- native-text-exact：双帧位置稳定、空输入框、唯一复制菜单、复制全文SHA-256一致。OCR仅定位候选，不替代原文。
- image-content-match：两帧新出站区域内容与源图视觉指纹一致、位置稳定，底层也已核对群和空输入。**不是原图字节一致证明**；多候选、纯色低信息图或布局无法匹配时unknown。
- file-name-size-ui：完整名称、显示大小、传输状态、两帧位置稳定及新消息区域变化。截断文件名不会按前缀放行。**不是附件字节回读证明**。

本地UI核验不等于群成员阅读或远端下载成功。接收和原生视频为unsupported；手机仅已校准主实例三类发送，批次中包含不支持项时在任何发送前拒绝。

返回状态：verified、already_verified、partial、blocked、unknown。每项包含载荷hash、状态、sendAttempts、证据等级、证据、底层收据。review为真实执行阶段计时，不生成未运行阶段的虚假耗时。

## 历史内容只读验证

verify-existing 复用同一请求结构，仅支持已明确指定的file对象；只检查目标群当前可见窗口中的完整名、大小和双帧位置，不滚动、不下载、不写发送账本。返回 historical_visible_verified，永远不把历史可见性改成新发送成功。
