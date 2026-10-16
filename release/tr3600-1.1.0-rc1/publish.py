#!/usr/bin/env python3
"""Publish only a verified prerelease, preserving any conflicting existing tag."""
import hashlib
import json
import os
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request

REPO = 'liuyong2027/mt300n-v2-openwrt'
TAG = 'tr3600-v1.1.0-rc1'
assert os.environ['GITHUB_REPOSITORY'] == REPO
commit = os.environ['GITHUB_SHA']
assert len(commit) == 40 and all(c in '0123456789abcdef' for c in commit)
ASSETS = Path('tr3600-assets')
proof = json.loads((ASSETS / 'tr3600-verification.json').read_text())
assert proof['source_commit'] == commit and proof['version'] == 'tr3600-1.1.0-rc1'
assert proof['webfiles_and_DDNS']['clean_image_private_data_absent']
expected = {}
for line in (ASSETS / 'SHA256SUMS').read_text().splitlines():
    digest, name = line.split('  ', 1)
    assert Path(name).name == name and name not in expected
    path = ASSETS / name
    assert path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == digest, name
    expected[name] = digest
assert set(expected) == {p.name for p in ASSETS.iterdir() if p.is_file()} - {'SHA256SUMS'}
expected['SHA256SUMS'] = hashlib.sha256((ASSETS / 'SHA256SUMS').read_bytes()).hexdigest()

class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, url):
        result = super().redirect_request(request, fp, code, message, headers, url)
        if result and urllib.parse.urlparse(request.full_url).netloc != urllib.parse.urlparse(url).netloc:
            result.remove_header('Authorization')
        return result

opener = urllib.request.build_opener(SafeRedirect)
def request(url, method='GET', value=None, binary=None, accept='application/vnd.github+json'):
    headers = {'Authorization': 'Bearer ' + os.environ['GH_TOKEN'], 'Accept': accept, 'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'Cudy-TR3600-verified-prerelease'}
    data = None
    if value is not None:
        data = json.dumps(value).encode(); headers['Content-Type'] = 'application/json'
    if binary is not None:
        data = binary; headers['Content-Type'] = 'application/octet-stream'
    return opener.open(urllib.request.Request(url, method=method, data=data, headers=headers), timeout=120)

def api(path, method='GET', value=None):
    with request('https://api.github.com/repos/' + REPO + '/' + path, method, value) as response:
        return json.load(response)

try:
    release = api('releases/tags/' + TAG)
    assert release['draft'] and release['target_commitish'] == commit, 'Existing release differs; refusing overwrite'
except urllib.error.HTTPError as error:
    if error.code != 404: raise
    drafts = [item for item in api('releases?per_page=100') if item['tag_name'] == TAG]
    assert len(drafts) <= 1, 'Multiple existing drafts; inspect before retrying'
    if drafts:
        release = drafts[0]
        assert release['draft'] and release['target_commitish'] == commit, 'Existing release differs; refusing overwrite'
    else:
        body = (ASSETS / 'RELEASE-1.1.0-rc1.txt').read_text()
        body += '\n\nSource: `' + commit + '`\nBuild: https://github.com/' + REPO + '/actions/runs/' + os.environ['GITHUB_RUN_ID']
        release = api('releases', 'POST', {'tag_name': TAG, 'target_commitish': commit, 'name': 'Cudy TR3600 V1.0 — 1.1.0-rc1 WebFiles + DDNS', 'body': body, 'draft': True, 'prerelease': True, 'make_latest': 'false'})
upload_url = release['upload_url'].split('{')[0]
assets = {a['name']: a for a in release['assets']}
receipt = {'repository': REPO, 'tag': TAG, 'source_commit': commit, 'release_id': release['id'], 'url': release['html_url'], 'assets': {}, 'published': False, 'automatic_router_flash': False}
for name, digest in sorted(expected.items()):
    path = ASSETS / name
    if name not in assets:
        with request(upload_url + '?name=' + urllib.parse.quote(name), 'POST', binary=path.read_bytes()) as response:
            assets[name] = json.load(response)
    asset = assets[name]
    assert asset['size'] == path.stat().st_size, name
    actual_digest = asset.get('digest')
    if actual_digest != 'sha256:' + digest:
        h = hashlib.sha256()
        with request(asset['url'], accept='application/octet-stream') as response:
            for chunk in iter(lambda: response.read(1024 * 1024), b''):
                h.update(chunk)
        assert h.hexdigest() == digest, 'Uploaded digest mismatch: ' + name
    receipt['assets'][name] = {'sha256': digest, 'bytes': path.stat().st_size, 'url': asset['browser_download_url']}
    Path('PUBLICATION-VERIFICATION-1.1.0-rc1.json').write_text(json.dumps(receipt, indent=2) + '\n')
assert set(assets) == set(expected), 'Unexpected existing draft assets; refusing publication'
try:
    ref = api('git/ref/tags/' + TAG)
    assert ref['object']['type'] == 'commit' and ref['object']['sha'] == commit, 'Tag differs; refusing publication'
except urllib.error.HTTPError as error:
    # GitHub may defer a newly drafted release's tag until publishing.
    if error.code != 404: raise
published = api('releases/' + str(release['id']), 'PATCH', {'draft': False, 'prerelease': True, 'make_latest': 'false'})
ref = api('git/ref/tags/' + TAG)
assert ref['object']['type'] == 'commit' and ref['object']['sha'] == commit
assert not published['draft'] and published['prerelease']
receipt.update(published=True, prerelease=True, url=published['html_url'])
Path('PUBLICATION-VERIFICATION-1.1.0-rc1.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps({'url': receipt['url'], 'source_commit': commit, 'published': True, 'prerelease': True, 'assets_verified': len(receipt['assets'])}, indent=2))
