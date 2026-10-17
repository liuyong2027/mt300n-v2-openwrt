"""Withdraw reviewed RC releases reversibly; retain build-reference assets and tags."""
import hashlib,json,os,subprocess,sys,time,urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parent
APPROVAL=json.loads((ROOT/'approved-inventory.json').read_text())
assert os.environ['GITHUB_REPOSITORY']==APPROVAL['repository']=='liuyong2027/mt300n-v2-openwrt'
assert os.environ['GITHUB_REF']=='refs/heads/codex/tr3600-archive-prereleases-20261017'
BASE='https://api.github.com/repos/'+APPROVAL['repository']
TOKEN=os.environ['GH_TOKEN']
def api(path,body=None,auth=True):
    headers={'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28','User-Agent':'TR3600-prerelease-retirement'}
    if auth: headers['Authorization']='Bearer '+TOKEN
    if body is not None: headers['Content-Type']='application/json'
    req=urllib.request.Request(BASE+path,data=json.dumps(body).encode() if body is not None else None,headers=headers,method='PATCH' if body is not None else 'GET')
    with urllib.request.urlopen(req,timeout=60) as res:return json.load(res)

def shape(r):
    out={k:r[k] for k in ('id','tag_name','target_commitish','name','body','draft','prerelease')}
    out['assets']=sorted([{k:a[k] for k in ('id','name','size','digest')} for a in r['assets']],key=lambda a:a['name'])
    return out

def unchanged_assets(r,expected):
    got=shape(r); ref={k:v for k,v in expected.items() if k!='tagRef'}
    got.pop('draft');got.pop('prerelease');ref.pop('draft');ref.pop('prerelease')
    assert got==ref,expected['tag_name']

def stable_unchanged():
    for expected in APPROVAL['otherPublished']:
        assert shape(api('/releases/'+str(expected['id'])))==expected,expected['tag_name']
    return True

def tags_unchanged():
    for expected in APPROVAL['targets']:
        obj=api('/git/ref/tags/'+expected['tag_name'])['object']
        assert obj==expected['tagRef'],expected['tag_name']

mode=sys.argv[1]
result={'mode':mode,'repository':APPROVAL['repository'],'runId':os.environ['GITHUB_RUN_ID'],'sourceCommit':os.environ['GITHUB_SHA'],'releases':[]}
try:
    if mode=='withdraw':
        stable_unchanged();tags_unchanged()
        # Complete preflight for all three before the first mutation.
        for expected in APPROVAL['targets']:
            r=api('/releases/'+str(expected['id']));unchanged_assets(r,expected)
            assert (r['draft'] is False and r['prerelease'] is True) or (r['draft'] is True and r['prerelease'] is False)
        for expected in APPROVAL['targets']:
            r=api('/releases/'+str(expected['id']),{'draft':True,'prerelease':False})
            unchanged_assets(r,expected);assert r['draft'] is True and r['prerelease'] is False
            result['releases'].append({'id':r['id'],'tag':r['tag_name'],'draft':True,'prerelease':False,'assetCount':len(r['assets'])})
        stable_unchanged();tags_unchanged()
    elif mode=='verify':
        # This mode is run with contents:read, matching the old build jobs.
        stable_unchanged();tags_unchanged()
        for expected in APPROVAL['targets']:
            r=api('/releases/tags/'+expected['tag_name']);unchanged_assets(r,expected)
            assert r['draft'] is True and r['prerelease'] is False
            images=[a for a in expected['assets'] if a['name'].endswith('.bin')]
            assert len(images)==1
            image=images[0];dest=Path('reference-downloads')/expected['tag_name'];dest.mkdir(parents=True,exist_ok=True)
            subprocess.run(['gh','release','download',expected['tag_name'],'--repo',APPROVAL['repository'],'--pattern',image['name'],'--dir',str(dest)],check=True,timeout=180)
            data=(dest/image['name']).read_bytes()
            assert len(data)==image['size'] and 'sha256:'+hashlib.sha256(data).hexdigest()==image['digest']
            result['releases'].append({'id':r['id'],'tag':r['tag_name'],'draft':True,'prerelease':False,'assetsUnchanged':True,'authenticatedReadOnlyBuildDownloadAndSHA256Verified':True})
        visible=api('/releases?per_page=100',auth=False)
        assert not any(r['tag_name'] in {e['tag_name'] for e in APPROVAL['targets']} for r in visible)
        assert not any(r['prerelease'] for r in visible)
        assert {r['id'] for r in visible}=={r['id'] for r in APPROVAL['otherPublished']}
        result['publicReleaseTags']=[r['tag_name'] for r in visible]
        result['publicPrereleaseCount']=0
        stable_unchanged()
    elif mode=='restore':
        # A failed withdrawal or read-only dependency check restores only our exact RC targets.
        for expected in APPROVAL['targets']:
            r=api('/releases/'+str(expected['id']));unchanged_assets(r,expected)
            if r['draft'] is True and r['prerelease'] is False:
                r=api('/releases/'+str(expected['id']),{'draft':False,'prerelease':True})
            assert r['draft'] is False and r['prerelease'] is True
            result['releases'].append({'id':r['id'],'tag':r['tag_name'],'restored':True})
        stable_unchanged();tags_unchanged()
    else: raise ValueError('Unexpected mode')
    result['success']=True
finally:
    Path('retirement-'+mode+'.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
