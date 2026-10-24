"""Fail early on real namespace tests, using the unchanged checked test3 ARM64 core.

Final verification repeats the tests against the new packed image. This step
only avoids a full toolchain rebuild before catching runtime integration bugs.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import zipfile

HERE=Path(__file__).resolve().parent
REPO=HERE.parents[1]
BASELINE_ZIP_SHA='9cc19df4de5b0cb05b6526068f84c3b681d1fc95aec34cc49b2eede9769e91df'
BASELINE_BIN_SHA='e9e9841e5a1326c1e34222a8c73eccd197c88fee7537091727a74e6152a9bcbf'

def run(*args,**kw):return subprocess.run(args,check=True,**kw)
def load(name):
    spec=importlib.util.spec_from_file_location(name,HERE/(name+'.py'))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

archive=REPO/'baseline.zip'
assert hashlib.sha256(archive.read_bytes()).hexdigest()==BASELINE_ZIP_SHA
with tempfile.TemporaryDirectory(prefix='unified-preflight-',dir='/tmp') as tmp:
    tmp=Path(tmp);tmp.chmod(0o755)
    with zipfile.ZipFile(archive) as z:
        image=z.read('cudy-tr3600-v1-ssrplus-1.2.0-test3-sysupgrade.bin')
    assert hashlib.sha256(image).hexdigest()==BASELINE_BIN_SHA
    imagefile=tmp/'baseline.bin';imagefile.write_bytes(image)
    with tarfile.open(imagefile) as t:
        members=[m for m in t if m.isfile() and m.name.endswith('/root')];assert len(members)==1
        squash=tmp/'root.squashfs';squash.write_bytes(t.extractfile(members[0]).read())
    root=tmp/'rootfs'
    run('sudo','unsquashfs','-no-progress','-d',str(root),str(squash))
    run('sudo','chown','-hR',str(os.getuid())+':'+str(os.getgid()),str(root))
    assert (root/'etc/cudy-release').read_text().strip()=='tr3600-ssrplus-1.2.0-test3'
    core_sha=hashlib.sha256((root/'usr/bin/xray').read_bytes()).hexdigest()
    # Build the new runtime exactly as the firmware source preparation does.
    run('python3',str(HERE/'profile.py'))
    fixture=tmp/'fixture';runtime=fixture/'package/luci-app-cudy-ss'
    shutil.copytree(REPO/'tr3600/luci-app-cudy-ss',runtime)
    owned={p.relative_to(runtime/'root') for p in (runtime/'root').rglob('*') if p.is_file()}
    with tarfile.open(REPO/'pinned-ssr.tar.gz') as t:
        prefix='helloworld-'+load('profile').SSR_COMMIT+'/luci-app-ssr-plus/'
        for name in ('luasrc/model/cbi/shadowsocksr/server-config.lua','luasrc/model/cbi/shadowsocksr/server.lua',
            'luasrc/model/cbi/shadowsocksr/status.lua','luasrc/controller/shadowsocksr.lua','root/etc/init.d/shadowsocksr'):
            content=t.extractfile(prefix+name).read()
            p=fixture/'feeds/helloworld/luci-app-ssr-plus'/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(content)
    (fixture/'files/etc/uci-defaults').mkdir(parents=True)
    load('patch-ss-server').patch(fixture);load('unify-ss').patch(fixture)
    run(str(REPO/'.test-venv/bin/python'),str(HERE/'test_unified_ss.py'),'--integration-root',str(fixture))
    for relative in owned:
        if not (runtime/'root'/relative).exists():
            target=root/relative
            if target.is_file():target.unlink()
    shutil.copytree(runtime/'root',root,dirs_exist_ok=True)
    env=os.environ.copy();env.update(LUA_PATH=str(root/'usr/lib/lua/?.lua')+';'+str(root/'usr/lib/lua/?/init.lua'),
        LUA_CPATH=str(root/'usr/lib/lua/?.so'))
    result=run('qemu-aarch64-static','-L',str(root),str(root/'usr/bin/lua'),str(HERE/'test-remove-private.lua'),
        str(root/'usr/lib/cudy-ss/remove-private.lua'),str(tmp/'native-cleanup'),env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    (REPO/'reports/private-ss-deletion-preflight.log').write_text(result.stdout);print(result.stdout,end='')
    assert 'PASS all 5 native private SS deletion cases' in result.stdout
    qemu=json.loads((REPO/'reports/ddns-qemu-build.json').read_text())
    executable=REPO/qemu['executable']
    assert hashlib.sha256(executable.read_bytes()).hexdigest()==qemu['executable_sha256']
    run('python3',str(HERE/'test_unified_ss_packed.py'),'--root',str(root),
        '--report',str(REPO/'reports/unified-ss-preflight.json'),'--qemu',str(executable))
    assert core_sha==hashlib.sha256((root/'usr/bin/xray').read_bytes()).hexdigest()
    (REPO/'reports/preflight-provenance.json').write_text(json.dumps({'baseline_run':39903333246,
        'baseline_artifact':12482494675,'baseline_image_sha256':BASELINE_BIN_SHA,'baseline_xray_sha256':core_sha,
        'runtime_source':'current commit','new_image_verified':False,'router_changed':False},indent=2)+'\n')
