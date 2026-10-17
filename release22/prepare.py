#!/usr/bin/env python3
"""Reproduce Release 22 from the checksum-locked Release 21 source plus reviewable additions."""
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import zipfile
import io

ROOT = Path(__file__).resolve().parents[1]
BASE_SHA256 = 'f532e8fa2d4e839db9d1a1baba790f3212d346987ba484775b0ad7044bdc9231'
BASE_COMMIT = 'e77231ac984c411ad4b1c96c1abd486606f3fbca'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def preserve_defaults(source):
    prefix = "#!/bin/sh\nuci -q batch <<'EOF'\n"
    assert source.startswith(prefix), 'Unexpected Release 21 firewall defaults'
    body, tail = source[len(prefix):].split('\nEOF\n', 1)
    groups = {}
    for line in body.splitlines():
        if line == 'commit firewall':
            continue
        match = re.match(r'(?:set|add_list|delete) firewall\.([a-z_]+)(?:[.=])', line)
        assert match, line
        groups.setdefault(match[1], []).append(line)
    out = ['#!/bin/sh', '# Preserve existing owner sections and disabled policies on settings upgrades.']
    for section, lines in groups.items():
        out += [f'if ! uci -q get firewall.{section} >/dev/null; then', "uci -q batch <<'EOF'"]
        out += lines + ['EOF', 'fi']
    return '\n'.join(out + ['uci -q commit firewall', tail.rstrip('\n')]) + '\n'


def prepare(dest):
    dest.mkdir()  # Refuse stale source or a build mixed with another attempt.
    raw = base64.b64decode((ROOT / 'release21-source.zip.b64').read_text().strip(), validate=True)
    assert sha(raw) == BASE_SHA256
    original = {}
    modes = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        assert z.testzip() is None
        assert len(z.namelist()) == len(set(z.namelist()))
        for entry in z.infolist():
            name = entry.filename
            p = PurePosixPath(name)
            assert not p.is_absolute() and '..' not in p.parts and '\\' not in name
            assert (entry.external_attr >> 16) & 0o170000 != 0o120000
            if not entry.is_dir():
                original[name] = z.read(name)
                modes[name] = (entry.external_attr >> 16) & 0o777 or 0o644
        manifest = {}
        for line in original['SOURCE-FILES-SHA256SUMS'].decode().splitlines():
            digest, name = line.split('  ', 1)
            assert name not in manifest and sha(original[name]) == digest
            manifest[name] = digest
        assert set(manifest) == set(original) - {'SOURCE-FILES-SHA256SUMS'}
    content = dict(original)
    overlay = ROOT / 'release22/overlay'
    for p in sorted(overlay.rglob('*')):
        if p.is_file() and '__pycache__' not in p.parts:
            name = p.relative_to(overlay).as_posix()
            assert name not in original, 'Overlay unexpectedly replaces baseline file: ' + name
            content[name] = p.read_bytes()
            modes[name] = 0o755 if p.read_bytes().startswith(b'#!') else 0o644
    def edit(name, function):
        content[name] = function(content[name].decode()).encode()
    fw = 'package/luci-app-mango-proxy/root/etc/uci-defaults/95-mango-proxy'
    edit(fw, preserve_defaults)
    wifi = 'package/luci-app-mango-proxy/root/etc/uci-defaults/96-mango-wifi-led'
    edit(wifi, lambda s: s.replace('# Follow the radio', 'uci -q get system.wifi_led >/dev/null && exit 0\n# Follow the radio', 1))
    lang = 'package/luci-app-mango-proxy/root/etc/uci-defaults/97-mango-language'
    edit(lang, lambda s: s.replace('#!/bin/sh\n', '#!/bin/sh\n[ -z "$(uci -q get luci.main.lang)" ] || exit 0\n', 1))
    content['files/etc/mango-release'] = b'22\n'
    prepare_name = 'scripts/prepare.sh'
    edit(prepare_name, lambda s: s.replace('./scripts/feeds install -a\n', './scripts/feeds install -a\npython3 "$kit/scripts/patch-zerotier-init.py" "$PWD/feeds/packages/net/zerotier/files/etc/init.d/zerotier"\n', 1).replace('cp -R "$kit/files" .\n', 'cp -R "$kit/files" .\nchmod +x package/luci-app-mango-proxy/root/etc/hotplug.d/iface/96-mango-zt-direct\n', 1))
    def bump(s):
        for before, after in [('Release 21', 'Release 22'), ("'21'", "'22'"), ('v21.0.0', 'v22.0.0'), ('mt300n-v2-21-', 'mt300n-v2-22-'), ('release21-source.zip.b64', 'release22-source.zip.b64'), ('VALIDATION-21.json', 'VALIDATION-22.json'), ('RELEASE-21.md', 'RELEASE-22.md')]:
            s = s.replace(before, after)
        return s
    edit('scripts/package-release.py', bump)
    edit('scripts/publish-release.py', lambda s: bump(s).replace("'refs/heads/main'", "'refs/heads/codex/mt300n-v2-release22'"))
    edit('tests/test_release_packaging.py', bump)
    edit('scripts/package-release.py', lambda s: s.replace("'KERNEL-PROFILES-20.md']", "'KERNEL-PROFILES-20.md', 'SOURCE-DELTA-22.json']").replace("'build': 'passed',", "'zerotier_direct': read('reports/zt-direct-nft.json'),\n        'zerotier_target': read('reports/zt-direct-target.json'),\n        'build': 'passed',"))
    edit('scripts/publish-release.py', lambda s: s.replace("'KERNEL-PROFILES-20.md'}", "'KERNEL-PROFILES-20.md', 'SOURCE-DELTA-22.json'}"))
    content['RELEASE-22.md'] = (ROOT / 'release22/RELEASE-22.md').read_bytes()
    content['README.md'] = content['RELEASE-22.md']
    validation = json.loads(original['VALIDATION-21.json'])
    validation.update(version='22', date='2026-10-17', base_commit=BASE_COMMIT,
                      artifact_scope='Release 21 plus MT300N-V2 ZeroTier direct UDP/UPnP runtime rules and preservation of existing defaults',
                      hardware_acceptance='Exact Release 22 image not flashed or hardware-accepted by this build',
                      historical_evidence='HARDWARE-EVIDENCE-21.json describes historical Release 21 component evidence only; it is not Release 22 acceptance')
    validation['source_rootfs_sha256'] = {n.split('/root/', 1)[1]: sha(b) for n, b in content.items() if n.startswith('package/luci-app-mango-proxy/root/')}
    content['VALIDATION-22.json'] = (json.dumps(validation, indent=2) + '\n').encode()
    changed = {n: {'before': sha(original[n]), 'after': sha(b)} for n, b in content.items() if n in original and b != original[n] and n != 'SOURCE-FILES-SHA256SUMS'}
    allowed = {fw, wifi, lang, 'README.md', 'files/etc/mango-release', prepare_name, 'scripts/package-release.py', 'scripts/publish-release.py', 'tests/test_release_packaging.py'}
    assert set(changed) == allowed, sorted(changed)
    delta = {'version': '22', 'base_tag': 'v21.0.0', 'base_commit': BASE_COMMIT, 'base_source_sha256': BASE_SHA256,
             'changed_files': changed, 'added_files': {n: sha(b) for n, b in content.items() if n not in original},
             'unchanged_baseline_files': len(original) - len(changed) - 1,
             'proxy_ui_and_runtime': 'Byte-identical to Release 21 except three first-boot defaults guarded to preserve existing settings',
             'new_hardware_acceptance': 'pending; publication does not flash devices',
             'vendored_json': {'upstream': 'https://github.com/rxi/json.lua', 'commit': 'dbf4b2dd2eb7c23be2773c89eb059dadd6436f94', 'license': 'MIT, included in module header', 'sha256': sha(content['package/luci-app-mango-proxy/root/usr/lib/mango/zt-json.lua'])}}
    content['SOURCE-DELTA-22.json'] = (json.dumps(delta, indent=2) + '\n').encode()
    content['SOURCE-FILES-SHA256SUMS'] = ''.join(sha(b) + '  ' + n + '\n' for n, b in sorted(content.items()) if n != 'SOURCE-FILES-SHA256SUMS').encode()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for n, b in sorted(content.items()):
            p = dest / n
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b)
            mode = modes.get(n, 0o644)
            p.chmod(mode)
            info = zipfile.ZipInfo(n, (2026, 10, 17, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (0o100000 | mode) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, b)
    source = buf.getvalue()
    (dest / 'release22-source.zip.b64').write_text(base64.b64encode(source).decode() + '\n')
    if os.environ.get('GITHUB_ENV'):
        with open(os.environ['GITHUB_ENV'], 'a') as f:
            f.write('RELEASE_SOURCE_SHA256=' + sha(source) + '\n')
    print(json.dumps({'source_sha256': sha(source), 'files': len(content), 'baseline_changed': sorted(changed), 'added': sorted(delta['added_files'])}, indent=2))
    return delta


if __name__ == '__main__':
    prepare(Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / 'source22'))
