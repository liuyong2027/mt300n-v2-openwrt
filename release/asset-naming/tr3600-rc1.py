#!/usr/bin/env python3
"""Correct the download name; keep the already tested firmware bytes and tag."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import urllib.parse
import urllib.request

REPO = 'liuyong2027/mt300n-v2-openwrt'
TAG = 'tr3600-v1.1.0-rc1'
BUILD = 'ad2f821a69a86ba7edf8e2f631e5e6dba279d7fb'
RUN = 38902566288
OLD = 'openwrt-mediatek-filogic-cudy_tr3600-v1-squashfs-sysupgrade.bin'
NEW = 'cudy-tr3600-v1-1.1.0-rc1-sysupgrade.bin'
IMAGE_SHA = '56ab6eda573eb5e873b679a2d8c5992a8a7a549b958f5b18798e20f2fb18e7f5'
SUM_SHA = '6e488b3692d70244966bf4063d36e897777065258b44b3b37d61bca6a41d2fc5'
assert os.environ['GITHUB_REPOSITORY'] == REPO


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, url):
        result = super().redirect_request(request, fp, code, message, headers, url)
        if result and urllib.parse.urlparse(request.full_url).netloc != urllib.parse.urlparse(url).netloc:
            result.remove_header('Authorization')
        return result


opener = urllib.request.build_opener(SafeRedirect)


def request(url, method='GET', value=None, binary=None):
    headers = {'Authorization': 'Bearer ' + os.environ['GH_TOKEN'], 'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'TR3600-versioned-download-name'}
    data = None
    if value is not None:
        data = json.dumps(value).encode(); headers['Content-Type'] = 'application/json'
    if binary is not None:
        data = binary; headers['Content-Type'] = 'application/octet-stream'
    with opener.open(urllib.request.Request(url, method=method, data=data, headers=headers), timeout=120) as response:
        raw = response.read()
        return json.loads(raw) if raw else None


def api(path, method='GET', value=None):
    return request('https://api.github.com/repos/' + REPO + '/' + path, method, value)


original = Path('original')
assert digest(original / 'SHA256SUMS') == SUM_SHA
old_hashes = {}
for line in (original / 'SHA256SUMS').read_text().splitlines():
    sha, name = line.split('  ', 1)
    assert Path(name).name == name and name not in old_hashes
    assert digest(original / name) == sha, name
    old_hashes[name] = sha
old_hashes['SHA256SUMS'] = SUM_SHA
assert len(old_hashes) == 17 and old_hashes[OLD] == IMAGE_SHA
proof = json.loads((original / 'tr3600-verification.json').read_text())
assert proof['source_commit'] == BUILD and proof['image'] == OLD and proof['image_sha256'] == IMAGE_SHA
assert proof['webfiles_and_DDNS']['clean_image_private_data_absent']
proof['image'] = NEW
proof['download_name_correction'] = {'original_name': OLD, 'binary_unchanged': True, 'metadata_commit': os.environ['GITHUB_SHA']}
changed = Path('changed'); changed.mkdir(exist_ok=True)
(changed / 'tr3600-verification.json').write_text(json.dumps(proof, indent=2) + '\n')
new_hashes = {NEW if name == OLD else name: sha for name, sha in old_hashes.items() if name != 'SHA256SUMS'}
new_hashes['tr3600-verification.json'] = digest(changed / 'tr3600-verification.json')
(changed / 'SHA256SUMS').write_text(''.join(sha + '  ' + name + '\n' for name, sha in sorted(new_hashes.items())))
new_hashes['SHA256SUMS'] = digest(changed / 'SHA256SUMS')
run = api('actions/runs/' + str(RUN))
assert run['head_sha'] == BUILD and run['conclusion'] == 'success'
ref = api('git/ref/tags/' + TAG)
assert ref['object']['type'] == 'commit' and ref['object']['sha'] == BUILD
release = api('releases/tags/' + TAG)
assert release['prerelease'] and not release['draft'] and release['target_commitish'] == BUILD
assets = {a['name']: a for a in release['assets']}
assert len(assets) == len(release['assets']) == 17
assert set(assets) in (set(old_hashes), set(new_hashes))
for name, item in assets.items():
    expected = {old_hashes.get(name), new_hashes.get(name)} - {None}
    assert item['state'] == 'uploaded' and item['digest'].removeprefix('sha256:') in expected, name

if sys.argv[1] == 'prepare':
    backup = Path('backup'); backup.mkdir(exist_ok=True)
    (backup / 'release-before-name-correction.json').write_text(json.dumps(release, indent=2) + '\n')
    for name in ('SHA256SUMS', 'tr3600-verification.json'):
        shutil.copyfile(original / name, backup / name)
    print(json.dumps({'prepared': True, 'binarySHA256Unchanged': IMAGE_SHA, 'newName': NEW}))
    sys.exit(0)

assert sys.argv[1] == 'apply' and os.environ['BACKUP_ARTIFACT_ID'].isdigit()
if OLD in assets:
    item = assets[OLD]
    assert item['digest'] == 'sha256:' + IMAGE_SHA and item['size'] == (original / OLD).stat().st_size
    updated = api('releases/assets/' + str(item['id']), 'PATCH', {'name': NEW, 'label': 'TR3600 V1.0 / R126 — 1.1.0-rc1 sysupgrade'})
    assert updated['name'] == NEW and updated['digest'] == 'sha256:' + IMAGE_SHA
upload = release['upload_url'].split('{')[0]
for name in ('tr3600-verification.json', 'SHA256SUMS'):
    item = {a['name']: a for a in api('releases/' + str(release['id']))['assets']}.get(name)
    if item and item['digest'] == 'sha256:' + new_hashes[name]:
        continue
    if item:
        assert item['digest'] == 'sha256:' + old_hashes[name], name
        api('releases/assets/' + str(item['id']), 'DELETE')
    uploaded = request(upload + '?name=' + urllib.parse.quote(name), 'POST', binary=(changed / name).read_bytes())
    assert uploaded['digest'] == 'sha256:' + new_hashes[name]
marker = '下载文件名已加入版本号'
if marker not in release['body']:
    link = 'https://github.com/' + REPO + '/releases/download/' + TAG + '/' + NEW
    body = '固件下载：[' + NEW + '](' + link + ')\n\n' + marker + '；固件二进制内容及 SHA256 保持不变，相关校验清单已同步更新。\n\n' + release['body']
    api('releases/' + str(release['id']), 'PATCH', {'body': body, 'prerelease': True, 'make_latest': 'false'})
final = api('releases/' + str(release['id']))
assert final['prerelease'] and not final['draft'] and final['target_commitish'] == BUILD
assert {a['name']: a['digest'].removeprefix('sha256:') for a in final['assets']} == new_hashes
assert api('git/ref/tags/' + TAG)['object']['sha'] == BUILD
receipt = {'releaseUrl': final['html_url'], 'imageBuildSourceCommit': BUILD, 'metadataCommit': os.environ['GITHUB_SHA'], 'metadataRunId': os.environ['GITHUB_RUN_ID'], 'backupArtifactId': os.environ['BACKUP_ARTIFACT_ID'], 'originalName': OLD, 'name': NEW, 'imageSHA256': IMAGE_SHA, 'binaryBytesChanged': False, 'assets': new_hashes, 'complete': True}
Path('FILENAME-CORRECTION-VERIFICATION.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps({'complete': True, 'name': NEW, 'imageSHA256': IMAGE_SHA}))
