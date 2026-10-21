import hashlib
from pathlib import Path
import re


def check_xray_source(root,config):
    openwrt=root/'openwrt'
    packages=list((openwrt/'package/feeds').glob('*/xray-core'))
    expected=openwrt/'feeds/helloworld/xray-core'
    assert len(packages)==1,('Expected one Xray source package',packages)
    assert packages[0].resolve(strict=True)==expected.resolve(strict=True),('Wrong Xray feed',packages[0])
    makefile=(expected/'Makefile').read_text()
    assert re.search(r'^PKG_VERSION:=26\.10\.21$',makefile,re.M),'Wrong Xray version'
    assert re.search(r'^PKG_RELEASE:=1$',makefile,re.M),'Wrong Xray release'
    assert '# CONFIG_XRAY_CORE_NAIVE is not set' in config,'Expected visible, disabled Cronet option'
    assert 'CONFIG_XRAY_CORE_NAIVE=y' not in config,'Cronet must remain disabled'


def main():
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
    check_xray_source(root,config)
    for name in ('cudy-webfiles','filebrowser','manifest.json'):
        source=root/'tr3600/cudy-webfiles/build-output'/name
        packaged=root/'openwrt/package/cudy-webfiles/build-output'/name
        assert source.is_file() and source.stat().st_size > 0,source
        assert packaged.is_file() and packaged.stat().st_size > 0,packaged
        assert hashlib.sha256(source.read_bytes()).digest()==hashlib.sha256(packaged.read_bytes()).digest(),name
    print('All replacement, private SS and retained device packages selected; Xray 26.10.21 from helloworld; WebFiles package inputs match guarded outputs')


if __name__=='__main__':main()

