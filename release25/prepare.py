#!/usr/bin/env python3
"""Reconstruct Release 24, then add the IKEv2 client overlay for Release 25."""
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
BASE_COMMIT = 'f122db1356302fd760f7b41d4fcb8eb09da7c309'
BASE_SHA256 = 'e3de229a1859330f7545e2ed606e6a75e3737bd61705ca80025fb3e2a0df8045'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def bump(text):
    for old, new in [
        ('Release 24', 'Release 25'), ("'24'", "'25'"), ('v24.0.0', 'v25.0.0'),
        ('mt300n-v2-24-', 'mt300n-v2-25-'), ('release24-source.zip.b64', 'release25-source.zip.b64'),
        ('VALIDATION-24.json', 'VALIDATION-25.json'), ('RELEASE-24.md', 'RELEASE-25.md'),
        ('SOURCE-DELTA-24.json', 'SOURCE-DELTA-25.json'),
        ('codex/mt300n-v2-release24', 'codex/mt300n-v2-release25'),
        ('DEVICE-MEMORY-EVIDENCE-24.json', 'DEVICE-MEMORY-EVIDENCE-24.json'),
    ]:
        text = text.replace(old, new)
    return text


def prepare(dest):
    spec = importlib.util.spec_from_file_location('release24_base', ROOT / 'release24/prepare.py')
    baseline = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(baseline)
    baseline.prepare(dest)
    raw = base64.b64decode((dest / 'release24-source.zip.b64').read_text().strip(), validate=True)
    assert sha(raw) == BASE_SHA256, 'Release 24 recipe changed'
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert archive.testzip() is None
        original = {p.filename: archive.read(p) for p in archive.infolist()}
        modes = {p.filename: (p.external_attr >> 16) & 0o777 for p in archive.infolist()}
    content = dict(original)
    overlay = ROOT / 'release25/overlay'
    for path in sorted(overlay.rglob('*')):
        if path.is_file() and '__pycache__' not in path.parts:
            name = path.relative_to(overlay).as_posix()
            content[name] = path.read_bytes()
            modes[name] = modes.get(name, 0o755 if content[name].startswith(b'#!') else 0o644)

    def edit(name, function):
        content[name] = function(content[name].decode()).encode()

    for name in [
        'scripts/package-release.py', 'scripts/publish-release.py',
        'tests/test_release_packaging.py', 'tests/test_publish_draft_response.py',
    ]:
        if name in content:
            edit(name, bump)

    content['files/etc/mango-release'] = b'25\n'
    content['RELEASE-25.md'] = (ROOT / 'release25/RELEASE-25.md').read_bytes()
    content['README.md'] = content['RELEASE-25.md']

    # Keep Release 24 memory evidence as historical attachment.
    if 'DEVICE-MEMORY-EVIDENCE-24.json' in original:
        content['DEVICE-MEMORY-EVIDENCE-24.json'] = original['DEVICE-MEMORY-EVIDENCE-24.json']

    validation = json.loads(original.get('VALIDATION-24.json', original.get('VALIDATION-23.json', b'{}')))
    validation.update(
        version='25',
        date='2026-10-31',
        base_commit=BASE_COMMIT,
        artifact_scope='Release 24 plus IKEv2 client build profile with China IP split; Xray standard profile preserved',
        hardware_acceptance='pending; ikev2 image requires separate flash validation',
        historical_evidence='DEVICE-MEMORY-EVIDENCE-24.json',
    )
    validation['source_rootfs_sha256'] = {
        n.split('/root/', 1)[1]: sha(b)
        for n, b in content.items()
        if n.startswith('package/luci-app-mango-ikev2/root/')
    }
    content['VALIDATION-25.json'] = (json.dumps(validation, indent=2) + '\n').encode()

    changed = {
        n: {'before': sha(original[n]), 'after': sha(b)}
        for n, b in content.items()
        if n in original and original[n] != b and n != 'SOURCE-FILES-SHA256SUMS'
    }
    added = {n: sha(b) for n, b in content.items() if n not in original}
    required_added = {
        'package/luci-app-mango-ikev2/Makefile',
        'package/luci-app-mango-ikev2/root/etc/config/mango_ikev2',
        'package/luci-app-mango-ikev2/root/etc/init.d/mango_ikev2',
        'package/luci-app-mango-ikev2/root/usr/lib/mango-ikev2/model.lua',
        'config/mt300n-v2-ikev2.config',
        'tests/test_ikev2_model.sh',
    }
    missing = sorted(p for p in required_added if p not in added and p not in changed)
    assert not missing, missing

    delta = {
        'version': '25',
        'base_tag': 'v24.0.0',
        'base_commit': BASE_COMMIT,
        'base_source_sha256': BASE_SHA256,
        'changed_files': changed,
        'added_files': added,
        'unchanged_baseline_files': len(original) - len(changed),
        'runtime_change': 'Optional IKEv2 client image profile with China split; standard Xray profile unchanged',
        'flash_note': 'IKEv2 and Xray are mutually exclusive on 16MiB flash',
        'new_full_image_hardware_acceptance': 'pending',
    }
    content['SOURCE-DELTA-25.json'] = (json.dumps(delta, indent=2) + '\n').encode()
    content['SOURCE-FILES-SHA256SUMS'] = ''.join(
        sha(b) + '  ' + n + '\n' for n, b in sorted(content.items()) if n != 'SOURCE-FILES-SHA256SUMS'
    ).encode()

    (dest / 'release24-source.zip.b64').unlink(missing_ok=True)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(content.items()):
            path = dest / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            mode = modes.get(name, 0o755 if data.startswith(b'#!') else 0o644)
            path.chmod(mode)
            entry = zipfile.ZipInfo(name, (2026, 10, 31, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = (0o100000 | mode) << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, data)
    source = buffer.getvalue()
    (dest / 'release25-source.zip.b64').write_text(base64.b64encode(source).decode() + '\n')
    if os.environ.get('GITHUB_ENV'):
        with open(os.environ['GITHUB_ENV'], 'a') as env:
            env.write('RELEASE_SOURCE_SHA256=' + sha(source) + '\n')
    print(json.dumps({
        'source_sha256': sha(source),
        'changed': sorted(changed),
        'added': sorted(added),
    }, indent=2))
    return delta


if __name__ == '__main__':
    prepare(Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / 'source25'))
