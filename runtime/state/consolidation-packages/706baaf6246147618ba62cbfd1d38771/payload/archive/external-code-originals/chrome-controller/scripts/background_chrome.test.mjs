import test from 'node:test';
import assert from 'node:assert/strict';
import os from 'node:os';
import path from 'node:path';
import {pathsFor,safeProfileName,validPort,optionalLaunchArgs} from './background_chrome.mjs';

test('profile names are bounded',()=>{
  assert.equal(safeProfileName('taobao-brand'),'taobao-brand');
  assert.throws(()=>safeProfileName('../Default'),/invalid-profile-name/);
});

test('daily Chrome profile is rejected',()=>{
  assert.throws(()=>pathsFor({profile:'default','profile-root':path.join(os.homedir(),'Library/Application Support/Google/Chrome')}),/daily-chrome-profile-forbidden/);
});

test('ports are bounded',()=>{
  assert.equal(validPort('9230'),9230);assert.throws(()=>validPort('80'),/invalid-port/);
});

test('session preservation flags are explicit and isolated',()=>{
  assert.deepEqual(optionalLaunchArgs({}),[]);
  assert.deepEqual(optionalLaunchArgs({'disable-background-mode':true}),['--disable-background-mode']);
  assert.deepEqual(optionalLaunchArgs({'restore-last-session':true}),['--restore-last-session']);
});
