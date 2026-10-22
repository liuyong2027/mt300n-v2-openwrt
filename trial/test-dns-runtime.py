#!/usr/bin/env python3
"""Exercise actual nft cache, failure rollback and routing recovery in isolated tables."""
from pathlib import Path
import subprocess
import sys
import tempfile

root=Path(sys.argv[1])/'package/luci-app-ssr-plus/root'
source=(root/'usr/bin/ssr-rules').read_text(encoding='utf-8')
def function(name):
    start=source.index(name+'() {\n')
    end=source.index('\n}\n',start)+3
    return source[start:end].replace('ss_spec','dns_fixture').replace('999','1999')
functions='\n'.join(function(name) for name in [
    'dump_nft_rules','compare_rules','persist_nftables_rules',
    'restore_from_persistence','gen_include_nft'])
script=r'''#!/bin/sh
set -eu
umask 077
if nft list table inet dns_fixture >/dev/null 2>&1 || nft list table ip dns_fixture_mangle >/dev/null 2>&1; then
 echo 'Fixture table already exists; refusing to replace it.';exit 1
fi
if ip rule show | grep -q 'lookup 1999' || [ -n "$(ip route show table 1999 2>/dev/null)" ]; then
 echo 'Fixture routing table already in use; refusing to replace it.';exit 1
fi
directory=$(mktemp -d /tmp/ssr-dns-fixture.XXXXXX)
cleanup() {
 nft destroy table inet dns_fixture 2>/dev/null || true
 nft destroy table ip dns_fixture_mangle 2>/dev/null || true
 ip rule del fwmark 0xd150 table 1999 priority 1999 2>/dev/null || true
 ip route del local 0.0.0.0/0 dev lo table 1999 2>/dev/null || true
 rm -f "$directory"/*
 rmdir "$directory"
}
trap cleanup EXIT
NFT='nft -nn -t'
USE_NFT=1
FWMARK=0xd150
NFTABLES_RULES_DIR=$directory
NFTABLES_RULES_FILE=$directory/cache.nft
FWI=$directory/firewall.include
RULES_FINGERPRINT=fixture-only
server=198.51.100.1
local_port=1234
WAN_BP_IP=$(printf '192.168.6.0/24\n192.168.7.0/24\n192.168.8.0/24')
loger() { printf '%s\n' "$2"; }
'''+functions+r'''
nft -f - <<'NFT'
table inet dns_fixture {
 set china { type ipv4_addr; flags interval; auto-merge; elements = { 198.18.0.0/24, 203.0.113.0/24 }; }
 chain dns_fixture_wan_fw { counter; }
 chain dns_fixture_wan_ac { ip daddr @china return; jump dns_fixture_wan_fw; }
}
table ip dns_fixture_mangle {
 chain sample { counter; }
}
NFT
persist_nftables_rules
[ -s "$NFTABLES_RULES_FILE" ]
[ "$(ls -l "$NFTABLES_RULES_FILE" | awk '{print $1}')" = '-rw-------' ]
compare_rules
cp "$NFTABLES_RULES_FILE" "$directory/good.nft"
good=$(sha256sum "$NFTABLES_RULES_FILE" | cut -d ' ' -f 1)
# A failed dump must leave the previous complete cache untouched.
(
 dump_nft_rules() { printf 'incomplete invalid input\n';return 1; }
 if persist_nftables_rules; then exit 1;fi
)
[ "$good" = "$(sha256sum "$NFTABLES_RULES_FILE" | cut -d ' ' -f 1)" ]
echo CACHE_WRITE_FAILURE_ROLLBACK=passed
# A malformed cache must not destroy the currently active tables.
before=$(nft -nn -s list table inet dns_fixture | sha256sum | cut -d ' ' -f 1)
printf '192.168.7.0/24\n' >"$NFTABLES_RULES_FILE"
if restore_from_persistence; then exit 1;fi
after=$(nft -nn -s list table inet dns_fixture | sha256sum | cut -d ' ' -f 1)
[ "$before" = "$after" ]
echo INVALID_CACHE_ATOMIC_ROLLBACK=passed
cp "$directory/good.nft" "$NFTABLES_RULES_FILE"
restore_from_persistence
ip rule show | grep -q 'fwmark 0xd150.*lookup 1999'
ip route show table 1999 | grep -q '^local.*dev lo'
compare_rules
echo VALID_CACHE_AND_TPROXY_ROUTE_RESTORE=passed
gen_include_nft
sed -e "s#cache=/tmp/ssrplus-nft/99-shadowsocksr.nft#cache=$NFTABLES_RULES_FILE#" \
 -e "s#/var/lock/ssrplus.lock#$directory/include.lock#" "$FWI" >"$directory/test-include"
sh "$directory/test-include"
compare_rules
echo GENERATED_FIREWALL_INCLUDE=passed
echo DNS_RUNTIME_KERNEL_FIXTURES=passed
'''
if len(sys.argv)>2:
    assert sys.argv[2]=='--emit'
    Path(sys.argv[3]).write_text(script,encoding='utf-8',newline='\n')
else:
    with tempfile.TemporaryDirectory() as directory:
        path=Path(directory)/'test.sh'
        path.write_text(script,encoding='utf-8')
        subprocess.run(['sh',str(path)],check=True)
