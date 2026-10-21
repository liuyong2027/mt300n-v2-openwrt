#!/usr/bin/env python3
"""Check installed helper bytes and execute policy tests with the compiled MIPS Lua."""
import hashlib
import importlib.util
import os
import shutil
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
command = [shutil.which('qemu-mipsel-static'), '-L', str(rootfs), str(rootfs / 'usr/bin/lua')]
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

# Verify actual installed dependencies, not host executables hidden by a fixture.
spec_paths = importlib.util.spec_from_file_location('zt_target_paths', ROOT / 'scripts/zt_target_paths.py')
module_paths = importlib.util.module_from_spec(spec_paths)
spec_paths.loader.exec_module(module_paths)
installed_commands = {}
for name in ('ubus', 'nft', 'flock', 'lua', 'sh'):
    candidates = [rootfs / folder / name for folder in ('bin', 'sbin', 'usr/bin', 'usr/sbin')]
    executable = next((p for p in candidates if module_paths.resolve_in_root(rootfs, p).is_file() and os.access(module_paths.resolve_in_root(rootfs, p), os.X_OK)), None)
    assert executable is not None, 'Missing target command: ' + name
    installed_commands[name] = executable.relative_to(rootfs).as_posix()
ubus = rootfs / installed_commands['ubus']
native = subprocess.run(command[:3] + [str(ubus), '-t', '3', '-s', '/tmp/mango-zt-ci-no-ubus.sock', 'call', 'network.interface.wan', 'status'],
                        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=10)
assert native.returncode != 0 and 'Failed to connect to ubus' in native.stdout, native.stdout
assert 'unrecognized option' not in native.stdout, native.stdout
spec = importlib.util.spec_from_file_location('zt_command_integration', ROOT / 'tests/test_zt_command_integration.py')
integration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(integration)
command_report = integration.check(command)

report = {'status': 'passed', 'architecture': 'actual compiled MIPS little-endian Lua under QEMU', 'policy_regressions': 'passed', 'installed_helpers_verified': paths, 'zerotier_init_hooks': 3, 'hardware_acceptance': 'pending', 'installed_external_commands': installed_commands, 'native_ubus_timeout': 'passed with actual MIPS ubus', 'command_lookup_without_external_timeout': command_report}
(ROOT / 'reports/zt-direct-target.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report))
