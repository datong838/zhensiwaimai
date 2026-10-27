import test from 'node:test';
import assert from 'node:assert/strict';
import {acquireJinshaLease, releaseJinshaLease} from './lease.mjs';
import {assertJinshaOrigin} from './connect.mjs';
import {waitPaginationStable} from './pagination.mjs';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';

test('租约：首次获取成功，owner 匹配可释放', async () => {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'jinsha-lease-'));
  const leasePath = path.join(dir, 'test.lock');
  const lease = await acquireJinshaLease('run-1', leasePath, 1000);
  assert.equal(lease.runId, 'run-1');
  assert.equal(lease.path, leasePath);
  const released = await releaseJinshaLease(lease);
  assert.equal(released, true);
});

test('租约：占用中第二次获取 → jinsha-lease-busy', async () => {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'jinsha-lease-'));
  const leasePath = path.join(dir, 'test.lock');
  await acquireJinshaLease('run-a', leasePath, 60000);
  await assert.rejects(() => acquireJinshaLease('run-b', leasePath, 60000), /jinsha-lease-busy/);
});

test('租约：owner 不符释放 → jinsha-lease-owner-mismatch', async () => {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'jinsha-lease-'));
  const leasePath = path.join(dir, 'test.lock');
  const lease = await acquireJinshaLease('run-1', leasePath, 60000);
  await assert.rejects(() => releaseJinshaLease({...lease, runId: 'run-2'}), /jinsha-lease-owner-mismatch/);
  await releaseJinshaLease(lease);
});

test('origin 断言：金鲨 origin 放行，其它拒绝', () => {
  assert.equal(assertJinshaOrigin('https://data.guoshuyufen.com/#/reportDownload'), true);
  assert.throws(() => assertJinshaOrigin('https://evil.com/'), /jinsha-origin-changed/);
});

test('分页稳定：mock page 四方一致稳定两次放行', async () => {
  let calls = 0;
  const make = (total, size, active, rows) => ({
    locator: (sel) => {
      if (sel === '.el-pagination__total:visible') return {count: async () => 1, innerText: async () => `共 ${total} 条`};
      if (sel === 'input[placeholder="请选择"]:visible') return {count: async () => 1, inputValue: async () => `${size}条/页`};
      if (sel === '.el-pager li.active:visible') return {count: async () => 1, innerText: async () => String(active)};
      if (sel === '.cryptonym:visible') return {count: async () => rows};
      return {count: async () => 0};
    },
  });
  const page = make(40, 20, 1, 20);
  calls++;
  const result = await waitPaginationStable(page, {pageNumber: 1, rowSelector: '.cryptonym:visible'});
  assert.equal(result.expected, 40);
  assert.equal(result.totalPages, 2);
});
