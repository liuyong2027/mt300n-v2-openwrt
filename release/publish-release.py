#!/usr/bin/env python3
"""Publish only the complete, checksum-verified artifact from this successful run."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

ASSETS = {'mt300n-v2-20-sysupgrade.bin', 'mt300n-v2-20-source.zip',
          'BUILD-VERIFICATION.json', 'HARDWARE-EVIDENCE-20.json', 'RELEASE-20.md'}


def verify_assets(root, commit, run_id):
    names = {p.name for p in root.iterdir() if p.is_file()}
    if names != ASSETS | {'SHA256SUMS'}:
        raise ValueError('Missing or unexpected release assets')
    expected = {}
    for row in (root / 'SHA256SUMS').read_text().splitlines():
        digest, name = row.split('  ', 1)
        if name in expected or name not in ASSETS:
            raise ValueError('Invalid manifest entry')
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != digest:
            raise ValueError('Asset checksum mismatch: ' + name)
        expected[name] = digest
    if set(expected) != ASSETS:
        raise ValueError('Incomplete manifest')
    proof = json.loads((root / 'BUILD-VERIFICATION.json').read_text())
    if proof['version'] != '20' or proof['tag'] != 'v20.0.0' or proof['commit'] != commit or str(proof['run_id']) != str(run_id):
        raise ValueError('Release provenance mismatch')
    if proof['image_sha256'] != expected['mt300n-v2-20-sysupgrade.bin'] or proof['source_sha256'] != expected['mt300n-v2-20-source.zip']:
        raise ValueError('Build proof checksum mismatch')
    if proof['build'] != 'passed' or proof['remaining_partition_bytes'] < 1048576:
        raise ValueError('Build or capacity gate failed')
    return expected


def gh(*args):
    return subprocess.check_output(['gh', *args], text=True)


def main():
    repo = os.environ['GITHUB_REPOSITORY']
    commit = os.environ['GITHUB_SHA']
    if repo != 'liuyong2027/mt300n-v2-openwrt' or os.environ['GITHUB_REF'] != 'refs/heads/main':
        raise ValueError('Unexpected repository/ref')
    root = Path('release-assets')
    expected = verify_assets(root, commit, os.environ['GITHUB_RUN_ID'])
    releases = json.loads(gh('api', f'repos/{repo}/releases?per_page=100'))
    old = [x for x in releases if x['tag_name'] == 'v20.0.0']
    if old:
        if len(old) != 1 or not old[0]['draft'] or old[0]['target_commitish'] != commit:
            raise ValueError('Refusing to replace an existing release or unrelated draft')
        release_id = old[0]['id']
    else:
        gh('release', 'create', 'v20.0.0', '--repo', repo, '--target', commit,
           '--title', 'Release 20 — GL-MT300N-V2', '--notes-file', str(root / 'RELEASE-20.md'), '--draft')
        # Use the REST numeric release ID.
        release_id = next(x['id'] for x in json.loads(gh('api', f'repos/{repo}/releases?per_page=100')) if x['tag_name'] == 'v20.0.0')
    gh('release', 'upload', 'v20.0.0', *[str(p) for p in sorted(root.iterdir()) if p.is_file()], '--repo', repo, '--clobber')
    remote = json.loads(gh('api', f'repos/{repo}/releases/{release_id}'))
    if {a['name'] for a in remote['assets']} != ASSETS | {'SHA256SUMS'}:
        raise ValueError('Remote release asset list differs')
    for asset in remote['assets']:
        local = root / asset['name']
        digest = hashlib.sha256(local.read_bytes()).hexdigest()
        if asset['state'] != 'uploaded' or asset['size'] != local.stat().st_size or asset.get('digest') != 'sha256:' + digest:
            raise ValueError('Remote uploaded asset verification failed: ' + asset['name'])
    gh('release', 'edit', 'v20.0.0', '--repo', repo, '--draft=false', '--prerelease=false', '--latest')
    final = json.loads(gh('api', f'repos/{repo}/releases/{release_id}'))
    if final['draft'] or final['prerelease']:
        raise ValueError('Release publication not confirmed')
    print(final['html_url'])


if __name__ == '__main__':
    main()
