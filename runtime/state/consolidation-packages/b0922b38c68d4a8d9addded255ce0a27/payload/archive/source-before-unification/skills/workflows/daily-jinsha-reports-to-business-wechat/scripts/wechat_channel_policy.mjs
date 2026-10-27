export function resolveWechatChannel(value) {
  if (value !== undefined && !['auto', 'wecom', 'desktop', 'mobile'].includes(value)) throw Error('wechat-channel-invalid');
  return value || 'auto';
}

export function mayFallbackFromWecom(reason) {
  return ['wecom-not-running', 'wecom-not-logged-in'].includes(reason);
}
