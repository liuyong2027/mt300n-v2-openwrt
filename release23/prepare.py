#!/usr/bin/env python3
"""Build Release 23 from the exact Release 22 source recipe and a narrow overlay."""
import base64
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BASE_SHA256 = '9fe237d2069d4e4789d6dbbda7005fc3921db91e23c0e220aa3edde1d04b4116'
BASE_COMMIT = 'b58f524d70b1c7ab37a279cdadbddb2685af04ca'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def prepare(dest):
    spec = importlib.util.spec_from_file_location('release22_base', ROOT / 'release22/prepare.py')
    baseline = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(baseline)
    baseline.prepare(dest)
    raw = base64.b64decode((dest / 'release22-source.zip.b64').read_text().strip(), validate=True)
    assert sha(raw) == BASE_SHA256, 'Release 22 recipe changed'
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert archive.testzip() is None
        original = {p.filename: archive.read(p) for p in archive.infolist()}
        modes = {p.filename: (p.external_attr >> 16) & 0o777 for p in archive.infolist()}
    content = dict(original)
    overlay = ROOT / 'release23/overlay'
    for path in sorted(overlay.rglob('*')):
        if path.is_file() and '__pycache__' not in path.parts:
            name = path.relative_to(overlay).as_posix()
            content[name] = path.read_bytes()
            modes[name] = modes.get(name, 0o755 if content[name].startswith(b'#!') else 0o644)

    def edit(name, function):
        content[name] = function(content[name].decode()).encode()

    def bump(text):
        for old, new in [('Release 22', 'Release 23'), ("'22'", "'23'"),
                         ('v22.0.0', 'v23.0.0'), ('mt300n-v2-22-', 'mt300n-v2-23-'),
                         ('release22-source.zip.b64', 'release23-source.zip.b64'),
                         ('VALIDATION-22.json', 'VALIDATION-23.json'),
                         ('RELEASE-22.md', 'RELEASE-23.md'), ('SOURCE-DELTA-22.json', 'SOURCE-DELTA-23.json'),
                         ('codex/mt300n-v2-release22', 'codex/mt300n-v2-release23')]:
            text = text.replace(old, new)
        return text

    for name in ['scripts/package-release.py', 'scripts/publish-release.py', 'tests/test_release_packaging.py']:
        edit(name, bump)
    evidence = 'DEVICE-HOTFIX-EVIDENCE-23.json'
    edit('scripts/package-release.py', lambda s: s.replace("'SOURCE-DELTA-23.json']", "'SOURCE-DELTA-23.json', 'DEVICE-HOTFIX-EVIDENCE-23.json']").replace("'zerotier_target': read('reports/zt-direct-target.json'),", "'zerotier_target': read('reports/zt-direct-target.json'),\n        'device_hotfix_evidence': read('DEVICE-HOTFIX-EVIDENCE-23.json'),"))
    edit('scripts/publish-release.py', lambda s: s.replace("'SOURCE-DELTA-23.json'}", "'SOURCE-DELTA-23.json', 'DEVICE-HOTFIX-EVIDENCE-23.json'}"))
    content['files/etc/mango-release'] = b'23\n'
    content['RELEASE-23.md'] = (ROOT / 'release23/RELEASE-23.md').read_bytes()
    content['README.md'] = content['RELEASE-23.md']
    content[evidence] = (ROOT / 'release23' / evidence).read_bytes()
    validation = json.loads(original['VALIDATION-22.json'])
    validation.update(version='23', date='2026-10-21', base_commit=BASE_COMMIT,
                      artifact_scope='Release 22 plus native ubus timeout fix; existing configuration and other runtime preserved',
                      hardware_acceptance='Same one-line helper hotfix tested on Release 22 hardware; exact full Release 23 image pending',
                      historical_evidence='DEVICE-HOTFIX-EVIDENCE-23.json covers this helper hotfix only')
    validation['source_rootfs_sha256'] = {n.split('/root/', 1)[1]: sha(b) for n,b in content.items() if n.startswith('package/luci-app-mango-proxy/root/')}
    content['VALIDATION-23.json'] = (json.dumps(validation, indent=2)+'\n').encode()
    changed = {n: {'before': sha(original[n]), 'after': sha(b)} for n,b in content.items() if n in original and original[n] != b and n != 'SOURCE-FILES-SHA256SUMS'}
    allowed = {'README.md', 'files/etc/mango-release', 'scripts/package-release.py', 'scripts/publish-release.py',
               'tests/test_release_packaging.py', 'scripts/verify-zt-target.py', 'tests/zt-direct-runner.lua',
               'package/luci-app-mango-proxy/root/usr/libexec/mango-zt-direct-run'}
    assert set(changed) == allowed, sorted(changed)
    helper = 'package/luci-app-mango-proxy/root/usr/libexec/mango-zt-direct-run'
    assert sha(content[helper]) == 'bda24368ea471e02e48508b81b1d2d3a8c3786cfd8b677cf7283d3de3657de91'
    delta = {'version': '23', 'base_tag': 'v22.0.0', 'base_commit': BASE_COMMIT,
             'base_source_sha256': BASE_SHA256, 'changed_files': changed,
             'added_files': {n: sha(b) for n,b in content.items() if n not in original},
             'unchanged_baseline_files': len(original)-len(changed)-1,
             'runtime_change': 'Only native ubus -t 3 replaces missing external timeout; all other runtime and defaults byte-identical to Release 22',
             'new_full_image_hardware_acceptance': 'pending', 'device_hotfix_evidence': evidence}
    content['SOURCE-DELTA-23.json'] = (json.dumps(delta,indent=2)+'\n').encode()
    content['SOURCE-FILES-SHA256SUMS'] = ''.join(sha(b)+'  '+n+'\n' for n,b in sorted(content.items()) if n != 'SOURCE-FILES-SHA256SUMS').encode()
    (dest / 'release22-source.zip.b64').unlink()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for name,data in sorted(content.items()):
            path=dest/name; path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(data)
            mode=modes.get(name,0o755 if data.startswith(b'#!') else 0o644)
            path.chmod(mode)
            entry=zipfile.ZipInfo(name,(2026,10,21,0,0,0)); entry.create_system=3
            entry.external_attr=(0o100000|mode)<<16; entry.compress_type=zipfile.ZIP_DEFLATED
            archive.writestr(entry,data)
    source=buffer.getvalue()
    (dest/'release23-source.zip.b64').write_text(base64.b64encode(source).decode()+'\n')
    if os.environ.get('GITHUB_ENV'):
        with open(os.environ['GITHUB_ENV'],'a') as env:
            env.write('RELEASE_SOURCE_SHA256='+sha(source)+'\n')
    print(json.dumps({'source_sha256':sha(source),'changed':sorted(changed),'added':sorted(delta['added_files'])},indent=2))
    return delta


if __name__ == '__main__':
    prepare(Path(sys.argv[1] if len(sys.argv)>1 else ROOT/'source23'))
