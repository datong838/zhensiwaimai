// Re-reveal an original exact session ID. No click, input, or submission.
export async function revealSessionCard(page, sessionId) {
  if (!/^\d{19}$/.test(sessionId)) throw Error('customer-session-id-unavailable');
  const result = await page.evaluate(async id => {
    const selector = "[class*='sessionListItemContainer']";
    const cards = () => [...document.querySelectorAll(selector)];
    const match = () => {
      const matches = cards().filter(el => el.id === id);
      if (matches.length > 1) throw Error('customer-session-id-not-unique');
      return matches.length === 1;
    };
    if (match()) return {found: true, originalTop: null};
    const first = document.querySelector(selector);
    const sc = document.querySelector("[class*='sessionListContent']") || (first &&
      (first.closest("[class*='scroll'], [class*='list'], [class*='List'], [class*='content'], [class*='Content']") || first.parentElement));
    if (!sc) return {found: false, originalTop: null};
    if (!Number.isFinite(sc.clientHeight) || sc.clientHeight <= 0 || !Number.isFinite(sc.scrollTop))
      throw Error('customer-list-viewport-unavailable');
    const originalTop = sc.scrollTop, step = Math.max(1, Math.floor(sc.clientHeight * 0.8));
    let found = false, wrapped = originalTop === 0;
    const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
    const bottom = () => sc.scrollTop + sc.clientHeight >= sc.scrollHeight - 5;
    const signature = () => cards().map(el => el.id).join('|');
    try {
      for (let guard = 0; guard < 300; guard++) {
        if (match()) {found = true; return {found, originalTop};}
        if (bottom()) {
          const height = sc.scrollHeight, before = signature();
          await pause(500);
          if (match()) {found = true; return {found, originalTop};}
          if (bottom() && height === sc.scrollHeight && before === signature()) {
            if (wrapped) return {found: false, originalTop: null};
            sc.scrollTop = 0; await pause(300);
            if (sc.scrollTop !== 0) throw Error('customer-list-start-not-top');
            wrapped = true; continue;
          }
        } else {
          const before = sc.scrollTop;
          sc.scrollTop = Math.min(before + step, sc.scrollHeight);
          await pause(300);
          if (sc.scrollTop <= before && !bottom()) throw Error('customer-list-scroll-stalled');
        }
      }
      throw Error('customer-session-location-incomplete');
    } finally {
      if (!found) sc.scrollTop = originalTop;
    }
  }, sessionId);
  return {...result, restore: result.originalTop === null ? null : async () => {
    await page.evaluate(top => {
      const first = document.querySelector("[class*='sessionListItemContainer']");
      const sc = document.querySelector("[class*='sessionListContent']") || (first &&
        (first.closest("[class*='scroll'], [class*='list'], [class*='List'], [class*='content'], [class*='Content']") || first.parentElement));
      if (!sc) throw Error('customer-session-location-restore-unavailable');
      sc.scrollTop = top;
    }, result.originalTop);
  }};
}
