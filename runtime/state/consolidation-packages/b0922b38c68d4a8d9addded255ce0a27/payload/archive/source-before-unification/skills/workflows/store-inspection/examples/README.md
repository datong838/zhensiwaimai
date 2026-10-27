# 巡店模板与合成示例

原始模板位于../runtime/门店自检表(框架+模板).xlsx，原字节保留，SHA以references/inspection-template-contract.md为准。工作表Sheet1，A1:C45，20个项目、44条检查点。

inspection.synthetic.json仅演示执行器输入结构，不是实际巡店结论。44行全部列出，只有前两行填合成发现与方案，其余同时留空，表达未取得证据时不猜测。真实运行仍须按原Skill采集、映射、生成和校验；原始模板中的历史营销文字不是执行授权。

结果生成器为scripts/build_inspection_result.mjs，模板与结果校验分别见scripts/inspect_inspection_template.mjs及scripts/test_inspection_result.mjs。真实门店截图和报告不公开上传。
