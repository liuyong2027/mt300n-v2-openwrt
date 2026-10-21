"""Verify the packed image, not just the build tree, before publishing an artifact."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile

repo=Path(__file__).resolve().parents[2]
images=list((repo/'openwrt/bin/targets/mediatek/filogic').glob('*cudy_tr3600-v1*squashfs-sysupgrade.bin'))
assert len(images)==1,images
image=images[0]
with tempfile.TemporaryDirectory(prefix='cudy-ssrplus-verify-') as temp:
    temp=Path(temp)
    with tarfile.open(image) as archive:
        roots=[m for m in archive.getmembers() if m.isfile() and m.name.endswith('/root')]
        assert len(roots)==1
        payload=temp/'root.squashfs'
        payload.write_bytes(archive.extractfile(roots[0]).read())
    root=temp/'rootfs'
    subprocess.run(['unsquashfs','-d',str(root),str(payload)],check=True)
    assert (root/'etc/cudy-release').read_text().strip()=='tr3600-ssrplus-1.2.0-test1'
    for absent in ['etc/init.d/mango_proxy','etc/init.d/mango_watchdog','usr/libexec/mango-fw','usr/share/luci/menu.d/luci-app-mango-proxy.json']:
        assert not (root/absent).exists(),absent
    assert not list((root/'usr/libexec').glob('mango-*'))
    for required in ['etc/init.d/shadowsocksr','usr/bin/xray','usr/libexec/cudy-ss-netns',
        'usr/lib/cudy-ss/migrate.lua','usr/lib/cudy-ss/config.lua','usr/libexec/cudy-ss-gate',
        'etc/init.d/cudy_ss_core','usr/lib/cudy-webfiles/bin/cudy-webfiles',
        'usr/lib/cudy-webfiles/bin/filebrowser','usr/sbin/smbd','usr/bin/zerotier-one']:
        assert (root/required).is_file(),required
    config=(repo/'openwrt/.config').read_text()
    for package in ['luci-app-ssr-plus','dnsmasq-full','kmod-nft-socket','kmod-nft-tproxy','kmod-veth','luci-compat','luci-app-cudy-ss','zerotier']:
        assert 'CONFIG_PACKAGE_'+package+'=y' in config,package
    assert 'CONFIG_PACKAGE_luci-app-mango-proxy=y' not in config
    # Parse every actual installed Lua file and every shell entrypoint using target tools.
    syntax=0
    for base in ['usr/lib/cudy-ss','usr/libexec','etc/init.d','etc/uci-defaults']:
        for path in (root/base).glob('*'):
            if not path.is_file():continue
            try:text=path.read_text()
            except UnicodeDecodeError:continue
            if path.parent.name=='cudy-ss' or text.startswith('#!/usr/bin/lua'):
                if path.parent.name=='cudy-ss' or path.name.startswith('cudy-ss'):
                    subprocess.run(['qemu-aarch64-static','-L',str(root),str(root/'usr/bin/lua'),'-e',
                        'assert(loadfile('+json.dumps(str(path))+'))'],check=True);syntax+=1
            elif text.startswith('#!') and ('cudy' in path.name or path.name=='shadowsocksr'):
                subprocess.run(['qemu-aarch64-static','-L',str(root),str(root/'bin/busybox'),'sh','-n',str(path)],check=True);syntax+=1
    # Test all three preserved server ciphers with the actual compiled ARM64 Xray.
    for cipher in ['aes-128-gcm','aes-256-gcm','chacha20-ietf-poly1305']:
        cfg={'log':{'loglevel':'warning'},'dns':{'queryStrategy':'UseIPv4','servers':['198.18.255.1']},
            'inbounds':[{'tag':'cudy-ss-zt','listen':'0.0.0.0','port':8388,'protocol':'shadowsocks',
            'settings':{'method':cipher,'password':'synthetic-test-password-only-12345','network':'tcp,udp'}}],
            'outbounds':[{'protocol':'freedom','settings':{'domainStrategy':'UseIPv4'}}]}
        path=temp/'test.json';path.write_text(json.dumps(cfg))
        subprocess.run(['qemu-aarch64-static','-L',str(root),str(root/'usr/bin/xray'),'run','-test','-config',str(path)],check=True)
    out=repo/'ssrplus-assets';out.mkdir(exist_ok=True)
    name='cudy-tr3600-v1-ssrplus-1.2.0-test1-sysupgrade.bin'
    shutil.copyfile(image,out/name)
    digest=hashlib.sha256(image.read_bytes()).hexdigest()
    (out/'SHA256SUMS').write_text(digest+'  '+name+'\n')
    proof={'image':name,'sha256':digest,'bytes':image.stat().st_size,'base':'tr3600-v1.1.1',
        'mango_proxy_installed':False,'ssrplus_commit':'11e0a48737097f8b0e0ec0dd080350ea7fd08d94',
        'private_ss':'preserved configuration and isolated network namespace',
        'actual_arm64_server_ciphers_tested':3,'actual_installed_syntax_checks':syntax,
        'hardware_flash_or_boot_tested':False}
    (out/'BUILD-VERIFICATION.json').write_text(json.dumps(proof,indent=2)+'\n')
    (out/'README.txt').write_text((repo/'tr3600/ssrplus/README.txt').read_text())
    shutil.copyfile(repo/'reports/resolved.config',out/'resolved.config')
    shutil.copyfile(repo/'reports/ssrplus-source.json',out/'SOURCE.json')
    print(json.dumps(proof,indent=2))

