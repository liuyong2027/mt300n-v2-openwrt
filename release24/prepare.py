#!/usr/bin/env python3
"""Reconstruct immutable Release 23, then apply the reviewed Release 24 overlay."""
import base64
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
BASE_COMMIT='7b6152a172415b7a5605ccc3ba9ececb8f951966'
BASE_SHA256='e7d48db4b3117a29891d3ddfc09a1268f62c54462e8255717bd2387498067d7e'


def sha(data): return hashlib.sha256(data).hexdigest()


def bump(text):
    for old,new in [('Release 23','Release 24'), ("'23'","'24'"), ('v23.0.0','v24.0.0'),
                    ('mt300n-v2-23-','mt300n-v2-24-'), ('release23-source.zip.b64','release24-source.zip.b64'),
                    ('VALIDATION-23.json','VALIDATION-24.json'), ('RELEASE-23.md','RELEASE-24.md'),
                    ('SOURCE-DELTA-23.json','SOURCE-DELTA-24.json'),
                    ('codex/mt300n-v2-release23','codex/mt300n-v2-release24')]:
        text=text.replace(old,new)
    return text


def prepare(dest):
    spec=importlib.util.spec_from_file_location('release23_base',ROOT/'release23/prepare.py')
    baseline=importlib.util.module_from_spec(spec); spec.loader.exec_module(baseline)
    baseline.prepare(dest)
    raw=base64.b64decode((dest/'release23-source.zip.b64').read_text().strip(),validate=True)
    assert sha(raw)==BASE_SHA256, 'Release 23 recipe changed'
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert archive.testzip() is None
        original={p.filename:archive.read(p) for p in archive.infolist()}
        modes={p.filename:(p.external_attr>>16)&0o777 for p in archive.infolist()}
    content=dict(original)
    for path in sorted((ROOT/'release24/overlay').rglob('*')):
        if path.is_file() and '__pycache__' not in path.parts:
            name=path.relative_to(ROOT/'release24/overlay').as_posix()
            content[name]=path.read_bytes()
            modes[name]=modes.get(name,0o755 if content[name].startswith(b'#!') else 0o644)
    def edit(name, function): content[name]=function(content[name].decode()).encode()
    for name in ['scripts/package-release.py','scripts/publish-release.py',
                 'tests/test_release_packaging.py','tests/test_publish_draft_response.py']:
        edit(name,bump)
    for name in ['tests/test_watchdog_startup.sh','tests/test_watchdog_failure_status.sh','tests/test_intermittent_watchdog.sh']:
        edit(name,lambda s:s.replace('for n in sleep uci flock mango-ready mango-probe',
                                    'for n in mango-memory-guard sleep uci flock mango-ready mango-probe'))
        edit(name,lambda s:s.replace('case "${0##*/}" in','case "${0##*/}" in\n mango-memory-guard) case "$SCENARIO" in memory10) exit 10;; memory20) exit 20;; esac; exit 0;;'))
    edit('tests/test_watchdog_startup.sh', lambda s:s+'''\nfor scenario in memory10 memory20; do
    run "$scenario" 4
    ! grep -q '^probe ' "$t/events"
    ! grep -q '^failover ' "$t/events"
    echo "PASS memory guard result suppresses normal candidate startup: $scenario"
done
''')
    evidence='DEVICE-MEMORY-EVIDENCE-24.json'
    edit('scripts/package-release.py',lambda s:s.replace('DEVICE-HOTFIX-EVIDENCE-23.json',evidence)
         .replace("'device_hotfix_evidence':", "'device_memory_evidence':")
         .replace("'zerotier_target': read('reports/zt-direct-target.json'),",
                  "'zerotier_target': read('reports/zt-direct-target.json'),\n        'memory_target': memory,")
         .replace("    out = root / 'release-assets'", "    memory = read('reports/memory-target.json')\n    if (memory['status'] != 'passed' or memory['preflight_prior_target'] or\n            len(memory['installed_bytes_verified']) != 7 or len(memory['checks']) != 36):\n        raise ValueError('New compiled target memory gate failed')\n    out = root / 'release-assets'")
         .replace("'Recovery timings measured on previous image with matching runtime source; exact 21 image and LAN client forwarding remain untested'",
                  "'Memory hotfix evidence is from Release 23 plus identical installed helpers; the exact full Release 24 image has not been flashed. Full LAN/IPv6 forwarding and power-loss recovery remain untested'"))
    edit('scripts/publish-release.py',lambda s:s.replace('DEVICE-HOTFIX-EVIDENCE-23.json',evidence))
    content['files/etc/mango-release']=b'24\n'
    content['RELEASE-24.md']=(ROOT/'release24/RELEASE-24.md').read_bytes()
    content['README.md']=content['RELEASE-24.md']
    content[evidence]=(ROOT/'release24'/evidence).read_bytes()
    validation=json.loads(original['VALIDATION-23.json'])
    validation.update(version='24',date='2026-10-23',base_commit=BASE_COMMIT,
        artifact_scope='Release 23 plus validated bounded memory recovery, GC and VM/DNS defaults; existing features and owner configuration preserved',
        hardware_acceptance='Matching four runtime helpers tested as a Release 23 hotfix; exact Release 24 image pending',
        historical_evidence=evidence)
    validation['source_rootfs_sha256']={n.split('/root/',1)[1]:sha(b) for n,b in content.items() if n.startswith('package/luci-app-mango-proxy/root/')}
    content['VALIDATION-24.json']=(json.dumps(validation,indent=2)+'\n').encode()
    changed={n:{'before':sha(original[n]),'after':sha(b)} for n,b in content.items() if n in original and original[n]!=b and n!='SOURCE-FILES-SHA256SUMS'}
    allowed={'README.md','files/etc/mango-release','scripts/package-release.py','scripts/publish-release.py',
             'tests/test_release_packaging.py','tests/test_publish_draft_response.py',
             'tests/test_watchdog_startup.sh','tests/test_watchdog_failure_status.sh','tests/test_intermittent_watchdog.sh',
             'package/luci-app-mango-proxy/root/etc/init.d/mango_proxy',
             'package/luci-app-mango-proxy/root/usr/libexec/mango-watchdog'}
    assert set(changed)==allowed, sorted(changed)
    helpers=json.loads(content[evidence])['installed_helper_sha256']
    for name,digest in helpers.items():
        assert sha(content['package/luci-app-mango-proxy/root/'+name.lstrip('/')])==digest, name
    for name,data in original.items():
        if 'zt-direct' in name or 'zt-json' in name:
            assert content[name]==data, 'ZeroTier regression: '+name
    delta={'version':'24','base_tag':'v23.0.0','base_commit':BASE_COMMIT,'base_source_sha256':BASE_SHA256,
           'changed_files':changed,'added_files':{n:sha(b) for n,b in content.items() if n not in original},
           'unchanged_baseline_files':len(original)-len(changed)-1,
           'runtime_change':'GOGC=50; bounded low-memory SOCKS recovery; persistent VM reserve and missing-only DNS TCP default',
           'zerotier_runtime':'byte-identical to Release 23',
           'new_full_image_hardware_acceptance':'pending','device_memory_evidence':evidence}
    content['SOURCE-DELTA-24.json']=(json.dumps(delta,indent=2)+'\n').encode()
    content['SOURCE-FILES-SHA256SUMS']=''.join(sha(b)+'  '+n+'\n' for n,b in sorted(content.items()) if n!='SOURCE-FILES-SHA256SUMS').encode()
    (dest/'release23-source.zip.b64').unlink()
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for name,data in sorted(content.items()):
            path=dest/name; path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(data)
            mode=modes.get(name,0o755 if data.startswith(b'#!') else 0o644); path.chmod(mode)
            entry=zipfile.ZipInfo(name,(2026,10,23,0,0,0)); entry.create_system=3
            entry.external_attr=(0o100000|mode)<<16; entry.compress_type=zipfile.ZIP_DEFLATED
            archive.writestr(entry,data)
    source=buffer.getvalue(); (dest/'release24-source.zip.b64').write_text(base64.b64encode(source).decode()+'\n')
    if os.environ.get('GITHUB_ENV'):
        with open(os.environ['GITHUB_ENV'],'a') as env: env.write('RELEASE_SOURCE_SHA256='+sha(source)+'\n')
    print(json.dumps({'source_sha256':sha(source),'changed':sorted(changed),'added':sorted(delta['added_files'])},indent=2))
    return delta


if __name__=='__main__': prepare(Path(sys.argv[1] if len(sys.argv)>1 else ROOT/'source24'))
