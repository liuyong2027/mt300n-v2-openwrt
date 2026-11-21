"""Compile Samba's actual DOS mode function with stale-attribute fixtures."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import urllib.request


HERE = Path(__file__).resolve().parent
SOURCE_SHA256 = 'e88454023852cc1d2e59e8603e70e167feba26099d5e42f5251020793b03b5f2'
SOURCE_URL = ('https://raw.githubusercontent.com/samba-team/samba/'
              'samba-4.22.7/source3/smbd/dosmode.c')


def dos_mode_function(source):
    start = source.index('static uint32_t dos_mode_post(')
    end = source.index('\n}\n', start) + 3
    return source[start:end]


def check(source, work, name):
    harness = (HERE / 'dosmode-test.c').read_text()
    program = work / (name + '.c')
    program.write_text(harness.replace('/* DOS_MODE_FUNCTION */', dos_mode_function(source)))
    executable = work / name
    subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                    str(program), '-o', str(executable)], check=True)
    result = subprocess.run([str(executable)], capture_output=True, text=True)
    print(name + '\n' + result.stdout + result.stderr, end='')
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    raw = args.source.read_bytes() if args.source else urllib.request.urlopen(SOURCE_URL, timeout=30).read()
    if hashlib.sha256(raw).hexdigest() != SOURCE_SHA256:
        raise ValueError('Pinned Samba dosmode.c changed')
    source = raw.decode('utf-8')
    with tempfile.TemporaryDirectory(prefix='samba-dosmode-') as directory:
        work = Path(directory)
        old = check(source, work, 'unpatched')
        if old.returncode != 1 or 'regular file with stale directory bit' not in old.stderr:
            raise AssertionError('Old Samba must reproduce the regular-file directory bug')
        target = work / 'source3/smbd/dosmode.c'
        target.parent.mkdir(parents=True)
        target.write_bytes(raw)
        patch = HERE.parent / 'patches/200-dos-mode-use-actual-file-type.patch'
        subprocess.run(['patch', '--batch', '--fuzz=0', '-p1', '-i', str(patch)],
                       cwd=work, check=True)
        new = check(target.read_text(), work, 'patched')
        if new.returncode != 0:
            raise AssertionError('Patched Samba must pass all file-type cases')
        report = {'samba_version': '4.22.7', 'source_sha256': SOURCE_SHA256,
                  'patch_sha256': hashlib.sha256(patch.read_bytes()).hexdigest(),
                  'old_bug_reproduced': True, 'patched_cases_passed': 10,
                  'packed_hardware_tested': False}
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
