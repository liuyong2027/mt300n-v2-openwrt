#!/usr/bin/env python3
"""Load the actual ARM64 PPP plugin in two simultaneous dry-run processes."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import re
import subprocess
import sys

root = Path(sys.argv[1]).resolve()
def run():
    p = subprocess.run(['sudo','qemu-aarch64-static','-L',str(root),
                        str(root/'usr/sbin/pppd'),'notty','dryrun','noauth','plugin',
                        str(root/'usr/lib/cudy-l2tp-ifname.so')],capture_output=True,text=True)
    assert p.returncode == 0, p.stdout+p.stderr
    m = re.search(r'\bifname\s+(l2tp[0-9]+)\b',p.stdout+p.stderr)
    assert m, p.stdout+p.stderr
    assert len(m[1]) < 16
    return m[1]
with ThreadPoolExecutor(max_workers=2) as executor:
    names = list(executor.map(lambda _:run(),range(2)))
assert len(set(names)) == 2, names
print('Actual ARM64 PPP plugin loaded and concurrent processes assigned distinct VPN interfaces')
