#!/usr/bin/env python3
"""Publish the exact verified R27 image, then remove the superseded release."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

REPO = 'liuyong2027/mt300n-v2-openwrt'
SOURCE = '2ba098ddff1b044c5bb0d7b23975c8a9135a42fc'
RUN = '42957607849'
TAG = 'v27.0.0'
RELEASE_ID = 441333797
OLD_ID = 440396907
OLD_SOURCE = 'f1c0443a0af392f8437b091b8b484a62a8281901'
OLD_IMAGE_SHA = '0cc4fcebfbaff7158351089d78e7dc25bd19b580aad3aface4bc5e806559a600'
IMAGE_SHA = '87088be86581dee5a9427fe226a00d12b3d5909f98c1723232883cc4b6ce6f6e'
IMAGE = 'mt300n-v2-r27-recovery-2ba098d-sysupgrade.bin'
ROOT = Path(__file__).resolve().parents[2]
DOCS = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def gh(*args):
    return subprocess.check_output(['gh', *map(str, args)], text=True)


def api(path):
    return json.loads(gh('api', f'repos/{REPO}/{path}'))


def optional_api(path):
    result = subprocess.run(['gh', 'api', f'repos/{REPO}/{path}'],
                            text=True, capture_output=True)
    if result.returncode == 0:
        return json.loads(result.stdout)
    if '(HTTP 404)' in result.stderr:
        return None
    raise RuntimeError(result.stderr)


def unique(directory, name):
    paths = list(directory.rglob(name))
    assert len(paths) == 1, (name, paths)
    return paths[0]


def prepare(artifact, out):
    report = json.loads(unique(artifact, 'firmware-format.json').read_text())
    image = unique(artifact, report['image'])
    assert digest(image) == report['sha256'] == IMAGE_SHA
    assert image.stat().st_size == report['image_bytes'] == 9896230
    assert report['margin_bytes'] == report['image_limit_bytes'] - image.stat().st_size >= 1048576
    assert (report['version'], report['profile'], report['kernel_profile']) == ('27', 'ikev2', 'production')
    assert unique(artifact, 'openwrt-commit.txt').read_text().strip() == 'f0a60eee2fe051741c643ea6118718aae1ef17fb'
    overlay = ROOT / 'release27/overlay/package/luci-app-mango-ikev2/root'
    files = {str(p.relative_to(overlay)): digest(p) for p in overlay.rglob('*') if p.is_file()}
    assert files == report['packaged_fixes_sha256'] and len(files) == 10
    notes = unique(artifact, 'RELEASE-27.md')
    assert notes.read_bytes() == (ROOT / 'release27/RELEASE-27.md').read_bytes()
    out.mkdir()
    shutil.copyfile(image, out / IMAGE)
    for name in ['firmware-format.json', 'SOURCE-DELTA-27.json', 'RELEASE-27.md']:
        shutil.copyfile(unique(artifact, name), out / name)
    for name in ['BUILD-VERIFICATION-27.json', 'HARDWARE-ACCEPTANCE-27.json']:
        shutil.copyfile(DOCS / name, out / name)
    (out / 'SHA256SUMS').write_text(''.join(
        f'{digest(p)}  {p.name}\n' for p in sorted(out.iterdir())))
    return {p.name: (p.stat().st_size, 'sha256:' + digest(p)) for p in out.iterdir()}


def check_release(release, expected, *, complete):
    assert release['id'] == RELEASE_ID
    assert release['tag_name'] == TAG and release['target_commitish'] == SOURCE
    assert release['body'] == (DOCS / 'release-notes.md').read_text()
    assets = {a['name']: a for a in release['assets']}
    assert set(assets) <= set(expected), 'Unexpected release asset; refusing to overwrite'
    if complete:
        assert set(assets) == set(expected), 'Incomplete release assets'
    for name, asset in assets.items():
        assert (asset['size'], asset['digest']) == expected[name], name
        assert asset['state'] == 'uploaded', name
    return assets


def publish(out, expected):
    release = api(f'releases/{RELEASE_ID}')
    assets = check_release(release, expected, complete=False)
    tag = optional_api(f'git/ref/tags/{TAG}')
    if tag:
        assert tag['object']['type'] == 'commit' and tag['object']['sha'] == SOURCE
    missing = [out / name for name in sorted(expected) if name not in assets]
    if missing:
        # A partially uploaded matching draft can resume; never clobber assets.
        assert release['draft'], 'Refusing to upload into an already published release'
        gh('release', 'upload', TAG, '--repo', REPO, *missing)
    check_release(api(f'releases/{RELEASE_ID}'), expected, complete=True)
    gh('release', 'edit', TAG, '--repo', REPO, '--draft=false', '--prerelease=false',
       '--latest', '--target', SOURCE)
    release = api(f'releases/{RELEASE_ID}')
    check_release(release, expected, complete=True)
    assert not release['draft'] and not release['prerelease']
    tag = api(f'git/ref/tags/{TAG}')
    assert tag['object']['type'] == 'commit' and tag['object']['sha'] == SOURCE
    assert api('releases/latest')['id'] == RELEASE_ID

    # Delete only the explicitly superseded release after the replacement is
    # public and every uploaded asset matches. Keep the historical source tag.
    old = optional_api(f'releases/{OLD_ID}')
    if old:
        assert old['tag_name'] == 'v27.0.1' and old['target_commitish'] == OLD_SOURCE
        old_images = [a for a in old['assets'] if a['name'].endswith('.bin')]
        assert len(old_images) == 1 and old_images[0]['digest'] == 'sha256:' + OLD_IMAGE_SHA
        gh('api', '--method', 'DELETE', f'repos/{REPO}/releases/{OLD_ID}')
    assert optional_api('releases/tags/v27.0.1') is None
    old_tag = api('git/ref/tags/v27.0.1')
    assert old_tag['object']['sha'] == OLD_SOURCE
    assert api('releases/latest')['id'] == RELEASE_ID
    print(json.dumps({'published': release['html_url'], 'source': SOURCE,
                      'sha256': IMAGE_SHA, 'verified_assets': len(expected),
                      'deleted_release': 'v27.0.1', 'historical_tag_preserved': True}))
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as f:
            f.write(f'Published [Release 27]({release["html_url"]}) with {len(expected)} verified assets.\n\n')
            f.write(f'Image SHA256: `{IMAGE_SHA}`. Removed old v27.0.1 release; retained its source tag.\n')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--artifact-dir', type=Path)
    args = parser.parse_args()
    if not args.prepare_only:
        assert os.environ.get('GITHUB_REPOSITORY') == REPO
        run = json.loads(gh('run', 'view', RUN, '--repo', REPO, '--json', 'headSha,conclusion'))
        assert run['headSha'] == SOURCE and run['conclusion'] == 'success'
    with tempfile.TemporaryDirectory() as temp:
        temp = Path(temp)
        artifact = args.artifact_dir
        if artifact is None:
            assert not args.prepare_only, '--prepare-only requires --artifact-dir'
            artifact = temp / 'artifact'
            gh('run', 'download', RUN, '--repo', REPO, '--name', '27-ikev2-image-10', '--dir', artifact)
        out = temp / 'assets'
        expected = prepare(artifact, out)
        print(json.dumps({'prepared_assets': expected}, indent=2), flush=True)
        if not args.prepare_only:
            publish(out, expected)


if __name__ == '__main__':
    main()
