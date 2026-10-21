#!/usr/bin/env python3
"""Inspect the compiled target, never install or flash it."""
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import zipfile

root=Path(sys.argv[1]).resolve()
out=root/'trial-artifacts';out.mkdir(exist_ok=True)
reports=root/'reports';reports.mkdir(exist_ok=True)
trees=list((root/'openwrt/build_dir').glob('target-*/root-ramips'))
assert len(trees)==1,'Missing or ambiguous compiled rootfs'
target=trees[0]
manifest=next((root/'openwrt/bin/targets/ramips/mt76x8').glob('*gl-mt300n-v2*.manifest'))
installed={line.split()[0] for line in manifest.read_text().splitlines() if line.strip()}
required={'xray-core','luci-app-ssr-plus','mango-zerotier-support','zerotier','luci-app-zerotier-mini',
'dnsmasq-full','luci-lua-runtime','kmod-nft-tproxy','kmod-nft-socket','shadowsocksr-libev-ssr-check'}
forbidden={'luci-app-mango-proxy','mango-tcpcheck','dnsmasq','v2ray-core','sing-box','mihomo',
'hysteria','tuic-client','trojan','naiveproxy','shadowsocks-rust-sslocal','shadowsocks-libev-ss-local',
'shadowsocksr-libev-ssr-local','shadowsocksr-libev-ssr-redir','v2ray-geoip','v2ray-geosite'}
assert not required-installed,sorted(required-installed)
assert not forbidden&installed,sorted(forbidden&installed)
proof=json.loads((reports/'trial-source.json').read_text())
support=root/'package/mango-zerotier-support/root'
for path,digest in proof['zerotier_source_hashes'].items():
    assert hashlib.sha256((target/path).read_bytes()).hexdigest()==digest,path
for path in ['usr/libexec/ssrplus-migrate','usr/lib/mango/ssr-migration.lua',
'etc/init.d/ssrplus-direct-socks','etc/uci-defaults/99-ssrplus-migrate']:
    assert (target/path).read_bytes()==(support/path).read_bytes(),path
ztinit=(target/'etc/init.d/zerotier').read_text()
assert ztinit.count('/usr/libexec/mango-zt-direct')==3
ssrinit=(target/'etc/init.d/shadowsocksr').read_text()
assert 'GOMEMLIMIT=48MiB' in ssrinit
assert not (target/'etc/init.d/mango_proxy').exists()
assert not (target/'etc/init.d/mango_watchdog').exists()
assert (target/'etc/mango-build-variant').read_text().strip()=='23-ssrplus-trial'
# Parse the firmware's actual SquashFS header and partition limit, not package archive sums.
mk=(root/'openwrt/target/linux/ramips/image/mt76x8.mk').read_text()
device=mk.split('define Device/glinet_gl-mt300n-v2\n',1)[1].split('endef',1)[0]
import re
limit=int(re.search(r'IMAGE_SIZE\s*:=\s*(\d+)k',device)[1])*1024
images=list((root/'openwrt/bin/targets/ramips/mt76x8').glob('*gl-mt300n-v2*sysupgrade.bin'))
entries=[]
for image in images:
    data=image.read_bytes()
    matches=[]
    start=0
    while True:
        pos=data.find(b'hsqs',start)
        if pos<0:break
        start=pos+4
        if pos+96<=len(data) and struct.unpack_from('<HH',data,pos+28)==(4,0):
            matches.append({'offset':pos,'block_size':struct.unpack_from('<I',data,pos+12)[0],
                'compression_id':struct.unpack_from('<H',data,pos+20)[0],
                'squashfs_bytes_used':struct.unpack_from('<Q',data,pos+40)[0]})
    assert len(matches)==1,matches
    assert matches[0]['block_size']==1048576 and matches[0]['compression_id']==4
    remaining=limit-len(data)
    entries.append({'file':image.name,'bytes':len(data),'MiB':len(data)/1048576,
        'sha256':hashlib.sha256(data).hexdigest(),'partition_limit_bytes':limit,
        'remaining_partition_bytes':remaining,'remaining_partition_MiB':remaining/1048576,
        'passes_1MiB_reserve':remaining>=1048576,'squashfs':matches[0]})
    shutil.copy2(image,out/'mt300n-v2-23-ssrplus-trial-sysupgrade.bin')
# Even a successful build may have omitted an oversized image. Preserve the rootfs measurement.
squash=list((root/'openwrt/build_dir').glob('target-*/linux-ramips_mt76x8/root.squashfs'))
result={'variant':'23-ssrplus-trial','firmware_images':entries,
    'capacity_pass':bool(entries) and all(x['passes_1MiB_reserve'] for x in entries),
    'baseline_release22_bytes':14942502,
    'required_packages_present':sorted(required),'other_proxy_cores':[],
    'zerotier_helpers_unchanged':True,'native_ubus_timeout_fix':True,
    'xray_bytes':(target/'usr/bin/xray').stat().st_size,
    'xray_sha256':hashlib.sha256((target/'usr/bin/xray').read_bytes()).hexdigest(),
    'ram_limit':'GOMEMLIMIT=48MiB (soft limit), GOMAXPROCS=1',
    'actual_runtime_ram':'not measured; hardware not flashed',
    'actual_overlay_free_space':'not measured; partition margin is not measured JFFS2 free space',
    'flash_performed':False,'ready_to_flash':False,
    'hardware_acceptance':'pending',
    'root_squashfs_files':[{'name':p.name,'bytes':p.stat().st_size} for p in squash]}
(out/'CAPACITY.json').write_text(json.dumps(result,indent=2)+'\n')
shutil.copy2(manifest,out/'firmware.manifest')
for name in ['resolved.config','trial-source.json','generator-validation.json']:
    if (reports/name).exists():shutil.copy2(reports/name,out/name)
source=out/'mt300n-v2-23-ssrplus-trial-source.zip'
with zipfile.ZipFile(source,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
    for base in ['config','files','package','patches','scripts','tests']:
        for p in sorted((root/base).rglob('*')):
            if p.is_file() and '__pycache__' not in p.parts:
                info=zipfile.ZipInfo(p.relative_to(root).as_posix(),(2026,10,21,0,0,0))
                info.create_system=3
                executable=p.read_bytes().startswith(b'#!')
                info.external_attr=(0o100755 if executable else 0o100644)<<16
                info.compress_type=zipfile.ZIP_DEFLATED
                archive.writestr(info,p.read_bytes())
    for p in sorted(Path(__file__).parent.glob('*')):
        if p.is_file():archive.write(p,'trial/'+p.name)
(out/'SHA256SUMS').write_text(''.join(
    hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n'
    for p in sorted(out.iterdir()) if p.is_file() and p.name!='SHA256SUMS'))
print(json.dumps(result,indent=2))
if not result['capacity_pass']:
    print('Capacity requirement not met: keep artifacts for diagnosis; do not flash.')
    sys.exit(2)
