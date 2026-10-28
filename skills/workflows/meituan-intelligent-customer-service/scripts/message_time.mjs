// Shanghai calendar values only. Never interpret a clock inside customer prose.
function calendar(year, month, day, hour, minute, second) {
  if (![year, month, day, hour, minute, second].every(Number.isInteger)
      || hour < 0 || hour > 23 || minute < 0 || minute > 59 || second < 0 || second > 59) return null;
  const ms = Date.UTC(year, month - 1, day, hour, minute, second), d = new Date(ms);
  return d.getUTCFullYear() === year && d.getUTCMonth() === month - 1 && d.getUTCDate() === day ? ms : null;
}
export function nowCalendarMs(now) {
  const date = /^(\d{4})-(\d{2})-(\d{2})$/.exec(now?.date || '');
  if (!date) return null;
  const second = now.clock ? /^(\d{2}):(\d{2}):(\d{2})$/.exec(now.clock) : null;
  if (now.clock && (!second || Number(second[1]) !== now.h || Number(second[2]) !== now.m)) return null;
  return calendar(Number(date[1]), Number(date[2]), Number(date[3]), now.h, now.m, second ? Number(second[3]) : 0);
}
export function parseMessageTime(label, now) {
  const at = nowCalendarMs(now);
  if (at === null) return null;
  const match = /^(?:(\d{4})[-/])?(\d{2})[-/](\d{2})\s+(\d{2}):(\d{2})(?::(\d{2}))?$/.exec(String(label || '').trim());
  if (!match) return null;
  let year = match[1] ? Number(match[1]) : Number(now.date.slice(0, 4));
  if (!match[1] && now.date.slice(5, 7) === '01' && match[2] === '12') year--;
  const value = calendar(year, Number(match[2]), Number(match[3]), Number(match[4]), Number(match[5]), Number(match[6] || 0));
  return value !== null && value <= at ? value : null;
}
export function latestCustomer(messages, now) {
  const left = messages.filter(x => x.side === 'left' && String(x.text || '').trim());
  if (!left.length) return {message: null, uncertain: false};
  const timed = left.map(message => ({message, at: message.timeSource === 'message-formattime'
    ? parseMessageTime(message.timeLabel, now) : null}));
  const uncertain = messages.some(x => x.timeContextUncertain === true) || timed.some(x => x.at === null);
  const known = timed.filter(x => x.at !== null).sort((a, b) => a.at - b.at);
  const chosen = known.at(-1) || timed.at(-1);
  // Equal timestamps with different customer texts do not establish which request is last.
  const tied = chosen.at !== null && known.filter(x => x.at === chosen.at)
    .some(x => x.message.text !== chosen.message.text);
  return {message: chosen.message, uncertain: uncertain || tied,
    elapsedMs: chosen.at === null ? null : nowCalendarMs(now) - chosen.at};
}
export function recentMetadata(metadata, now) {
  const timed = metadata.map(x => ({...x, at: parseMessageTime(x.timeLabel, now)}));
  const uncertain = timed.some(x => x.side === 'left' && x.at === null);
  const selected = timed.sort((a, b) => (b.at ?? Infinity) - (a.at ?? Infinity) || b.index - a.index)
    .slice(0, 40).sort((a, b) => (a.at ?? Infinity) - (b.at ?? Infinity) || a.index - b.index);
  return {selected, uncertain};
}
