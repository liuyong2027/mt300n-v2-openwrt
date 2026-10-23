#!/usr/bin/env python3
"""Execute new source under actual MIPS ash/nc; optionally require installed bytes."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
roots=list((ROOT/'openwrt/build_dir').glob('target-*/root-ramips'))
assert len(roots)==1
fs=roots[0].resolve(); source=ROOT/'package/luci-app-mango-proxy/root'
qemu=shutil.which('qemu-mipsel-static'); assert qemu
command=[qemu, '-L', str(fs)]
busybox=command+[str(fs/'bin/busybox')]
paths=['etc/init.d/mango_proxy', 'usr/libexec/mango-watchdog', 'usr/libexec/mango-core-health',
       'usr/libexec/mango-memory-guard', 'etc/uci-defaults/98-mango-memory',
       'etc/sysctl.d/99-mango-memory.conf', 'lib/upgrade/keep.d/mango-memory']
preflight='--preflight' in sys.argv
for name in paths:
    if not preflight:
        assert (source/name).read_bytes()==(fs/name).read_bytes(), name
    if name.startswith(('usr/libexec/', 'etc/init.d/', 'etc/uci-defaults/')):
        if not preflight: assert (fs/name).stat().st_mode & 0o111, name
        subprocess.run(busybox+['sh', '-n', str(source/name)], check=True, timeout=10)
applets=subprocess.check_output(busybox+['--list'], text=True).splitlines()
for name in ['nc', 'cmp', 'mktemp', 'rmdir', 'kill', 'sleep', 'awk', 'readlink', 'cut', 'tail', 'mv']:
    assert name in applets, 'Missing actual target applet: '+name
sys.path.insert(0,str(ROOT/'tests'))
import memory_checks
results=memory_checks.guard_cases(source,busybox+['sh'])
results+=memory_checks.protocol_cases(source,busybox+['sh'],busybox+['nc'])
results+=memory_checks.dns_cases(source,busybox+['sh'])
assert len(results)==36
dns=next(p for p in [fs/'usr/sbin/dnsmasq', fs/'sbin/dnsmasq'] if p.is_file())
config=ROOT/'reports/memory-dnsmasq-test.conf'
config.write_text('max-tcp-connections=8\n')
subprocess.run(command+[str(dns), '--test', '--conf-file='+str(config)], check=True, timeout=15)
assert 'GOMEMLIMIT=48MiB GOGC=50' in (source/'etc/init.d/mango_proxy').read_text()
assert (source/'etc/sysctl.d/99-mango-memory.conf').read_text().splitlines()[-3:]==[
    'vm.min_free_kbytes=16384','vm.watermark_boost_factor=0','vm.watermark_scale_factor=10']
report={'status':'passed','version':'24','preflight_prior_target':preflight,
        'installed_bytes_verified': [] if preflight else paths,
        'execution_scope':'Actual MIPS BusyBox ash and nc under QEMU; recovery collaborators, procfs and UCI mocked in temporary directories; other external commands use host utilities',
        'actual_mips_dnsmasq_option':'passed', 'checks':results,
        'new_full_image_hardware_acceptance':'pending'}
(ROOT/'reports/memory-target.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
