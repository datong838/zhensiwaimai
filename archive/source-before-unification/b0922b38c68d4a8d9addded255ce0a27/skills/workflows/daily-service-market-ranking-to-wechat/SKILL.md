---
name: daily-service-market-ranking-to-wechat
description: 每日采集9231淘宝闪购服务市场代运营首页的服务商等级、排名及全部本月考核指标原图，通过原主任和企业微信原生UI队列发运营群。
---

# 服务市场排名与本月考核指标

唯一生产入口 scripts/ranking_workflow.py --execute，由runtime/skills_manifest.json派班，默认每日10:00，首次上线当天执行一次。只用taobao-svc-post的9231、现有唯一业务页和原租约，保留并还原原URL/viewport/滚动位置。完整方案见项目docs/solutions/20261026-服务市场排名与考核指标值班方案.md。

采集.sycm-common-agency-grade-wrapper全区块，等级/排名/等级更新时间/本月全部指标同源。当前值、要求值、昨日值独立保存；额外指标不能裁掉，缺值不编造、不计算新完成率。截图必须直接作为image展示，不能发PNG文件卡。

只走原主任/control、WeComAdapter、原队列及System Events公开原生UI；完整运营群名由代码固定。一个业务日一个冻结事件，verified不重发，attempted/unknown只读对账；零发送预检失败沿原事件恢复，不重新采集改变载荷。未知草稿、登录、验证码、风险或页面结构歧义停止。新商家始终优先，不占用其排班。

本地runtime-policy只证明文件完整性，实际采集和外发分别验收；图片证据不足诚实unknown。修改先完善方案、自测、同步源与安装目录，不改原业务记录。
