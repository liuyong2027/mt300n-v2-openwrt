import hashlib
from pathlib import Path
root=Path(__file__).resolve().parents[2]
config=(root/'openwrt/.config').read_text()
required=['luci-app-ssr-plus','xray-core','dnsmasq-full','luci-compat','kmod-nft-socket',
    'kmod-nft-tproxy','kmod-nft-nat','kmod-veth','luci-app-cudy-ss','luci-app-cudy-led',
    'cudy-webfiles','luci-app-cudy-usb','samba4-server','zerotier','luci-app-ddns']
for name in required:assert 'CONFIG_PACKAGE_'+name+'=y' in config,name
for name in ['luci-app-mango-proxy','dnsmasq','mango-tcpcheck']:
    assert 'CONFIG_PACKAGE_'+name+'=y' not in config,name
assert 'CONFIG_PACKAGE_luci-app-ssr-plus_Nftables_Transparent_Proxy=y' in config
assert 'CONFIG_TARGET_mediatek_filogic_DEVICE_cudy_tr3600-v1=y' in config
assert 'CONFIG_KERNEL_NET_NS=y' in config
for name in ('cudy-webfiles','filebrowser','manifest.json'):
    source=root/'tr3600/cudy-webfiles/build-output'/name
    packaged=root/'openwrt/package/cudy-webfiles/build-output'/name
    assert source.is_file() and source.stat().st_size > 0,source
    assert packaged.is_file() and packaged.stat().st_size > 0,packaged
    assert hashlib.sha256(source.read_bytes()).digest()==hashlib.sha256(packaged.read_bytes()).digest(),name
print('All replacement, private SS and retained device packages selected; WebFiles package inputs match guarded outputs')

