"""Publish only the already built, checked TR3600 1.0.0 assets at their original commit."""
from pathlib import Path, PurePosixPath
import hashlib, json, os, subprocess, sys, zipfile

ROOT = Path(__file__).resolve().parent
SPEC = json.loads((ROOT / 'release-spec.json').read_text(encoding='utf-8'))
REPO = SPEC['repository']
TAG = SPEC['tag']
COMMIT = SPEC['commit']
OUT = Path('release-assets')


def api(endpoint, *args):
    value = subprocess.check_output(['gh', 'api', f'repos/{REPO}/{endpoint}', *args])
    return json.loads(value) if value else None


def gh(*args):
    return subprocess.run(['gh', *args, '--repo', REPO], check=True)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def check_local_assets():
    assert set(p.name for p in OUT.iterdir()) == set(SPEC['assets']), 'Unexpected or missing release assets'
    for name, expected in SPEC['assets'].items():
        path = OUT / name
        assert path.is_file() and path.stat().st_size == expected['bytes'], name
        assert sha(path.read_bytes()) == expected['sha256'], name
    for row in (OUT / 'SHA256SUMS').read_text(encoding='utf-8').splitlines():
        digest, name = row.split('  ', 1)
        assert digest == sha((OUT / name).read_bytes()), name


def prepare():
    run = api(f'actions/runs/{SPEC["build_run"]}')
    assert run['head_sha'] == COMMIT and run['status'] == 'completed' and run['conclusion'] == 'success'
    assert run['repository']['full_name'] == REPO
    artifact = api(f'actions/artifacts/{SPEC["artifact_id"]}')
    assert artifact['name'] == SPEC['artifact_name'] and not artifact['expired']
    assert artifact['workflow_run']['id'] == SPEC['build_run'] and artifact['workflow_run']['head_sha'] == COMMIT
    assert artifact['digest'] == 'sha256:' + SPEC['artifact_digest']
    archive = Path('original-firmware.zip')
    with archive.open('wb') as stream:
        subprocess.run(['gh', 'api', f'repos/{REPO}/actions/artifacts/{SPEC["artifact_id"]}/zip'], stdout=stream, check=True)
    assert sha(archive.read_bytes()) == SPEC['artifact_digest'], 'Original Actions ZIP digest mismatch'
    OUT.mkdir(exist_ok=False)
    with zipfile.ZipFile(archive) as original:
        assert original.testzip() is None
        names = original.namelist()
        assert len(names) == len(set(names)) == 11
        for name in names:
            path = PurePosixPath(name)
            assert len(path.parts) == 1 and not path.is_absolute() and '..' not in path.parts and '\\' not in name
        verified = set()
        for row in original.read('SHA256SUMS').decode().splitlines():
            digest, name = row.split('  ', 1)
            assert name in names and sha(original.read(name)) == digest, name
            verified.add(name)
        assert verified == set(names) - {'SHA256SUMS'}
        report = json.loads(original.read('tr3600-verification.json'))
        assert report['version'] == 'tr3600-1.0.0' and report['device'] == 'cudy,tr3600-v1'
        assert report['source_commit'] == COMMIT
        mappings = {report['image']: report['image'], 'tr3600-verification.json': 'BUILD-VERIFICATION-1.0.0.json',
                    'tr3600-source.json': 'SOURCE-PROVENANCE-1.0.0.json', 'image-metadata.json': 'IMAGE-METADATA-1.0.0.json'}
        for name, destination in mappings.items():
            (OUT / destination).write_bytes(original.read(name))
    for name in ('RELEASE-1.0.0.txt', 'UPGRADE-1.0.0.txt', 'HARDWARE-ACCEPTANCE-1.0.0.json'):
        (OUT / name).write_bytes((ROOT / name).read_bytes())
    manifest = json.loads((ROOT / 'source-manifest.json').read_text(encoding='utf-8'))
    assert len(manifest) == 137
    actual_tree = subprocess.check_output(['git', 'rev-parse', f'{COMMIT}^{{tree}}']).decode().strip()
    assert actual_tree == SPEC['tree']
    actual = subprocess.check_output(['git', 'ls-tree', '-r', '-z', COMMIT]).split(b'\0')
    entries = {}
    for line in filter(None, actual):
        meta, path = line.split(b'\t', 1)
        mode, kind, oid = meta.decode().split()
        assert kind == 'blob'
        entries[path.decode()] = {'mode': mode, 'sha': oid}
    assert len(entries) == len(manifest)
    assert set(entries) == {e['path'] for e in manifest}
    source_checks = []
    with zipfile.ZipFile(OUT / 'SOURCE-1.0.0.zip', 'w', zipfile.ZIP_STORED) as source:
        for entry in manifest:
            assert entries[entry['path']] == {'mode': entry['mode'], 'sha': entry['sha']}
            data = subprocess.check_output(['git', 'cat-file', 'blob', entry['sha']])
            assert len(data) == entry['size']
            assert hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest() == entry['sha']
            info = zipfile.ZipInfo(entry['path'], date_time=(2026, 10, 7, 0, 0, 0))
            info.create_system = 3
            info.external_attr = int(entry['mode'], 8) << 16
            info.compress_type = zipfile.ZIP_STORED
            source.writestr(info, data)
            source_checks.append(sha(data) + '  ' + entry['path'] + '\n')
        for name, data in [('SOURCE-COMMIT.txt', COMMIT + '\n'), ('SOURCE-FILES-SHA256SUMS', ''.join(source_checks))]:
            info = zipfile.ZipInfo(name, date_time=(2026, 10, 7, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_STORED
            source.writestr(info, data)
    rows = ''.join(sha((OUT / name).read_bytes()) + '  ' + name + '\n' for name in sorted(SPEC['assets']) if name != 'SHA256SUMS')
    (OUT / 'SHA256SUMS').write_text(rows, encoding='utf-8', newline='\n')
    check_local_assets()
    print(json.dumps({'prepared_assets': len(SPEC['assets']), 'source_blobs_verified': len(manifest), 'original_build': SPEC['build_run'], 'firmware_commit': COMMIT}))


def release_by_tag():
    releases = api('releases?per_page=100')
    matches = [r for r in releases if r['tag_name'] == TAG]
    assert len(matches) <= 1
    return matches[0] if matches else None


def verify_uploaded(release):
    actual = {a['name']: a for a in release['assets']}
    assert set(actual) == set(SPEC['assets']), 'Missing or unexpected remote release assets'
    for name, expected in SPEC['assets'].items():
        item = actual[name]
        assert item['state'] == 'uploaded' and item['size'] == expected['bytes'], name
        assert item.get('digest') == 'sha256:' + expected['sha256'], f'Remote digest mismatch: {name}'
    assert release['name'] == SPEC['title']
    assert release['body'].replace('\r\n', '\n').rstrip() == (ROOT / 'RELEASE-1.0.0.txt').read_text(encoding='utf-8').rstrip()
    tag = api(f'git/ref/tags/{TAG}')
    assert tag['object']['type'] == 'commit' and tag['object']['sha'] == COMMIT


def publish():
    check_local_assets()
    references = api(f'git/matching-refs/tags/{TAG}')
    exact = [r for r in references if r['ref'] == f'refs/tags/{TAG}']
    assert len(exact) <= 1
    if exact:
        assert exact[0]['object']['type'] == 'commit' and exact[0]['object']['sha'] == COMMIT, 'Existing release tag is different; never replace it'
    else:
        api('git/refs', '--method', 'POST', '-f', f'ref=refs/tags/{TAG}', '-f', f'sha={COMMIT}')
    release = release_by_tag()
    if release and not release['draft']:
        verify_uploaded(release)
        assert not release['prerelease']
        print('Already published and all digests match: ' + release['html_url'])
        return
    if release is None:
        gh('release', 'create', TAG, '--verify-tag', '--draft', '--target', COMMIT, '--title', SPEC['title'], '--notes-file', str(ROOT / 'RELEASE-1.0.0.txt'), '--latest=false')
        release = release_by_tag()
        assert release and release['draft']
    assert release['name'] == SPEC['title']
    assert release['target_commitish'] == COMMIT or api(f'git/ref/tags/{TAG}')['object']['sha'] == COMMIT
    existing = {a['name']: a for a in release['assets']}
    assert set(existing).issubset(SPEC['assets']), 'Existing draft contains unreviewed assets'
    for name in sorted(SPEC['assets']):
        expected = SPEC['assets'][name]
        if name in existing:
            assert existing[name]['size'] == expected['bytes'] and existing[name].get('digest') == 'sha256:' + expected['sha256'], name
        else:
            gh('release', 'upload', TAG, str(OUT / name))
    release = release_by_tag()
    verify_uploaded(release)
    assert release['draft']
    gh('release', 'edit', TAG, '--draft=false', '--prerelease=false', '--latest=false')
    published = release_by_tag()
    verify_uploaded(published)
    assert not published['draft'] and not published['prerelease']
    record = {'release_id': published['id'], 'release_url': published['html_url'], 'tag': TAG, 'source_commit': COMMIT,
              'draft': published['draft'], 'prerelease': published['prerelease'], 'published_at': published['published_at'],
              'verified_asset_digests': {n: e['sha256'] for n, e in SPEC['assets'].items()}}
    Path('PUBLICATION-VERIFICATION.json').write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(record, ensure_ascii=False))
    if os.getenv('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as summary:
            summary.write(f'Published [{TAG}]({published["html_url"]}) at `{COMMIT}` with {len(SPEC["assets"])} SHA256-verified assets.\n')


if __name__ == '__main__':
    assert REPO == 'liuyong2027/mt300n-v2-openwrt' and COMMIT == 'e298f2b015bc70eac46e0de58204616046cb119f'
    assert TAG == 'tr3600-v1.0.0'
    {'prepare': prepare, 'publish': publish}[sys.argv[1]]()
