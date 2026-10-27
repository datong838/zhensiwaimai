import fs from "node:fs/promises";
import path from "node:path";
// 2026-10-06 跨树整改（大同授权）：旧根 zhensi_waimai → _back，且 skill 实际位于 skills/workflows/ 下
// （原 import 路径 ../skills/store-inspection/... 指向 _back/skills/store-inspection —— 该目录不存在，
//   import 早已断裂；一并修正到 skills/workflows/store-inspection/...）。
import { buildInspectionResult, validateInspectionResult } from "../skills/workflows/store-inspection/scripts/build_inspection_result.mjs";

const ROOT = "/Users/ddt/work/projects/ai_agent/zhensi_waimai_back";
const HANDOFF = path.join(ROOT, "skills/workflows/store-inspection/runtime/run-2026-09-09-handoff");
const RESULT_DIR = path.join(ROOT, "skills/workflows/store-inspection/runtime/results/2026-09-第2周");
const PREVIEW_DIR = path.join(HANDOFF, "result-previews");

const stores = [
  { platform: "淘宝闪购", roster: "9家湘菜（金谊广场店）", store: "9家湘菜（金谊广场店）", rating: "5.0分", sales: "月售2000+", delivery: "起送¥20、免配送费、约15分钟", hours: "商家页已取证", reviews: "评价646，近期差评7条", evidenceDir: "淘宝闪购-9家湘菜（金谊广场店）" },
  { platform: "淘宝闪购", roster: "陶姥姥砂锅·广式啫啫煲（金谊广场店）", store: "陶姥姥砂锅·广式啫啫煲（金谊广场店）", rating: "4.4分", sales: "月售300+", delivery: "起送¥30、免配送费、约15分钟", hours: "周一至周日10:30-14:30、16:00-21:00", reviews: "评价179，近期差评12条", evidenceDir: "淘宝闪购-陶姥姥砂锅·广式啫啫煲（金谊广场店）" },
  { platform: "美团外卖", roster: "9家湘菜（金谊广场店）", store: "9家湘菜（金谊广场店）", rating: "4.5分", sales: "月售600+", delivery: "起送¥30、免配送费、约22米/21分钟", hours: "配送时间10:00-21:00", reviews: "外卖评价164，好评147、差评14、商家回复111", evidenceDir: "美团外卖-9家湘菜（金谊广场店）" },
];

function checksFor(store) {
  const checks = Array.from({ length: 44 }, (_, index) => ({ row: index + 2, finding: "", recommendation: "", evidence: "" }));
  const set = (row, finding, recommendation, evidence) => { checks[row - 2] = { row, finding, recommendation, evidence }; };
  set(2, `页面展示门店名“${store.store}”。`, "保持搜索页名称、商家页名称与品牌物料一致。", "01-search-result.png、06-merchant.png");
  set(3, "商品页与商家页可见菜品图、门店图。", "持续使用清晰、统一风格的菜品和门店实拍图。", "02-store-home.png、06-merchant.png");
  set(4, "商品页可见招牌、热销、套餐等卖点信息。", "将招牌卖点固定在首屏和核心分类，保持表述一致。", "02-store-home.png、03-products-scroll.png");
  set(5, `当前评分${store.rating}。`, "持续按最近评价反馈复盘出品、包装和配送体验。", "01-search-result.png、04-reviews.png");
  set(6, `当前搜索页展示${store.rating}。`, "每周复核评分变化，并优先处理新增差评主题。", "01-search-result.png");
  set(7, `${store.reviews}。`, "对可见差评按餐品、包装和服务分类复盘，形成责任闭环。", "04-reviews.png、05-negative-reviews.png");
  set(11, `当前搜索页展示${store.sales}。`, "按周跟踪核心商品销量，保持高销量商品稳定供应。", "01-search-result.png");
  set(12, "商品页展示多款带月售的商品。", "按商品月售分层复盘，明确主推与待优化商品。", "02-store-home.png、03-products-scroll.png");
  set(13, "当前页面可见满减、券或套餐等活动信息。", "在不改变合规边界的前提下，按商圈价格带定期复核活动组合。", "01-search-result.png、02-store-home.png");
  set(14, "商品页可见套餐、招牌和热销商品。", "将引流款与招牌菜分层呈现，并持续核对出品竞争力。", "02-store-home.png、03-products-scroll.png");
  set(15, "商品页可见招牌及热销标识。", "保持主推商品命名、图片和价格信息一致，避免首屏卖点漂移。", "02-store-home.png、03-products-scroll.png");
  set(16, "商品页可见不同价格带的套餐与单品。", "每月按销量复核各价格带热销商品，补齐弱档位。", "02-store-home.png、03-products-scroll.png");
  set(17, "商品页可见招牌、热销和分类结构。", "将高销量商品固定在前列，定期根据月售调整分类排序。", "02-store-home.png、03-products-scroll.png");
  set(19, `${store.hours}。`, "每日开档前复核页面营业与配送时段，避免展示与接单不一致。", "06-merchant.png");
  set(20, "页面展示预订或后续配送提示。", "保持预订提示、营业时间和实际接单能力一致。", "01-search-result.png、02-store-home.png");
  set(23, `${store.delivery}。`, "按配送距离与时效监测用户反馈，异常订单及时复盘。", "01-search-result.png、06-merchant.png");
  set(26, "当前页面可见店内券或满减入口。", "定期检查活动文案、门槛和价格展示是否一致。", "01-search-result.png、02-store-home.png");
  set(31, "商品页可见多个商品分类。", "保持分类数量适中、名称清晰，并按销量定期排序。", "02-store-home.png、03-products-scroll.png");
  set(32, "当前商品页可见分类及商品名称。", "为核心分类补齐简洁描述，突出食材、口味和招牌信息。", "02-store-home.png、03-products-scroll.png");
  set(33, `当前配送信息为${store.delivery}。`, "定期复核配送范围和时效的用户体验反馈。", "01-search-result.png、06-merchant.png");
  set(36, "可见商品名称包含招牌、热销或套餐信息。", "商品名称突出菜品、分量和核心卖点，避免夸大表述。", "02-store-home.png、03-products-scroll.png");
  set(37, "可见商品卡展示菜品名称、价格和部分卖点。", "优先完善高销量商品描述，明确食材、口味和份量。", "02-store-home.png、03-products-scroll.png");
  set(38, "商品页可见多张菜品配图。", "统一配图风格并定期替换失真、过期或与实物不符的图片。", "02-store-home.png、03-products-scroll.png");
  set(39, "商家页可见门店环境或门店图。", "保持环境图、菜品图与实际门店一致。", "06-merchant.png");
  set(41, "商家页可见门店与品牌相关展示。", "以真实门店、招牌菜和食材信息持续完善品牌故事。", "06-merchant.png");
  set(45, "商品与商家页可见招牌菜、图片和卖点展示。", "围绕已验证的招牌菜和真实消费反馈更新宣传素材。", "02-store-home.png、06-merchant.png");
  return checks;
}

for (const store of stores) {
  const evidenceDir = path.join(HANDOFF, store.evidenceDir);
  const inputPath = path.join(evidenceDir, "inspection.json");
  const outputPath = path.join(RESULT_DIR, `${store.platform}-上海市-${store.store}-巡店结果.xlsx`);
  await fs.writeFile(inputPath, JSON.stringify({
    platform: store.platform,
    city: "上海市",
    rosterStoreName: store.roster,
    storeName: store.store,
    inspectionDate: "2026-09-09",
    templateChecks: checksFor(store),
  }, null, 2));
  await buildInspectionResult({ inputPath, outputPath, previewDir: PREVIEW_DIR });
  await validateInspectionResult(outputPath);
  console.log(JSON.stringify({ inputPath, outputPath, checks: 44 }));
}
