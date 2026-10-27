/**
 * 店铺名匹配判据（唯一权威源）
 *
 * 背景：源店名（旧 ID `wmPoiId` 或不同命名口径）与目标候选店名可能来自不同命名体系，店名口径不同：
 *   源   「湘霸王·创意湘菜（平凉路店）」
 *   候选「湘霸王·老坛剁椒鱼头(平凉路店)」
 * ⇒ 不能靠 ID 映射，只能「品牌段 + 括号分店名」定位。
 *
 * 铁律：宁可不切，不可错切。
 *   错切会把 A 店的经营数据发到 B 店的商家群里，是生产事故；
 *   搜不到只是少发一家，台账备注即可。
 */

/** 归一化：全角括号→半角、统一间隔符、去空白 */
export function norm(x) {
  return String(x || '')
    .replace(/（/g, '(').replace(/）/g, ')')
    .replace(/[·•・･]/g, '·')
    .replace(/\s+/g, '')
    .trim();
}

/** 去掉所有括号段（含内容） */
export function nobracket(x) {
  return norm(x).replace(/[（(][^）)]*[）)]/g, '');
}

/** 取最后一个括号内的分店名 */
export function branchOf(x) {
  const m = norm(x).match(/[（(][^）)]*[）)]/g);
  if (!m) return '';
  return m[m.length - 1].replace(/^[（(]|[）)]$/g, '');
}

/** 取品牌段：去括号后按分隔符切第一段 */
export function brandOf(x) {
  return nobracket(x).split(/[·\-—_|/]/)[0];
}

/**
 * 分店名键：从括号里挑出「以『店』结尾」的片段
 *
 * 为什么不能直接用括号内容：有的命名会把品类塞进括号
 *   「Espacio（咖啡·西班牙餐厅·通福六区店）」  vs 品牌商「Espacio(西班牙餐厅·沙拉·咖啡·通福六区店)」
 * 直接比字符串必然不等，但两者其实是同一家（通福六区店）。
 * 只认「XX店」片段，品类词自动丢弃。
 *
 * 括号里没有任何「XX店」⇒ 不是分店名（如「旺鲜全羊馆（全羊·泡馍·烧烤）」）⇒ 返回 ''
 */
export function branchKey(x) {
  const br = branchOf(x);
  if (!br) return '';
  const parts = br.split('·').map((s) => s.trim()).filter(Boolean);
  const storeLike = parts.filter((p) => /店$/.test(p));
  return storeLike.length ? storeLike[storeLike.length - 1] : '';
}

/** 搜索关键词：前缀 = 去括号全名，超长截断 */
export function prefixOf(x, max = 10) {
  const b = nobracket(x);
  return b.length > max ? b.slice(0, max) : b;
}

/**
 * 生成**降级搜索关键词序列**（按精确度降序，已去重）
 *
 * 为什么不能只用一个前缀：源与候选的「品类段」经常不同
 *   源   「湘霸王·创意湘菜（平凉路店）」
 *   候选「湘霸王·老坛剁椒鱼头(平凉路店)」
 * ⇒ 搜「湘霸王·创意湘菜」命中 0 条；必须退到品牌词「湘霸王」才能拿到候选族，
 *   再用括号分店名（平凉路店）定位唯一目标。
 *
 * 2026-10-20 30 家分层实测：单级前缀（去括号全名）层 2 命中 0/10；
 * 改用品牌词后见下方实测记录。
 */
export function keywordsFor(name) {
  const n = norm(name);
  const body = nobracket(n);          // 去括号主体
  const brand = body.split('·')[0];   // 品牌词（· 前第一段）
  const out = [];
  const push = (k) => {
    const v = String(k || '').trim();
    if (v.length >= 2 && !out.includes(v)) out.push(v);
  };
  push(body);                          // ① 去括号全名
  push(brand);                         // ② 品牌词
  if (brand.length > 6) push(brand.slice(0, 6)); // ③ 品牌词前 6 字
  if (brand.length > 4) push(brand.slice(0, 4)); // ④ 品牌词前 4 字（兜底）
  return out;
}

/**
 * 在候选列表中定位唯一目标。
 * @param {string} target 源店名（可为空：此时只按候选唯一性判断）
 * @param {string[]} cands 候选店名
 * @returns {{ok:boolean, pick?:string, why:string, weak?:boolean, n?:number, sample?:string[]}}
 *   why: exact | branch | brand+branch | single | single-brand | no-confident-match | ambiguous | not-found
 */
export function judge(target, cands) {
  const list = (cands || []).filter(Boolean);
  if (!target) {
    if (list.length === 1) return { ok: true, pick: list[0], why: 'single' };
    return list.length ? { ok: false, why: 'ambiguous', n: list.length, sample: list.slice(0, 3) }
                       : { ok: false, why: 'not-found', n: 0 };
  }

  const T = norm(target), TB = brandOf(target), TR = branchKey(target);

  // 1) 全名归一化相等
  const i = list.findIndex((c) => norm(c) === T);
  if (i >= 0) return { ok: true, pick: list[i], why: 'exact' };

  // 2) 分店名（branchKey）唯一匹配 —— 这是跨「两套命名口径」的主力判据
  if (TR) {
    const bs = list.filter((c) => branchKey(c) === TR);
    if (bs.length === 1) return { ok: true, pick: bs[0], why: 'branch' };
    if (bs.length > 1) {
      const both = bs.filter((c) => brandOf(c) === TB);
      if (both.length === 1) return { ok: true, pick: both[0], why: 'brand+branch' };
      return { ok: false, why: 'ambiguous', n: bs.length, sample: bs.slice(0, 3) };
    }
  }

  // 3) 唯一候选：只在「没有分店名冲突风险」时才接受
  if (list.length === 1) {
    const c = list[0];
    const cb = brandOf(c) || norm(c);
    const cr = branchKey(c);
    const brandHit = !!(cb && TB && (cb.startsWith(TB) || TB.startsWith(cb)));
    if (!TR) {
      // 目标本身没有分店名（单店品牌）⇒ 唯一候选可接受
      if (brandHit) return { ok: true, pick: c, why: 'single-brand', weak: true };
    } else if (cr) {
      // 目标有分店名、候选也有，但 2) 已排除相等 ⇒ 明确是两家不同的店
      return { ok: false, why: 'branch-conflict', n: 1, sample: list };
    } else if (brandHit) {
      // 目标有分店名、候选无分店名（品牌商侧简写，如 "VibeSip"）
      // ⇒ 无法确认是不是同一家，交人工复核，不自动切
      return { ok: false, why: 'branch-unknown', n: 1, sample: list };
    }
  }

  return { ok: false, why: list.length ? 'no-confident-match' : 'not-found', n: list.length, sample: list.slice(0, 3) };
}

/**
 * 切换后的店名校验强度：exact 命中要求严格相等，其余允许模糊。
 * 模糊 = 品牌段相同 或 分店名相同
 */
export function nameAcceptable(target, actual, why) {
  if (!target) return true;
  if (why === 'exact') return norm(target) === norm(actual);
  const tr = branchKey(target), ar = branchKey(actual);
  // 目标有分店名 ⇒ 候选必须同分店名（否则就是错切到同名品牌的另一家店）
  if (tr) return tr === ar;
  // 目标无分店名 ⇒ 候选也不能有，否则无法确认是哪一家
  return !ar && (nobracket(target) === nobracket(actual) || brandOf(target) === brandOf(actual));
}
