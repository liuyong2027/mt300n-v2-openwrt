#!/usr/bin/env python3
"""Check installed helper bytes and execute policy tests with the compiled MIPS Lua."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
roots = list((ROOT / 'openwrt/build_dir').glob('target-*/root-ramips'))
assert len(roots) == 1
rootfs = roots[0].resolve()
source = ROOT / 'package/luci-app-mango-proxy/root'
paths = ['usr/lib/mango/zt-direct.lua', 'usr/lib/mango/zt-json.lua', 'usr/libexec/mango-zt-direct', 'usr/libexec/mango-zt-direct-run',
         'etc/hotplug.d/iface/96-mango-zt-direct', 'etc/uci-defaults/96-mango-zt-direct', 'lib/upgrade/keep.d/mango-zt-direct']
for name in paths:
    assert (source / name).read_bytes() == (rootfs / name).read_bytes(), name
    if name.startswith(('usr/libexec/', 'etc/hotplug.d/', 'etc/uci-defaults/')):
        assert (rootfs / name).stat().st_mode & 0o111, name
actual_init = rootfs / 'etc/init.d/zerotier'
expected_init = ROOT / 'openwrt/feeds/packages/net/zerotier/files/etc/init.d/zerotier'
assert actual_init.read_bytes() == expected_init.read_bytes()
assert actual_init.read_text().count('/usr/libexec/mango-zt-direct') == 3
command = ['qemu-mipsel-static', '-L', str(rootfs), str(rootfs / 'usr/bin/lua')]
subprocess.run(command + ['tests/zt-json.lua'], cwd=ROOT, check=True)
subprocess.run(command + ['tests/zt-direct.lua'], cwd=ROOT, check=True)
subprocess.run(command + ['tests/zt-direct-runner.lua'], cwd=ROOT, check=True)
syntax = ROOT / 'reports/zt-target-syntax.lua'
syntax.write_text('''local root=arg[1]
package.path=root..'/usr/lib/?.lua;'..root..'/usr/lib/lua/?.lua;'..root..'/usr/lib/lua/?/init.lua;'..package.path
package.cpath=root..'/usr/lib/lua/?.so;'..package.cpath
assert(require('uci'));assert(require('mango.zt-direct'))
local j=assert(require('mango.zt-json'))
assert(j.decode('{"settings":{"secondaryPort":48170,"portMappingEnabled":true}}').settings.portMappingEnabled==true)
assert(loadfile(root..'/usr/libexec/mango-zt-direct-run'))
print('MIPS Lua helper and installed module loading passed')
''')
subprocess.run(command + [str(syntax), str(rootfs)], cwd=ROOT, check=True)
report = {'status': 'passed', 'architecture': 'actual compiled MIPS little-endian Lua under QEMU', 'policy_regressions': 'passed', 'installed_helpers_verified': paths, 'zerotier_init_hooks': 3, 'hardware_acceptance': 'pending'}
(ROOT / 'reports/zt-direct-target.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report))
