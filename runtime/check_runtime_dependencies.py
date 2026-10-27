"""Read-only deployed dependency baseline check. Never installs or runs business code."""
import argparse
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent.parent


def probe(argv):
    env = {k: v for k, v in os.environ.items()
           if k not in ('PYTHONPATH', 'PYTHONSTARTUP')}
    result = subprocess.run(argv, capture_output=True, text=True, timeout=10,
                            check=True, env=env)
    return json.loads(result.stdout)


def check_dependencies(contract, manifest, runner=probe):
    checks = []

    def record(name, expected, actual, exists=True):
        checks.append({'name': name, 'expected': expected, 'actual': actual,
                       'ok': exists and actual == expected})

    node = os.environ.get('ZENSI_NODE') or manifest['interpreters']['node']
    python = os.environ.get('ZENSI_PYTHON') or manifest['interpreters']['python']
    try:
        actual = runner([node, '--eval',
                         'process.stdout.write(JSON.stringify({version:process.versions.node,'
                         'webSocket:typeof globalThis.WebSocket === "function"}))'])
        record('node-version', contract['runtime']['node']['observedVersion'], actual.get('version'))
        record('node-native-WebSocket', True, actual.get('webSocket'))
    except (OSError, subprocess.SubprocessError, ValueError, TypeError) as error:
        record('node-probe', 'available', type(error).__name__, False)
    packages = contract['runtime']['python']['observedBusinessDependencyClosure']
    script = ('import json,sys;from importlib.metadata import version,PackageNotFoundError;'
              'names=json.loads(sys.argv[1]);packages={};\n'
              'for name in names:\n'
              ' try: packages[name]=version(name)\n'
              ' except PackageNotFoundError: packages[name]=None\n'
              'print(json.dumps({"version":sys.version.split()[0],"packages":packages}))')
    try:
        actual = runner([python, '-c', script, json.dumps(list(packages))])
        record('python-version', contract['runtime']['python']['observedVersion'], actual.get('version'))
        for name, expected in packages.items():
            record('python:' + name, expected, actual.get('packages', {}).get(name))
    except (OSError, subprocess.SubprocessError, ValueError, TypeError) as error:
        record('python-probe', 'available', type(error).__name__, False)
    libraries = [(item['name'] + ':' + item['version'], Path(item['path']), item['version'])
                 for item in contract['browserComponents']]
    libraries.extend((name, Path(contract['hostNodeLibraries']['currentRoot']) / name, expected)
                     for name, expected in contract['hostNodeLibraries']['observed'].items())
    for name, folder, expected in libraries:
        try:
            actual = json.loads((folder / 'package.json').read_text())['version']
            record('node-library:' + name, expected, actual)
        except (OSError, ValueError, KeyError, TypeError) as error:
            record('node-library:' + name, expected, type(error).__name__, False)
    return {'ok': all(item['ok'] for item in checks), 'checks': checks,
            'interpreters': {'node': node, 'python': python},
            'scope': 'deployed versions and capabilities only; no install or business execution',
            'productionActions': 0}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    contract = json.loads((args.root / 'runtime/dependency-contract.json').read_text())
    manifest = json.loads((args.root / 'runtime/skills_manifest.json').read_text())
    result = check_dependencies(contract, manifest)
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result['ok'] else 2)
