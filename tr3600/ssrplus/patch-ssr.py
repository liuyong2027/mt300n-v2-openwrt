"""Apply the TR3600 changes to the pinned helloworld feed."""
from pathlib import Path
import sys


def once(text, old, new):
    if text.count(old) != 1:
        raise ValueError(f'Pinned SSR patch anchor changed: {old[:100]!r}')
    return text.replace(old, new, 1)


def patch_init(text):
    begin = text.index('set_lock() {\n')
    end = text.index('first_type() {\n', begin)
    text = text[:begin] + '''# Keep the same inode across starts, stops and timeouts.
with_ssr_lock() (
    mkdir -p "${LOCK_FILE%/*}" || exit 1
    exec 8>>"$LOCK_FILE" || exit 1
    if ! flock -x -w 120 8; then
        echolog "ERROR: Timed out waiting for the SSR lifecycle lock."
        exit 1
    fi
    # The parent keeps the lock. Services spawned by the worker never inherit it.
    (
        exec 8>&-
        "$@"
    )
    # Keep the lock owner alive even if ash/dash optimize a final subshell.
    result=$?
    exec 8>&-
    exit "$result"
)

_exit() {
    exit "$1"
}

''' + text[end:]
    text = once(text, '''		[ -z "$ip" ] && ip=$(curl -sSL "http://119.29.29.29/d?dn=$host" | awk -F ';' '{print $1}')
''', '')
    text = once(text, '|| echo "119.29.29.29")', '|| echo "202.106.46.151")')
    # Resolve a deleted node before starting instead of re-entering restart
    # synchronously from the locked worker.
    text = once(text, '			/etc/init.d/shadowsocksr restart\n', '')
    text = once(text, '\tcheck_server\n', '')
    text = once(text, 'start() {\n\tlocal run_mode', 'start_without_cudy_gate() {\n\tlocal run_mode')
    text = once(text, '''		# Restore nft persistence rules
		if [ -f "$BACKUP_FILE" ]; then
			mkdir -p "$PERSIST_DIR"
			mv "$BACKUP_FILE" "$PERSIST_FILE"
			rm -rf "$BACKUP_DIR"
		fi
''', '')
    text = once(text, '\tlocal handle\n\n\tunlock', '\tlocal handle\n\tlocal backup_flag=\n\n\tunlock')
    text = once(text, '''		# Save nft rules before stopping to persist transparent proxy state
		if [ -f "$PERSIST_FILE" ]; then
			mkdir -p "$BACKUP_DIR"
			mv "$PERSIST_FILE" "$BACKUP_FILE"
		fi
		/usr/bin/ssr-rules -K
''', '''		backup_flag=-J
		/usr/bin/ssr-rules -K || return 1
''')
    text = once(text, '\t/usr/bin/ssr-rules -f\n', '\t/usr/bin/ssr-rules -f $backup_flag || return 1\n')
    text = once(text, '\tset_lock\n\techolog "----------start', '\techolog "----------start')
    text = once(text, '\t\tunset_lock\n\t\treturn 1\n\tfi\n\tnormalize_run_mode',
                '\t\treturn 1\n\tfi\n\tcheck_server\n\tnormalize_run_mode')
    text = once(text, '\t\t\tunset_lock\n\t\t\tstop\n', '\t\t\tstop_with_cudy_gate\n')
    text = once(text, '\tunset_lock\n}\n\nboot()', '\treturn 0\n}\n\nboot()')
    text = once(text, 'stop() {\n\tlocal run_mode', 'stop_without_cudy_gate() {\n\tlocal run_mode')
    text = once(text, '\tunlock\n\tset_lock\n\tcheck_run_environment', '\tcheck_run_environment')
    # -K owns daemon shutdown. Killing arbitrary ssr-rules workers can abort
    # a transaction after it has removed the live tables.
    text = once(text, '\t\tps_list | grep -v "grep" | grep ssr-rules | awk \'{print $1}\' | xargs kill -9 >/dev/null 2>&1 &\n', '')
    text = once(text, '\tunset_lock\n}\n\nreset() {\n\tstop\n\tset_lock\n',
                '\treturn 0\n}\n\nreset_locked() {\n\tstop_with_cudy_gate || return 1\n')
    text = once(text, '\tcp /usr/share/shadowsocksr/shadowsocksr.config /etc/config/shadowsocksr\n\tunset_lock\n',
                '\tcp /usr/share/shadowsocksr/shadowsocksr.config /etc/config/shadowsocksr\n')
    return text + '''
# IKEv2 claim can call SSR stop while holding the Mango lock. Yield first
# so the SSR lifecycle never waits for Mango while holding the SSR lock.
yield_to_ssr() {
    if [ -x /usr/libexec/mango-ikev2-peer-engine ]; then
        /usr/libexec/mango-ikev2-peer-engine yield || return 1
    fi
}

stop_with_cudy_gate() {
    /usr/libexec/cudy-ss-gate close || return 1
    /etc/init.d/cudy_ss stop || return 1
    local result
    stop_without_cudy_gate "$@"
    result=$?
    /usr/libexec/cudy-ssr-server-firewall stop || return 1
    return "$result"
}

start_with_cudy_gate() {
    start_without_cudy_gate "$@" || return $?
    /usr/libexec/cudy-ss-ssr-interfaces || return 1
    /usr/libexec/cudy-ss-gate started || return 1
    /etc/init.d/cudy_ss restart
}

restart_locked() {
    trap '' TERM
    stop_with_cudy_gate "$@"
    local result=$?
    trap - TERM
    [ "$result" = 0 ] || return "$result"
    start_with_cudy_gate "$@"
}

start() {
    yield_to_ssr || return 1
    with_ssr_lock start_with_cudy_gate "$@"
}

stop() {
    with_ssr_lock stop_with_cudy_gate "$@"
}

restart() {
    yield_to_ssr || return 1
    with_ssr_lock restart_locked "$@"
}

reset() {
    with_ssr_lock reset_locked "$@"
}
'''


SNAPSHOT = r'''
# Validate the same snapshot that will be installed. OUTPUT and TPROXY
# are optional when those modes are disabled, but a partial table never is.
valid_nft_snapshot() {
    local output tproxy
    output=$(uci_get_by_type access_control router_proxy 1)
    case "${TPROXY:-$(cat /tmp/.last_tproxy 2>/dev/null)}" in
        1|2) tproxy=1 ;;
        *) tproxy=0 ;;
    esac
    awk -v output="$output" -v tproxy="$tproxy" '
        $1 == "table" {
            inet_table = ($2 == "inet" && $3 == "ss_spec")
            mangle_table = ($2 == "ip" && $3 == "ss_spec_mangle")
            if (mangle_table) mangle_seen = 1
            chain = ""
        }
        $1 == "chain" { chain = $2 }
        $1 == "}" { chain = "" }
        inet_table && chain == "ss_spec_prerouting" && $1 == "type" &&
            $2 == "nat" && $3 == "hook" && $4 == "prerouting" { prerouting = 1 }
        inet_table && chain == "ss_spec_output" && $1 == "type" &&
            $2 == "nat" && $3 == "hook" && $4 == "output" { outbound = 1 }
        inet_table && $1 == "chain" && $2 == "ss_spec_wan_ac" { access = 1 }
        inet_table && $1 == "chain" && $2 == "ss_spec_wan_fw" { redirect = 1 }
        mangle_table && chain == "prerouting" && $1 == "type" &&
            $2 == "filter" && $3 == "hook" && $4 == "prerouting" { mangle_hook = 1 }
        mangle_table && chain == "ss_spec_tproxy" &&
            $0 ~ /[[:space:]]tproxy[[:space:]]/ { tproxy_rule = 1 }
        END {
            exit !(prerouting && access && redirect &&
                ((output != 1 && output != 2) || outbound) &&
                ((!tproxy && !mangle_seen) || (mangle_hook && tproxy_rule)))
        }
    ' "$1"
}

persist_nftables_rules() {
    [ "$USE_NFT" = 1 ] || return 0
    mkdir -p "$NFTABLES_RULES_DIR" || return 1
    local snapshot
    snapshot=$(mktemp "$NFTABLES_RULES_DIR/.shadowsocksr.XXXXXX") || return 1
    if ! {
        printf '%s\n' '#!/usr/sbin/nft -f' '# ShadowsocksR nftables rules'
        printf '# IPv6 schema: 1\n# IPv6 support: %s\n' "$(uci_get_by_type global ipv6_support 0)"
        printf '# Runmode: %s\n# Interfaces: %s\n' "${RUNMODE:-$(normalize_run_mode)}" \
            "$(cat /tmp/.ssr_rules_interfaces 2>/dev/null)"
        "$NFT" list table inet ss_spec 2>/dev/null &&
            { "$NFT" list table ip ss_spec_mangle 2>/dev/null || :; }
    } > "$snapshot" || ! valid_nft_snapshot "$snapshot"; then
        loger 4 "Refusing to persist incomplete SSR nftables rules"
        rm -f "$snapshot"
        return 1
    fi
    if ! { chmod 644 "$snapshot" && mv -f "$snapshot" "$NFTABLES_RULES_FILE"; }; then
        rm -f "$snapshot"
        return 1
    fi
    loger 5 "NFTables rules persisted to $NFTABLES_RULES_FILE"
}

remember_nft_interfaces() {
    printf '%s\n' "$Interface" > /tmp/.ssr_rules_interfaces
}

# Called by the generated fw4 include under the same rule lock as flush and
# persist. Keep the live rules when the snapshot is absent or incomplete.
reload_nft_snapshot() {
    [ -f "$NFTABLES_RULES_FILE" ] || return 0
    if ! valid_nft_snapshot "$NFTABLES_RULES_FILE"; then
        rm -f "$NFTABLES_RULES_FILE"
        return 1
    fi
    # Apply the deletes and replacement as one nft transaction.
    {
        printf '%s\n' 'destroy table inet ss_spec' 'destroy table ip ss_spec' \
            'destroy table ip ss_spec_mangle'
        cat "$NFTABLES_RULES_FILE"
    } | "$NFT" -f -
}

'''


def patch_rules(text):
    begin = text.index('\t\t# Clear existing ss_spec tables\n')
    end = text.index('\tEOF\n\tchmod +x "$FWI"', begin)
    text = text[:begin] + '''		/usr/bin/ssr-rules -V
		/usr/libexec/cudy-ss-ssr-interfaces
''' + text[end:]
    begin = text.index('# Compare current rules with persistence rules\n')
    end = text.index('# Auto-update daemon\n', begin)
    text = text[:begin] + SNAPSHOT.lstrip('\n') + text[end:]
    text = once(text, '\t\techo $$ > "/var/run/ssr-rules-daemon.pid"\n', '')
    text = once(text, '\t) &\n\n\tlocal DAEMON_PID=$!\n',
                '\t) 7>&- &\n\n\tlocal DAEMON_PID=$!\n\tprintf \'%s\\n\' "$DAEMON_PID" > /var/run/ssr-rules-daemon.pid\n')
    text = once(text, '''	# Remove existing rule file to ensure recreation
	rm -f "$NFTABLES_RULES_FILE" 2>/dev/null

''', '')
    text = once(text, '\t# Old snapshots lack the DNS-only whitelist', '''	if ! valid_nft_snapshot "$NFTABLES_RULES_FILE"; then
		loger 4 "Discarding incomplete SSR nftables snapshot"
		rm -f "$NFTABLES_RULES_FILE"
		return 2
	fi
	if [ -n "$local_port" ] &&
	   ! grep -Fxq "# Interfaces: $Interface" "$NFTABLES_RULES_FILE"; then
		loger 6 "SSR interface selection changed; rebuilding rules"
		rm -f "$NFTABLES_RULES_FILE"
		return 1
	fi

	# Old snapshots lack the DNS-only whitelist''')
    text = once(text, '\t\tloger 4 "Failed to restore rules from persistence file"\n\t\treturn 1',
                '\t\tloger 4 "Failed to restore rules from persistence file"\n\t\trm -f "$NFTABLES_RULES_FILE"\n\t\treturn 2')
    text = once(text, ':m:s:l:S:L:i:e:a:B:b:w:p:G:D:F:N:M:I:oOuUyfgrzAKPCRXh',
                ':m:s:l:S:L:i:e:a:B:b:w:p:G:D:F:N:M:I:oOuUyfgrzAKPCRXJVh')
    text = once(text, '\tR)\n\t\tRESTORE_RULES=1\n\t\t;;\n', '''	R)
		RESTORE_RULES=1
		;;
	J)
		BACKUP_SNAPSHOT=1
		;;
	V)
		RELOAD_SNAPSHOT=1
		;;
''')
    text = once(text, '# First process options that need immediate exit', '''# Standalone -P, -f, and firewall reloads also share this transaction lock.
mkdir -p /var/lock || exit 1
exec 7>>/var/lock/ssrplus-rules.lock || exit 1
if ! flock -x -w 120 7; then
	loger 3 "Timed out waiting for the SSR rules lock"
	exit 1
fi

if [ "$RELOAD_SNAPSHOT" = 1 ]; then
	reload_nft_snapshot
	exit $?
fi

# Boot/restart may reuse the snapshot saved by the previous stop. Keep both
# moves under the rules lock so the daemon cannot republish after a stop.
if [ "$USE_NFT" = 1 ] && [ -n "$local_port" ] && [ -f "$BACKUP_FILE" ]; then
	if valid_nft_snapshot "$BACKUP_FILE"; then
		mkdir -p "$PERSIST_DIR" && mv -f "$BACKUP_FILE" "$NFTABLES_RULES_FILE" || exit 1
	else
		rm -f "$BACKUP_FILE"
	fi
	rmdir "$BACKUP_DIR" 2>/dev/null || :
fi

# First process options that need immediate exit''')
    text = once(text, '''# Force flush rules
if [ "$FLUSH_RULES" = "1" ]; then
''', '''# Force flush rules
if [ "$FLUSH_RULES" = "1" ]; then
	if [ "$BACKUP_SNAPSHOT" = 1 ] && [ -f "$NFTABLES_RULES_FILE" ]; then
		if valid_nft_snapshot "$NFTABLES_RULES_FILE"; then
			mkdir -p "$BACKUP_DIR" && mv -f "$NFTABLES_RULES_FILE" "$BACKUP_FILE" || exit 1
		else
			rm -f "$NFTABLES_RULES_FILE"
		fi
	fi
''')
    text = once(text, '\t\trestore_from_persistence\n\t\texit $?',
                '''		restore_from_persistence
		result=$?
		if [ "$result" = 2 ]; then
			# Standalone restore has no rule arguments. Let the service
			# rebuild from UCI after releasing the rules lock.
			exec 7>&-
			exec /etc/init.d/shadowsocksr restart
		fi
		exit "$result"''')
    for message in ('NFT rules applied successfully (forced rebuild)',
                    'NFT rules restored from persistence', 'NFTables rules applied successfully'):
        line = f'loger 5 "{message}"\n'
        if text.count(line) != 1:
            raise ValueError(f'Pinned SSR rules anchor changed: {message}')
        index = text.index(line)
        indent = text[text.rindex('\n', 0, index) + 1:index]
        text = text[:index] + 'remember_nft_interfaces\n' + indent + text[index:]
    return text


def patch_control(text):
    text = once(text, '''	function m.on_apply(self)
		luci.sys.call("/etc/init.d/shadowsocksr reload > /dev/null 2>&1 &")
	end
''', '')
    text = once(text, 's:tab("esc", translate("Bypass Domain List"))', '''-- These lists live outside UCI. Stage a change only when a file changes so
-- a list-only Save & Apply still reaches the normal ucitrack path.
local function write_domain_list(section, path, value)
	if (nixio.fs.readfile(path) or "") == value then return end
	if not nixio.fs.writefile(path, value) then return end
	local revision = tonumber(m:get(section, "domain_lists_revision")) or 0
	return m:set(section, "domain_lists_revision", tostring(revision + 1))
end

s:tab("esc", translate("Bypass Domain List"))''')
    for name in ('escconf', 'blockconf', 'denydomainconf'):
        text = once(text, f'nixio.fs.writefile({name}, value:gsub("\\r\\n", "\\n"))',
                    f'return write_domain_list(section, {name}, value:gsub("\\r\\n", "\\n"))')
        text = once(text, f'nixio.fs.writefile({name}, "")',
                    f'return write_domain_list(section, {name}, "")')
    return text


def patch_xray(text):
    command = ('\tpython3 $(PKG_BUILD_DIR)/tools/eip93/overlay.py '
               '--go $(STAGING_DIR_HOSTPKG)/bin/go --out $(PKG_BUILD_DIR)/.eip93-overlay')
    if text.count(command) != 1:
        raise ValueError('Pinned Xray overlay command changed')
    return text.replace(command, '\t$(GO_BIN_PATH) python3 '
                        '$(PKG_BUILD_DIR)/tools/eip93/overlay.py --go go '
                        '--out $(PKG_BUILD_DIR)/.eip93-overlay', 1)


def patch(root):
    feed = root / 'feeds/helloworld'
    package = feed / 'luci-app-ssr-plus'
    changes = {
        feed / 'xray-core/Makefile': patch_xray,
        package / 'root/etc/init.d/shadowsocksr': patch_init,
        package / 'root/usr/bin/ssr-rules': patch_rules,
        package / 'luasrc/model/cbi/shadowsocksr/control.lua': patch_control,
        package / 'Makefile': lambda text: once(text, 'PKG_RELEASE:=1\n', 'PKG_RELEASE:=3\n'),
    }
    patched = {path: change(path.read_text(encoding='utf-8')) for path, change in changes.items()}
    for path, text in patched.items():
        path.write_text(text, encoding='utf-8', newline='\n')


if __name__ == '__main__':
    patch(Path(sys.argv[1]))
