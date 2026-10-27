// Compatibility discovery/export only. Canonical implementation is maintained in this repository.
import {pathToFileURL} from 'node:url';
import {selfTest} from '../../../skills/workflows/daily-taobao-download-to-jinsha/scripts/background_browser_executor.mjs';
export * from '../../../skills/workflows/daily-taobao-download-to-jinsha/scripts/background_browser_executor.mjs';
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const args=process.argv.slice(2);
  const result=args.length===1 && args[0]==='--self-test'
    ? selfTest() : {ok:false,reason:'business-cli-disabled-use-installed-entrypoint'};
  console.log(JSON.stringify(result));
  if (!result.ok) process.exitCode=1;
}
