#!/usr/bin/env python3
"""Set defaults only when OpenWrt generates a new TR3600 5 GHz radio."""
from pathlib import Path
import sys

def patch(tree):
    path = Path(tree)/'package/kernel/mac80211/files/lib/wifi/mac80211.uc'
    source = path.read_text(encoding='utf-8')
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
