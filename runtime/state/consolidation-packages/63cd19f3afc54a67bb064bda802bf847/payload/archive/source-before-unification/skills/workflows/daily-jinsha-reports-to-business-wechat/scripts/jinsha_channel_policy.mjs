const ALLOWED = new Set(['browser', 'desktop']);

function resolveJinshaChannel(value) {
  const channel = value ?? 'browser';
  if (!ALLOWED.has(channel)) throw Error(`invalid-jinsha-channel:${channel}`);
  return channel;
}

export { resolveJinshaChannel };
