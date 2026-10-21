#!/usr/bin/env python3
"""Exercise real shell lookup: missing external timeout must not suppress UPnP."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def check(command):
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        binary = folder / 'bin'
        binary.mkdir()
        (folder / 'board').write_text('glinet,gl-mt300n-v2\n')
        (folder / 'local.conf').write_text(json.dumps({'settings': {
            'secondaryPort': 48170, 'tertiaryPort': 20089, 'portMappingEnabled': True}}))
        (binary / 'ubus').write_text('''#!/bin/sh
[ "$#" = 5 ] && [ "$1" = -t ] && [ "$2" = 3 ] && [ "$3" = call ] && [ "$4" = network.interface.wan ] && [ "$5" = status ] || exit 92
printf '%s\\n' native-ubus-called > "$ZT_FIXTURE/called"
printf '%s\\n' '{"up":true,"route":[{"target":"0.0.0.0","mask":0,"nexthop":"192.0.2.1"}]}'
''')
        (binary / 'nft').write_text('''#!/bin/sh
if [ "$#" = 5 ] && [ "$1" = -j ] && [ "$2" = list ] && [ "$3" = table ] && [ "$4" = inet ] && [ "$5" = fw4 ]; then
 printf '%s\\n' '{"nftables":[{"table":{"family":"inet","name":"fw4"}},{"chain":{"family":"inet","table":"fw4","name":"input_wan"}}]}'
elif [ "$#" = 2 ] && [ "$1" = -f ] && [ "$2" = - ]; then
 : > "$ZT_FIXTURE/transaction"
 while IFS= read -r line; do printf '%s\\n' "$line" >> "$ZT_FIXTURE/transaction"; done
else exit 93; fi
''')
        for item in binary.iterdir():
            item.chmod(0o755)
        env = dict(os.environ, PATH=str(binary), ZT_FIXTURE=str(folder))
        assert shutil.which('timeout', path=env['PATH']) is None
        subprocess.run(command + [str(ROOT / 'tests/zt-command-runner.lua'), str(ROOT), str(folder)],
                       cwd=ROOT, env=env, check=True, timeout=15)
        assert (folder / 'called').read_text().strip() == 'native-ubus-called'
        text = (folder / 'transaction').read_text()
        assert text.count('comment "ZeroTier direct UDP"') == 1
        assert text.count('comment "ZeroTier UPnP discovery"') == 1
        assert 'ip saddr 192.0.2.1 udp sport 1900 udp dport 1024-65535 accept' in text
        assert text.count('insert rule inet fw4 input_wan jump mango_zt_direct') == 1
        return {'status': 'passed', 'external_timeout_present': False, 'real_shell_lookup': True,
                'native_ubus_arguments': 'verified', 'both_rules_generated': True}


@unittest.skipIf(os.name == 'nt', 'Requires Linux /bin/sh; run in firmware CI')
class CommandIntegration(unittest.TestCase):
    def test_both_rules_without_external_timeout(self):
        check([shutil.which('lua5.1') or shutil.which('lua') or 'lua5.1'])


if __name__ == '__main__':
    unittest.main()
