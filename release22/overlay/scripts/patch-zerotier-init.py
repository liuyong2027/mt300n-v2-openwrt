#!/usr/bin/env python3
"""Add lifecycle hooks to the exact Release 21 ZeroTier init without touching configuration.

Each hook is skipped when mango-zt-direct is not installed (the IKEv2 profile
has no luci-app-mango-proxy), so ZeroTier start does not log a false
"Rule refresh failed". When the helper is installed the guard is a no-op
and the hook runs as before.
"""
import hashlib
from pathlib import Path
import sys

BASE_SHA256 = 'babca17d5a939bfdefb40338670f317819981405082a119e5e45d3f0ea579a86'


def patch(source):
    assert hashlib.sha256(source.encode()).hexdigest() == BASE_SHA256, 'Unexpected pinned ZeroTier init'
    changes = {
        '\t\techo "disabled in /etc/config/zerotier"': '\t\t[ ! -x /usr/libexec/mango-zt-direct ] || /usr/libexec/mango-zt-direct stop >/dev/null 2>&1 || true\n\t\techo "disabled in /etc/config/zerotier"',
        '\tprocd_close_instance\n': '\tprocd_close_instance\n\t[ ! -x /usr/libexec/mango-zt-direct ] || /usr/libexec/mango-zt-direct >/dev/null 2>&1 || logger -t mango-zt-direct "Rule refresh failed; retry on firewall or WAN event"\n',
        'stop_service() {\n': 'stop_service() {\n\t[ ! -x /usr/libexec/mango-zt-direct ] || /usr/libexec/mango-zt-direct stop >/dev/null 2>&1 || true\n',
    }
    for old, new in changes.items():
        assert source.count(old) == 1, old
        source = source.replace(old, new)
    return source


if __name__ == '__main__':
    path = Path(sys.argv[1])
    path.write_text(patch(path.read_text()), encoding='utf-8', newline='\n')
