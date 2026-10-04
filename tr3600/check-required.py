#!/usr/bin/env python3
"""Report every requested component dropped by Kconfig before compiling."""
from pathlib import Path
required = {line for line in Path('tr3600/tr3600.config').read_text().splitlines()
            if line.startswith(('CONFIG_PACKAGE_', 'CONFIG_TARGET_')) and line.endswith('=y')}
required.add('CONFIG_LUCI_JSMIN=y')
required.add('CONFIG_TARGET_SQUASHFS_BLOCK_SIZE=1024')
resolved = set(Path('openwrt/.config').read_text().splitlines())
missing = sorted(required-resolved)
for line in missing:
    print('Required configuration missing: '+line, flush=True)
if missing:
    raise SystemExit('Requested components were dropped by Kconfig; refusing incomplete image')
print('All requested device, USB, repeater and L2TP/IPsec components selected')
