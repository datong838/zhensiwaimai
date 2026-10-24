// 测试隔离硬闸门（Node 侧运行时控制）
// 设计原则（test-isolation-contract skill）：光靠字符串约定拦不住事故，
// 决定性的是「能力隔离」——让「连真机 / 写生产状态 / 调真实发送器」在测试进程内直接抛错，
// 且不依赖测试作者记得。本模块在 import 时自动 install()。
//
// 规则（大同 2026-10-01 定）：测试脚本不允许执行正规生产流程；只允许发到「臻肆测试群」。
//
// 三层防御：
//   ① ZHS_TEST_MODE=1 环境变量（发送层据此拒绝构造真实适配器）；
//   ② 网络拦截：非回环 / 真实机器端点 connect 直接抛错（原型可写，可靠）；
//   ③ 子进程拦截：尝试劫持 child_process 的 execFile/spawn/exec，若运行时命名空间只读则
//      安全降级，退回「静态审计器 + 网络拦截 + ZHS_TEST_MODE」组合（见 maintenance/audit_test_isolation.py）。

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join, basename, resolve } from 'node:path';
import * as cp from 'node:child_process';
import * as net from 'node:net';
import * as tls from 'node:tls';

// 单一数据源：消费仓库 canonical 策略表 maintenance/test-isolation-policy.json
const __dirname = dirname(fileURLToPath(import.meta.url));
const POLICY_PATH = resolve(__dirname, '..', 'maintenance', 'test-isolation-policy.json');
const STRATEGY = JSON.parse(readFileSync(POLICY_PATH, 'utf8'));

const SENDER_BASES = new Set((STRATEGY.productionSenders || []).map((s) => basename(s)));
const DANGEROUS = new Set(STRATEGY.dangerousFlags || []);
const ENDPOINTS = STRATEGY.realMachineEndpoints || STRATEGY.forbiddenHosts || [];

let _installed = false;
let _cp_patched = false;

function flatArgs(args) {
  // 把 execFile(file, argsArray) / spawn(file, argsArray) 的参数拍平成可匹配的字符串列表
  if (Array.isArray(args)) return args.map(String);
  if (typeof args === 'string') return [args];
  return [];
}

function hitSenderOrDanger(argsList) {
  const joined = argsList.join(' ').toLowerCase();
  for (const s of SENDER_BASES) {
    if (joined.includes(s.toLowerCase())) return `sender:${s}`;
  }
  for (const f of DANGEROUS) {
    // 仅当参数里出现 --execute / --send / --deliver 这类真实发送开关时拦截
    if (argsList.includes(f)) return `flag:${f}`;
  }
  return null;
}

function blockReason(program, args) {
  const prog = String(program || '');
  const argsList = flatArgs(args);
  // 子进程程序本身若是发送器则拦截
  if (SENDER_BASES.has(basename(prog))) return `sender-program:${basename(prog)}`;
  const hit = hitSenderOrDanger([prog, ...argsList]);
  if (hit) return hit;
  return null;
}

function guardChildProcess(role, program, args) {
  const reason = blockReason(program, args);
  if (reason) {
    throw new Error(
      `[ISOLATION-GATE] 测试进程试图调用真实发送/生产入口，已拒绝 (${role}): ${String(program)} ${flatArgs(args).join(' ')} — 命中 ${reason}。测试只允许发到「臻肆测试群」，或调用 --selftest/--verify 等非发送子命令。`
    );
  }
}

function isLoopback(host) {
  if (host == null) return true;
  const h = String(host);
  if (h === 'localhost' || h === '::1' || h === '127.0.0.1') return true;
  if (h.startsWith('127.')) return true;
  if (h.startsWith('/') || h.startsWith('@')) return true; // AF_UNIX 路径
  return false;
}

function guardConnect(host, role) {
  if (isLoopback(host)) return;
  const h = String(host);
  if (ENDPOINTS.some((e) => h.includes(e))) {
    throw new Error(`[ISOLATION-GATE] 测试进程试图连接真实机器端点，已拒绝 (${role}): ${h}`);
  }
  // 非回环一律拒绝，避免任何外发
  throw new Error(`[ISOLATION-GATE] 测试进程试图连接非回环地址，已拒绝 (${role}): ${h}。测试不得触达真实服务。`);
}

export function install() {
  if (_installed) return;
  _installed = true;

  // 强制测试模式环境变量；生产传输层应据此拒绝构造真实适配器
  if (process.env.ZHS_TEST_MODE !== '1') {
    process.env.ZHS_TEST_MODE = '1';
  }

  // —— 子进程发送拦截（命名空间可能只读，失败则安全降级） ——
  try {
    const origExecFile = cp.execFile;
    cp.execFile = function (program, args, options, cb) {
      // 兼容 execFile(program, cb) / execFile(program, args, cb) 等多种签名
      let a = args, c = cb, o = options;
      if (typeof args === 'function') { c = args; a = []; o = options; }
      if (typeof options === 'function') { c = options; o = undefined; }
      guardChildProcess('execFile', program, a);
      return origExecFile.call(this, program, a, o, c);
    };
    const origExecFileSync = cp.execFileSync;
    cp.execFileSync = function (program, args, options) {
      guardChildProcess('execFileSync', program, args);
      return origExecFileSync.call(cp, program, args, options);
    };
    const origSpawn = cp.spawn;
    cp.spawn = function (program, args, options) {
      guardChildProcess('spawn', program, args);
      return origSpawn.call(this, program, args, options);
    };
    const origExec = cp.exec;
    cp.exec = function (cmd, options, cb) {
      let c = cb; if (typeof options === 'function') { c = options; }
      if (typeof cmd === 'string' && hitSenderOrDanger(cmd.split(/\s+/))) {
        throw new Error(`[ISOLATION-GATE] 测试进程试图经 shell 调用真实发送入口，已拒绝 (exec): ${cmd}`);
      }
      return origExec.call(this, cmd, options, c);
    };
    _cp_patched = true;
  } catch (e) {
    // 命名空间只读时无法劫持；退回静态审计器 + 网络拦截 + ZHS_TEST_MODE
    console.warn('[ISOLATION-GATE] child_process 运行时拦截不可用（命名空间只读），已安全降级：' +
      '静态审计器 + 网络拦截 + ZHS_TEST_MODE 仍生效。', e && e.message);
  }

  // —— 网络连接拦截（非回环 / 真实机器） ——
  try {
    const origNetConnect = net.Socket.prototype.connect;
    net.Socket.prototype.connect = function (...cargs) {
      let host = null;
      const first = cargs[0];
      if (first && typeof first === 'object') host = first.host ?? first.path ?? null;
      else if (typeof cargs[1] === 'string') host = cargs[1];
      try { guardConnect(host, 'net.connect'); } catch (e) { throw e; }
      return origNetConnect.apply(this, cargs);
    };
  } catch (e) {
    console.warn('[ISOLATION-GATE] net.Socket.connect 拦截失败：', e && e.message);
  }
  try {
    const origTlsConnect = tls.connect;
    tls.connect = function (...cargs) {
      let host = null;
      const first = cargs[0];
      if (first && typeof first === 'object') host = first.host ?? first.path ?? null;
      else if (typeof cargs[1] === 'string') host = cargs[1];
      guardConnect(host, 'tls.connect');
      return origTlsConnect.apply(tls, cargs);
    };
  } catch (e) {
    console.warn('[ISOLATION-GATE] tls.connect 拦截失败：', e && e.message);
  }

  return true;
}

export const strategy = STRATEGY;
export const meta = { installed: () => _installed, cpPatched: () => _cp_patched, senderBases: [...SENDER_BASES], dangerous: [...DANGEROUS] };

// import 即自动安装，无需测试显式调用
install();
