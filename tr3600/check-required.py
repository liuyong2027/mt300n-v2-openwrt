#!/usr/bin/env python3
"""Report every requested component dropped by Kconfig before compiling."""
from pathlib import Path
from importlib.machinery import SourceFileLoader
removed = SourceFileLoader('removed_features', str(Path(__file__).parent/'check-removed.py')).load_module()
required = {line for line in Path('tr3600/tr3600.config').read_text().splitlines()
            if line.startswith(('CONFIG_PACKAGE_', 'CONFIG_TARGET_')) and line.endswith('=y')}
required.add('CONFIG_LUCI_JSMIN=y')
required.add('CONFIG_TARGET_SQUASHFS_BLOCK_SIZE=1024')
resolved = set(Path('openwrt/.config').read_text().splitlines())
removed.validate_config('openwrt/.config')
missing = sorted(required-resolved)
for line in missing:
    print('Required configuration missing: '+line, flush=True)
if missing:
    raise SystemExit('Requested components were dropped by Kconfig; refusing incomplete image')
print('All requested device, USB, repeater, unified Wi-Fi and LED components selected')
