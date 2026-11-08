#!/usr/bin/env python3
"""Set defaults only when OpenWrt generates a new TR3600 5 GHz radio."""
from pathlib import Path
import hashlib
import sys

# Exact Git blobs of package/network/config/wifi-scripts/files/lib/wifi/mac80211.uc.
# v25.12.6 differs from v25.12.5 only by upstream 6bc29f34241d, which prepends
# the 60 GHz band. The replacements below do not rewrite bands_order.
REVIEWED_BLOBS = {
    'd61786fa65023521d16fdf6bc499c2d26ee2d275',  # v25.12.5 f0a60eee2fe051741c643ea6118718aae1ef17fb
    'c6c973040eb8c01f8fb8618337f9d1cf3cce4447',  # v25.12.6 64900e756efa667774214f9c6b17c113222e01f7
}

def patch(tree):
    path = Path(tree)/'package/network/config/wifi-scripts/files/lib/wifi/mac80211.uc'
    data = path.read_bytes()
    blob = b'blob ' + str(len(data)).encode('ascii') + bytes([0]) + data
    digest = hashlib.sha1(blob).hexdigest()
    assert digest in REVIEWED_BLOBS, 'Unexpected locked OpenWrt wireless generator: ' + digest
    source = data.decode('utf-8')
    replacements = [
        ('const bands_order =', 'const cudy_tr3600 = trim(readfile("/tmp/sysinfo/board_name") || "") == "cudy,tr3600-v1";\n\nconst bands_order ='),
        ('\t\tif (!phy.path)\n', '\t\t// Existing radios are skipped below; never rewrite saved wireless settings.\n\t\tif (cudy_tr3600 && band_name == "5G" && band.he) {\n\t\t\tchannel = 36;\n\t\t\thtmode = "HE80";\n\t\t}\n\n\t\tif (!phy.path)\n'),
        ('${defaults?.ssid || "OpenWrt"}', '${defaults?.ssid || (cudy_tr3600 && band_name == "5g" ? "Cudy-TR3600-5G" : "OpenWrt")}'),
    ]
    for old, new in replacements:
        assert source.count(old) == 1, (path, old)
        source = source.replace(old, new)
    path.write_text(source, encoding='utf-8', newline='\n')

if __name__ == '__main__':
    patch(sys.argv[1])
