"""Verify the packed image, not just the build tree, before publishing an artifact."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import struct
import tarfile
import tempfile

repo=Path(__file__).resolve().parents[2]
source=json.loads((repo/'reports/ssrplus-source.json').read_text())
assert source['xray_version']=='26.10.21',source
images=list((repo/'openwrt/bin/targets/mediatek/filogic').glob('*cudy_tr3600-v1*squashfs-sysupgrade.bin'))
assert len(images)==1,images
image=images[0]
assert image.stat().st_size < 237824*1024
with tempfile.TemporaryDirectory(prefix='cudy-ssrplus-verify-',dir='/tmp') as temp:
    temp=Path(temp)
    with tarfile.open(image) as archive:
        roots=[m for m in archive.getmembers() if m.isfile() and m.name.endswith('/root')]
        assert len(roots)==1
        kernels=[m for m in archive.getmembers() if m.isfile() and m.name.endswith('/kernel')]
        assert len(kernels)==1
        assert archive.extractfile(kernels[0]).read(4)==bytes.fromhex('d00dfeed')
        payload=temp/'root.squashfs'
        payload.write_bytes(archive.extractfile(roots[0]).read())
        header=payload.read_bytes()[:96]
        assert header[:4]==b'hsqs' and struct.unpack_from('<I',header,12)[0]==1048576
        assert struct.unpack_from('<H',header,20)[0]==4
    root=temp/'rootfs'
    subprocess.run(['sudo','unsquashfs','-no-progress','-d',str(root),str(payload)],check=True)
    subprocess.run(['sudo','chown','-hR',str(os.getuid())+':'+str(os.getgid()),str(root)],check=True)
    assert (root/'etc/cudy-release').read_text().strip()=='tr3600-ssrplus-1.2.0-test3'
    for absent in ['etc/init.d/mango_proxy','etc/init.d/mango_watchdog','usr/libexec/mango-fw',
        'usr/share/luci/menu.d/luci-app-mango-proxy.json',
        'usr/share/luci/menu.d/luci-app-cudy-ss.json','usr/libexec/rpcd/cudy.ss',
        'usr/share/rpcd/acl.d/luci-app-cudy-ss.json','usr/libexec/cudy-ss-worker',
        'www/luci-static/resources/view/cudy-ss.js']:
        assert not (root/absent).exists(),absent
    assert not list((root/'usr/libexec').glob('mango-*'))
    for required in ['etc/init.d/shadowsocksr','usr/bin/xray','usr/libexec/cudy-ss-netns',
        'usr/lib/cudy-ss/migrate.lua','usr/lib/cudy-ss/config.lua','usr/libexec/cudy-ss-gate',
        'usr/lib/cudy-ss/ss-server-migrate.lua','usr/lib/lua/cudy/ssr-server.lua',
        'usr/share/shadowsocksr/gen_cudy_ss_server.lua','usr/libexec/cudy-ssr-server-firewall',
        'etc/init.d/cudy_ss_core','usr/lib/cudy-webfiles/bin/cudy-webfiles',
        'usr/lib/cudy-webfiles/bin/filebrowser','usr/sbin/smbd','usr/bin/zerotier-one']:
        assert (root/required).is_file(),required
    assert (root/'lib/upgrade/cudy-tr3600.sh').read_bytes()==(repo/'tr3600/cudy-upgrade.sh').read_bytes()
    for name in ['usr/bin/xray','bin/busybox','usr/sbin/smbd','usr/bin/zerotier-one']:
        data=(root/name).read_bytes()
        assert data[:6]==b'\x7fELF\x02\x01' and struct.unpack_from('<H',data,18)[0]==183,name
    xray_command=['qemu-aarch64-static','-L',str(root),str(root/'usr/bin/xray')]
    xray_version=subprocess.check_output(xray_command+['version'],text=True).splitlines()[0]
    assert xray_version.split()[:2]==['Xray',source['xray_version']],xray_version
    metadata=repo/'reports/image-metadata.json'
    subprocess.run([str(repo/'openwrt/staging_dir/host/bin/fwtool'),'-i',str(metadata),str(image)],check=True)
    devices=json.loads(metadata.read_text())['supported_devices']
    assert 'cudy,tr3600-v1' in devices and 'R126' in devices
    kernels=list((repo/'openwrt/build_dir').glob('target-*/linux-mediatek_filogic/linux-6.12.*'))
    assert len(kernels)==1
    symbols=(kernels[0]/'System.map').read_text()
    assert '__param_dual_boot' in symbols and '__param_rootfs_volume' in symbols
    assert not (root/'etc/cudy-webfiles').exists()
    assert not (root/'etc/cudy-ss').exists()
    ss_defaults=(root/'etc/config/cudy_ss').read_text()
    assert "option enabled '0'" in ss_defaults
    for key in ['password','listen','subnet','network_id','interface']:
        assert 'option '+key not in ss_defaults,key
    manifest=json.loads((root/'usr/lib/cudy-webfiles/manifest.json').read_text())
    assert manifest==json.loads((repo/'tr3600/cudy-webfiles/build-output/manifest.json').read_text())
    assert hashlib.sha256((root/'usr/lib/cudy-webfiles/bin/cudy-webfiles').read_bytes()).hexdigest()==manifest['helperSHA256']
    assert hashlib.sha256((root/'usr/lib/cudy-webfiles/bin/filebrowser').read_bytes()).hexdigest()==manifest['quantum']['sha256']
    config=(repo/'openwrt/.config').read_text()
    for package in ['luci-app-ssr-plus','dnsmasq-full','kmod-nft-socket','kmod-nft-tproxy','kmod-veth','luci-compat','luci-app-cudy-ss','zerotier']:
        assert 'CONFIG_PACKAGE_'+package+'=y' in config,package
    assert 'CONFIG_PACKAGE_luci-app-mango-proxy=y' not in config
    # Parse every actual installed Lua file and every shell entrypoint using target tools.
    syntax=0
    for base in ['usr/lib/cudy-ss','usr/lib/lua/cudy','usr/share/shadowsocksr','usr/libexec','etc/init.d','etc/uci-defaults']:
        for path in (root/base).glob('*'):
            if not path.is_file():continue
            try:text=path.read_text()
            except UnicodeDecodeError:continue
            if path.suffix=='.lua' or text.startswith('#!/usr/bin/lua'):
                if path.parent.name in ('cudy-ss','cudy') or path.name.startswith(('cudy-ss','gen_cudy_')):
                    subprocess.run(['qemu-aarch64-static','-L',str(root),str(root/'usr/bin/lua'),'-e',
                        'assert(loadfile('+json.dumps(str(path))+'))'],check=True);syntax+=1
            elif text.startswith('#!') and ('cudy' in path.name or path.name=='shadowsocksr'):
                subprocess.run(['qemu-aarch64-static','-L',str(root),str(root/'bin/busybox'),'sh','-n',str(path)],check=True);syntax+=1
    for relative in ('model/cbi/shadowsocksr/server-config.lua','model/cbi/shadowsocksr/server.lua',
        'model/cbi/shadowsocksr/status.lua','controller/shadowsocksr.lua'):
        path=root/'usr/lib/lua/luci'/relative
        assert path.is_file(),relative
        subprocess.run(['qemu-aarch64-static','-L',str(root),str(root/'usr/bin/lua'),'-e',
            'assert(loadfile('+json.dumps(str(path))+'))'],check=True)
        syntax+=1
    # Exercise native libuci/nixio from the packed image. A Lua-only mock can
    # accidentally supply cursor helpers that the installed native API lacks.
    for name in ['usr/bin/lua','usr/lib/lua/uci.so','usr/lib/lua/nixio.so','usr/lib/lua/nixio/fs.lua']:
        assert (root/name).is_file(),name
    native_environment=os.environ.copy()
    native_environment['LUA_PATH']=str(root/'usr/lib/lua/?.lua')+';'+str(root/'usr/lib/lua/?/init.lua')
    native_environment['LUA_CPATH']=str(root/'usr/lib/lua/?.so')
    native_sandbox=temp/'native-uci'
    assert not native_sandbox.exists()
    native_result=subprocess.run(['qemu-aarch64-static','-L',str(root),str(root/'usr/bin/lua'),
        str(repo/'tr3600/ssrplus/test-native-uci.lua'),str(root/'usr/lib/cudy-ss/migrate.lua'),str(native_sandbox)],
        env=native_environment,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    (repo/'reports/native-uci-packed-verification.log').write_text(native_result.stdout)
    print(native_result.stdout,end='')
    native_result.check_returncode()
    native_cases=['seeded_nil','missing_global_access_control','preserve_user_selection']
    for case in native_cases:
        assert 'PASS '+case+': native UCI, private SS preserved, repeat no-op' in native_result.stdout,case
    assert 'PASS all synthetic native-UCI migration checks; no production configuration used' in native_result.stdout
    private_migration_result=subprocess.run(['qemu-aarch64-static','-L',str(root),str(root/'usr/bin/lua'),
        str(repo/'tr3600/ssrplus/test-ss-server-migration.lua'),
        str(root/'usr/lib/cudy-ss/ss-server-migrate.lua'),str(root/'usr/lib/cudy-ss/config.lua'),
        str(temp/'private-row-native-uci'),str(root/'usr/lib/cudy-ss/ss-zt.lua')],env=native_environment,text=True,
        stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    (repo/'reports/private-ss-migration-packed-verification.log').write_text(private_migration_result.stdout)
    print(private_migration_result.stdout,end='')
    private_migration_result.check_returncode()
    assert 'PASS all 3 native private SS server_config migration cases' in private_migration_result.stdout
    server_report=repo/'reports/ss-server-packed-verification.json'
    subprocess.run(['python3',str(repo/'tr3600/ssrplus/test_ss_server.py'),
        '--root',str(root),'--report',str(server_report)],check=True)
    server_checks=json.loads(server_report.read_text())
    # Test all three preserved server ciphers with the actual compiled ARM64 Xray.
    for cipher in ['aes-128-gcm','aes-256-gcm','chacha20-ietf-poly1305']:
        cfg={'log':{'loglevel':'warning'},'dns':{'queryStrategy':'UseIPv4','servers':['198.18.255.1']},
            'inbounds':[{'tag':'cudy-ss-zt','listen':'0.0.0.0','port':8388,'protocol':'shadowsocks',
            'settings':{'method':cipher,'password':'synthetic-test-password-only-12345','network':'tcp,udp'}}],
            'outbounds':[{'protocol':'freedom','settings':{'domainStrategy':'UseIPv4'}}]}
        path=temp/'test.json';path.write_text(json.dumps(cfg))
        subprocess.run(xray_command+['run','-test','-config',str(path)],check=True)
    # A stock Xray build lacks these feed-provided protocols. Parse each actual
    # outbound with synthetic settings before accepting the packaged core.
    enhanced_outbounds={
        'shadowsocksr':{'address':'127.0.0.1','port':8388,'method':'aes-128-cfb',
            'password':'synthetic-test-password-only-12345','protocol':'origin','obfs':'plain'},
        'anytls':{'address':'127.0.0.1','port':443,'password':'synthetic-test-password-only-12345'},
        'tuic':{'address':'127.0.0.1','port':443,'version':5,
            'uuid':'00000000-0000-4000-8000-000000000001','password':'synthetic-test-password-only-12345',
            'serverName':'example.com','congestionControl':'bbr','udpRelayMode':'native'},
        'snell':{'address':'127.0.0.1','port':8388,'psk':'synthetic-test-password-only-12345','version':4}
    }
    for protocol,settings in enhanced_outbounds.items():
        outbound={'protocol':protocol,'settings':settings,'streamSettings':{'network':'raw'}}
        if protocol=='anytls':
            outbound['streamSettings'].update(security='tls',tlsSettings={'serverName':'example.com'})
        path=temp/('test-'+protocol+'.json')
        path.write_text(json.dumps({'log':{'loglevel':'warning'},'outbounds':[outbound]}))
        subprocess.run(xray_command+['run','-test','-config',str(path)],check=True)
    out=repo/'ssrplus-assets';out.mkdir(exist_ok=True)
    name='cudy-tr3600-v1-ssrplus-1.2.0-test3-sysupgrade.bin'
    shutil.copyfile(image,out/name)
    digest=hashlib.sha256(image.read_bytes()).hexdigest()
    (out/'SHA256SUMS').write_text(digest+'  '+name+'\n')
    proof={'image':name,'sha256':digest,'bytes':image.stat().st_size,'base':'tr3600-v1.1.1',
        'mango_proxy_installed':False,'ssrplus_commit':source['ssrplus_commit'],
        'actual_xray_version':xray_version,
        'actual_arm64_enhanced_outbound_configs_tested':list(enhanced_outbounds),
        'actual_arm64_native_uci_migration_cases_passed':len(native_cases),
        'actual_arm64_private_ss_row_migration_cases_passed':3,
        'private_ss':'SSR Plus+ server row with preserved scope and isolated network namespace',
        'ss_server_end_to_end_checks':server_checks,
        'private_ss_ipv6_supported':False,
        'actual_arm64_server_ciphers_tested':3,'actual_installed_syntax_checks':syntax,
        'hardware_flash_or_boot_tested':False}
    (out/'BUILD-VERIFICATION.json').write_text(json.dumps(proof,indent=2)+'\n')
    (out/'README.txt').write_text((repo/'tr3600/ssrplus/README.txt').read_text())
    shutil.copyfile(repo/'reports/resolved.config',out/'resolved.config')
    shutil.copyfile(repo/'reports/ssrplus-source.json',out/'SOURCE.json')
    print(json.dumps(proof,indent=2))

