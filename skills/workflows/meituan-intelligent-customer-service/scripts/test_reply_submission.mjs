import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { replyBinding, inspectReplySubmission, submitReplyOnce, assertReplyDraft } from './reply_submission.mjs';
import { processCards, judge, collectAllCards } from './reply_unanswered_sessions.mjs';

const request = { sessionId: '1234567890123456789', customerText: '少送米饭 11:00', reply: '请联系门店核实处理。' };
async function temporary(t) {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'customer-reply-once-'));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  return root;
}

test('full draft contract preserves user text and rejects prefix-only draft', () => {
  assertReplyDraft('', ''); assertReplyDraft(request.reply, request.reply);
  assert.throws(() => assertReplyDraft('用户草稿', ''), /not-empty/);
  assert.throws(() => assertReplyDraft(request.reply.slice(0, 5), request.reply), /fulltext/);
  assert.throws(() => assertReplyDraft(request.reply + '多余文字', request.reply), /fulltext/);
});

test('exact session ID and bounded original text required', () => {
  for (const sessionId of ['', '123', 'not-session', '1234567890123456789"']) {
    assert.throws(() => replyBinding({ ...request, sessionId }), /binding-invalid/);
  }
  assert.throws(() => replyBinding({ ...request, customerText: 'x'.repeat(401) }), /binding-invalid/);
  assert.throws(() => replyBinding({ ...request, customerText: '' }), /binding-invalid/);
});

test('own prior fallback is a reply even when nickname contains 小美', () => {
  const fallback = '您好，理解这件事给您带来的不便，抱歉让您久等了。我会尽快联系商家核实处理；具体处理方式需要以门店确认的实际情况为准，您也可以直接联系门店，以便更快处理。';
  const decision = judge('甲** 11:00', [{ side: 'left', text: '少送米饭11:00' },
    { side: 'right', nick: '商家总客服小美', text: fallback }], { date: '2026-10-28', h: 12, m: 0 });
  assert.equal(decision.qualify, false); assert.match(decision.reason, /owner-human-reply-present/);
});

for (const [proof, expected] of [['echo', 'verified'], ['list-gone', 'verified'], [null, 'unknown'], ['weak-prefix', 'unknown']]) {
  test('one submit, proof=' + proof, async t => {
    const root = await temporary(t); let calls = 0;
    const result = await submitReplyOnce(root, request, async () => calls++, async () => proof);
    assert.equal(calls, 1); assert.equal(result.state, expected);
    const bytes = await fs.readFile(result.file, 'utf8');
    for (let i = 0; i < 2; i++) {
      const prior = await submitReplyOnce(root, request, async () => calls++, async () => 'echo');
      assert.equal(prior.newSubmitCalls, 0); assert.equal(prior.state, expected);
    }
    assert.equal(calls, 1); assert.equal(await fs.readFile(result.file, 'utf8'), bytes);
    assert.ok(!bytes.includes(request.sessionId)); assert.ok(!bytes.includes(request.customerText));
    assert.ok(!bytes.includes(request.reply));
  });
}

test('submission exception is unknown and never invokes second send', async t => {
  const root = await temporary(t); let calls = 0, verifications = 0;
  const result = await submitReplyOnce(root, request, async () => { calls++; throw Error('uncertain'); }, async () => verifications++);
  assert.equal(result.state, 'unknown'); assert.equal(calls, 1); assert.equal(verifications, 0);
  await submitReplyOnce(root, request, async () => calls++, async () => 'echo');
  assert.equal(calls, 1);
});

test('verification exception remains unknown after exactly one send', async t => {
  const root = await temporary(t); let calls = 0;
  const result = await submitReplyOnce(root, request, async () => calls++, async () => { throw Error('read failed'); });
  assert.equal(result.state, 'unknown'); assert.equal(calls, 1);
});

test('two concurrent claimers have one physical submission call', async t => {
  const root = await temporary(t); let calls = 0;
  const results = await Promise.all(Array.from({ length: 2 }, () => submitReplyOnce(root, request, async () => {
    calls++; await new Promise(resolve => setTimeout(resolve, 10));
  }, async () => 'echo')));
  assert.equal(calls, 1); assert.equal(results.reduce((sum, x) => sum + x.newSubmitCalls, 0), 1);
});

test('crash after durable intent is read-only; no date/run-key bypass', async t => {
  const root = await temporary(t); const binding = replyBinding(request);
  const folder = path.join(root, binding.sessionSha256); await fs.mkdir(folder);
  const file = path.join(folder, binding.customerTextSha256 + '.json');
  const bytes = JSON.stringify({ ...binding, date: '2026-10-27', state: 'attempted' });
  await fs.writeFile(file, bytes);
  const result = await submitReplyOnce(root, request, async () => assert.fail('must not submit'), async () => 'echo');
  assert.equal(result.newSubmitCalls, 0); assert.equal(result.state, 'attempted');
  assert.equal(await fs.readFile(file, 'utf8'), bytes);
});

test('bad prior record, changed reply and source collision cannot create new attempt', async t => {
  const root = await temporary(t);
  const first = await submitReplyOnce(root, request, async () => {}, async () => null);
  const changed = await submitReplyOnce(root, { ...request, reply: 'different' }, async () => assert.fail('no bypass'), async () => 'echo');
  assert.equal(changed.state, 'blocked');
  await fs.writeFile(first.file, '{partial');
  assert.equal((await inspectReplySubmission(root, replyBinding(request))).state, 'blocked');
});

test('different session or real distinct customer message is independent', async t => {
  const root = await temporary(t); let calls = 0;
  for (const input of [request, { ...request, sessionId: '2234567890123456789' },
    { ...request, customerText: '少送米饭 12:00' }]) {
    await submitReplyOnce(root, input, async () => calls++, async () => null);
  }
  assert.equal(calls, 3);
});

function fakePage({ echo = false, draft = '', cardCount = 1 } = {}) {
  const state = { input: draft, sends: 0, enters: 0, types: 0 };
  const card = { count: async () => cardCount, click: async () => {} };
  const textarea = { count: async () => 1, click: async () => {}, inputValue: async () => state.input,
    pressSequentially: async value => { state.types++; state.input += value; },
    press: async () => { state.enters++; assert.fail('second submit forbidden'); },
    boundingBox: async () => ({ x: 10, y: 10, width: 100, height: 50 }) };
  const button = { boundingBox: async () => ({ x: 120, y: 10, width: 50, height: 50 }), isVisible: async () => true,
    isEnabled: async () => true, evaluate: async () => false, click: async () => { state.sends++; state.reply = state.input; state.input = ''; } };
  const entries = [{ sessionId: request.sessionId, text: '甲**（测试门店） 少送米饭 11:00' }];
  return { state, entries, page: { waitForTimeout: async () => {}, locator(selector) {
    if (selector.startsWith('.roo-modal-dialog')) return { filter: () => ({ count: async () => 0 }) };
    if (selector.startsWith('[class*=')) {
      assert.ok(selector.includes('[id="' + request.sessionId + '"]')); return card;
    }
    if (selector.startsWith('textarea')) return textarea;
    if (selector === 'button') return { filter: () => ({ count: async () => 1, nth: () => button }) };
    throw Error('unexpected locator:' + selector);
  }, evaluate: async callback => callback.toString().includes('.message-item')
    ? [{ side: 'left', text: request.customerText, timeSource: 'message-formattime', timeLabel: '10-28 11:00:00' }, ...(echo && state.sends ? [{ side: 'right', text: echo === 'prefix' ? state.reply.slice(0, 12) : state.reply }] : [])]
    : entries } };
}

function receipt() { return { date: '2026-10-28', scanned: 0, decisions: [], sent: [], failed: [], verificationPending: [] }; }

for (const echo of [false, true, 'prefix']) test('original processCards one submit with echo=' + echo, async t => {
  const root = await temporary(t); const mock = fakePage({ echo }); let ledger = 0;
  const options = { submissions: root, appendLedger: async () => ledger++ };
  const first = receipt(); await processCards(mock.page, mock.entries, first, { date: '2026-10-28', h: 12, m: 0 }, new Set(), '未回复', options);
  assert.equal(mock.state.sends, 1); assert.equal(mock.state.enters, 0); assert.equal(ledger, 1);
  assert.equal(first.verificationPending.length, echo === true ? 0 : 1);
  const second = receipt(); await processCards(mock.page, mock.entries, second, { date: '2026-10-28', h: 15, m: 0 }, new Set(), '未回复', options);
  assert.equal(mock.state.sends, 1); assert.equal(mock.state.types, 1); assert.equal(ledger, 1);
});

test('existing user draft stops before typing, intent or send', async t => {
  const root = await temporary(t); const mock = fakePage({ draft: '用户草稿' });
  await assert.rejects(processCards(mock.page, mock.entries, receipt(), { date: '2026-10-28', h: 12, m: 0 }, new Set(), '未回复',
    { submissions: root, appendLedger: async () => assert.fail('no ledger') }), /not-empty/);
  assert.equal(mock.state.types, 0); assert.equal(mock.state.sends, 0); assert.deepEqual(await fs.readdir(root), []);
});

test('ambiguous session cards stop before opening or sending', async t => {
  const root = await temporary(t); const mock = fakePage({ cardCount: 2 });
  await assert.rejects(processCards(mock.page, mock.entries, receipt(), { date: '2026-10-28', h: 12, m: 0 }, new Set(), '未回复',
    { submissions: root }), /not-unique/);
  assert.equal(mock.state.sends, 0);
});

test('card discovery keeps distinct exact IDs even when preview text is equal', async () => {
  const previous = globalThis.document;
  const cards = ['1234567890123456789', '2234567890123456789'].map(id => ({ id, innerText: '相同脱敏标题', closest: () => null }));
  globalThis.document = { querySelector: selector => selector.includes('sessionListContent') ? null : cards[0],
    querySelectorAll: () => cards };
  try {
    const result = await collectAllCards({ evaluate: callback => callback() });
    assert.equal(result.length, 2); assert.notEqual(result[0].sessionId, result[1].sessionId);
    cards[1].id = 'invalid-nonempty-id';
    await assert.rejects(collectAllCards({ evaluate: callback => callback() }), /session-id-unavailable/);
  } finally { globalThis.document = previous; }
});
