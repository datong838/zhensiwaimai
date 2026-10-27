import assert from 'node:assert/strict';
import { mayFallbackFromWecom, resolveWechatChannel } from './wechat_channel_policy.mjs';

assert.equal(resolveWechatChannel(undefined), 'auto');
assert.equal(resolveWechatChannel('auto'), 'auto');
assert.equal(resolveWechatChannel('wecom'), 'wecom');
assert.equal(resolveWechatChannel('desktop'), 'desktop');
assert.equal(resolveWechatChannel('mobile'), 'mobile');
assert.throws(() => resolveWechatChannel('other'), /wechat-channel-invalid/);
assert.equal(mayFallbackFromWecom('wecom-not-running'), true);
assert.equal(mayFallbackFromWecom('wecom-upload-outcome-unknown'), false);
console.log(JSON.stringify({ok:true,tests:8,defaultChannel:'auto'}));
