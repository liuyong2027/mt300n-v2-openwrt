#!/usr/bin/env python3
"""Keep DNS startup independent of slow flash snapshots; make nft cache reloadable."""
from pathlib import Path
import sys

root=Path(sys.argv[1])/'package/luci-app-ssr-plus/root'
init=root/'etc/init.d/shadowsocksr'
rules=root/'usr/bin/ssr-rules'

def once(text,before,after):
    assert text.count(before)==1,(before,text.count(before))
    return text.replace(before,after.replace(r'\t','\t'))

def function(text,name,replacement):
    start=text.index(name+'() {\n')
    end=text.index('\n}\n',start)+3
    return text[:start]+replacement.rstrip().replace(r'\t','\t')+'\n'+text[end:]

s=init.read_text(encoding='utf-8')
s=once(s,'PERSIST_DIR="/usr/share/nftables.d/ruleset-post"','PERSIST_DIR="/tmp/ssrplus-nft"')
s=once(s,'BACKUP_DIR="/etc/ssrplus/ssrplus-persist"','BACKUP_DIR="/tmp/ssrplus-nft-backup"')
s=once(s,'\t\tstart_rules 9>&-\n\t\tstart_dns\n', '''		if ! start_dns; then
			echolog "DNS startup failed; refusing to report a successful start."
			unset_lock
			return 1
		fi
		if ! start_rules 9>&-; then
			echolog "Proxy firewall setup failed."
			unset_lock
			return 1
		fi
''')
s=once(s,'\t\t\tln_start_bin $(first_type dns2tcp) dns2tcp -L 127.0.0.1#$dns_port -R ${dnsserver/:/#}\n\t\t\tpdnsd_enable_flag=1', '''			ln_start_bin $(first_type dns2tcp) dns2tcp -L "127.0.0.1#$dns_port" -R "${dnsserver/:/#}"
			local dns_pid=$!
			sleep 1
			if ! kill -0 "$dns_pid" 2>/dev/null; then
				echolog "DNS2TCP exited during startup."
				return 1
			fi
			pdnsd_enable_flag=1''')
init.write_text(s,encoding='utf-8',newline='\n')

s=rules.read_text(encoding='utf-8')
s=once(s,'NFT="nft -nn"','NFT="nft -nn -t"')
s=once(s,'NFTABLES_RULES_DIR="/usr/share/nftables.d/ruleset-post"','NFTABLES_RULES_DIR="/tmp/ssrplus-nft"')
s=function(s,'gen_include_nft',r'''
gen_include_nft() {
	[ -n "$FWI" ] || return 0
	cat <<-'EOF' >"$FWI"
		#!/bin/sh
		# Runtime state is rebuilt from UCI on boot; never write large caches to NOR.
		exec 9>/var/lock/ssrplus.lock
		flock -x -w 60 9 || exit 1
		cache=/tmp/ssrplus-nft/99-shadowsocksr.nft
		[ -s "$cache" ] || exit 0
		{
			echo 'destroy table inet ss_spec'
			echo 'destroy table ip ss_spec_mangle'
			cat "$cache"
		} | nft -f -
	EOF
	chmod +x "$FWI"
}
''')
dump=r'''
dump_nft_rules() {
	local found=0
	if $NFT list table inet ss_spec >/dev/null 2>&1; then
		nft -nn -s list table inet ss_spec || return 1
		found=1
	fi
	if $NFT list table ip ss_spec_mangle >/dev/null 2>&1; then
		nft -nn -s list table ip ss_spec_mangle || return 1
		found=1
	fi
	[ "$found" = "1" ]
}

compare_rules() {
	[ "$USE_NFT" = "1" ] && [ -s "$NFTABLES_RULES_FILE" ] || return 1
	local current=$(mktemp "$NFTABLES_RULES_DIR/compare.XXXXXX") || return 1
	local result=1
	if dump_nft_rules >"$current"; then
		cmp -s "$current" "$NFTABLES_RULES_FILE"
		result=$?
	fi
	rm -f "$current"
	return "$result"
}
'''
s=function(s,'compare_rules',dump)
s=function(s,'persist_nftables_rules',r'''
persist_nftables_rules() {
	[ "$USE_NFT" = "1" ] || return 0
	mkdir -p "$NFTABLES_RULES_DIR" || return 1
	local temporary=$(mktemp "$NFTABLES_RULES_DIR/rules.XXXXXX") || return 1
	if ! dump_nft_rules >"$temporary" || [ ! -s "$temporary" ]; then
		rm -f "$temporary"
		loger 3 "Unable to snapshot active proxy rules."
		return 1
	fi
	# Only nft-generated syntax is stored. Multiline IP metadata is not executable input.
	chmod 600 "$temporary"
	mv -f "$temporary" "$NFTABLES_RULES_FILE" || return 1
	if [ -n "$server" ] && [ -n "$local_port" ]; then
		printf '%s\n' "$RULES_FINGERPRINT" >"$NFTABLES_RULES_FILE.key.new"
		mv -f "$NFTABLES_RULES_FILE.key.new" "$NFTABLES_RULES_FILE.key"
	fi
	loger 5 "Proxy rules cached atomically in RAM."
	return 0
}
''')
s=function(s,'restore_from_persistence',r'''
restore_from_persistence() {
	[ "$USE_NFT" = "1" ] && [ -s "$NFTABLES_RULES_FILE" ] || return 1
	local transaction=$(mktemp "$NFTABLES_RULES_DIR/restore.XXXXXX") || return 1
	{
		echo 'destroy table inet ss_spec'
		echo 'destroy table ip ss_spec_mangle'
		cat "$NFTABLES_RULES_FILE"
	} >"$transaction"
	# A parse failure rolls back the complete transaction, including both destroys.
	if ! nft -f "$transaction"; then
		rm -f "$transaction"
		loger 4 "Cached proxy rules were rejected; active rules retained."
		return 1
	fi
	rm -f "$transaction"
	if $NFT list table ip ss_spec_mangle >/dev/null 2>&1; then
		ip rule show | grep -Eq "fwmark ${FWMARK}.*lookup 999" ||
			ip rule add fwmark "$FWMARK" table 999 priority 999 || return 1
		ip route show table 999 | grep -Eq '^local.*dev lo' ||
			ip route add local 0.0.0.0/0 dev lo table 999 || return 1
	fi
	loger 5 "Proxy rules restored atomically from RAM."
	return 0
}
''')
s=once(s,'\t\techo $$ > "/var/run/ssr-rules-daemon.pid"\n','')
s=once(s,'\tlocal DAEMON_PID=$!\n\tsleep 2','\tlocal DAEMON_PID=$!\n\tprintf \'%s\\n\' "$DAEMON_PID" > /var/run/ssr-rules-daemon.pid\n\tsleep 2')
s=once(s,'while getopts ":m:s:l:S:L:i:e:a:B:b:w:p:G:D:F:N:M:I:oOuUfgrczAKPCRXh" arg; do',r'''
# Include the selected endpoint and source rules in cache validity, without logging secrets.
RULES_FINGERPRINT=$(
	{
		printf '%s\000' "$@"
		uci -q show shadowsocksr | sed '/\.old_global_server=/d; /\.ip=/d'
		sha256sum /etc/ssrplus/china_ssr.txt /etc/ssrplus/netflixip.list 2>/dev/null
	} | sha256sum | cut -d ' ' -f 1
)

while getopts ":m:s:l:S:L:i:e:a:B:b:w:p:G:D:F:N:M:I:oOuUfgrczAKPCRXh" arg; do''')
s=once(s,'\t\tFORCE_RECREATE=0\n\t\tPERSISTENCE_EXISTS=0', '''		FORCE_RECREATE=0
		PERSISTENCE_EXISTS=0
		if [ "$RULES_FINGERPRINT" != "$(cat "$NFTABLES_RULES_FILE.key" 2>/dev/null)" ]; then
			FORCE_RECREATE=1
		fi''')
rules.write_text(s,encoding='utf-8',newline='\n')
print('DNS startup and atomic RAM nft cache fixes applied')
