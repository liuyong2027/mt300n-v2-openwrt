#!/usr/bin/env python3
"""Reject L2TP/IPsec/DDNS packages and public-facing service artifacts in test2."""
from pathlib import Path
import re
import sys

def validate_config(path):
    forbidden = re.compile(r'^CONFIG_PACKAGE_(?:luci-app-cudy-l2tp|cudy-l2tp-ifname|xl2tpd|luci-proto-l2tp|strongswan(?:-[^=]+)?|luci-app-ddns|luci-i18n-ddns-[^=]+|ddns-scripts(?:-[^=]+)?)=[ym]$')
    bad = [line for line in Path(path).read_text().splitlines() if forbidden.fullmatch(line)]
    assert not bad, 'Removed feature selected: ' + ', '.join(bad)

def validate_root(path):
    root = Path(path)
    forbidden = (
        'etc/init.d/cudy_l2tp', 'etc/init.d/xl2tpd', 'etc/init.d/swanctl', 'etc/init.d/ddns',
        'etc/config/cudy_l2tp', 'etc/config/ddns', 'usr/sbin/xl2tpd', 'usr/sbin/swanctl',
        'usr/lib/ipsec/charon', 'usr/lib/cudy-l2tp-ifname.so', 'usr/lib/ddns',
        'usr/libexec/cudy-l2tp-config', 'www/luci-static/resources/view/cudy-l2tp.js',
        'usr/share/luci/menu.d/luci-app-cudy-l2tp.json', 'usr/share/rpcd/acl.d/luci-app-cudy-l2tp.json',
        'usr/share/luci/menu.d/luci-app-ddns.json', 'www/luci-static/resources/view/ddns',
        'usr/share/nftables.d/chain-pre/input/90-cudy-l2tp.nft',
    )
    bad = [name for name in forbidden if (root / name).exists() or (root / name).is_symlink()]
    assert not bad, 'Removed feature installed: ' + ', '.join(bad)

if __name__ == '__main__':
    validate_root(sys.argv[1])
    validate_config(sys.argv[2])
    print('L2TP/IPsec and dynamic DNS packages, services, credentials and pages absent')
