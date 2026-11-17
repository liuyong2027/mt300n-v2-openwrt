"""Exercise the TR3600 SSR patch using the pinned upstream feed from CI."""
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest

HERE = Path(__file__).resolve().parent
CBI = Path('luasrc/model/cbi/shadowsocksr')
SSR = Path('feeds/helloworld/luci-app-ssr-plus')
BUILD_FILES = (
    SSR / 'Makefile',
    SSR / 'root/etc/init.d/shadowsocksr',
    SSR / 'root/usr/bin/ssr-rules',
    Path('feeds/helloworld/xray-core/Makefile'),
)


def function(text, declaration, close='}'):
    start = text.index('\n' + declaration + '\n') + 1
    end = text.index('\n' + close + '\n', start) + len(close) + 2
    return text[start:end]


class SSRLifecycleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temp = tempfile.TemporaryDirectory(prefix='ssr-lifecycle-')
        cls.addClassCleanup(temp.cleanup)
        cls.root = Path(temp.name)
        with tarfile.open('pinned-ssr.tar.gz') as archive:
            prefix = archive.getmembers()[0].name
            cbi_prefix = f'{prefix}/luci-app-ssr-plus/{CBI.as_posix()}/'
            cls.pages = sorted(SSR / CBI / Path(m.name).name for m in archive.getmembers()
                               if m.isfile() and m.name.startswith(cbi_prefix) and m.name.endswith('.lua'))
            for path in (*BUILD_FILES, *cls.pages):
                file = cls.root / path
                file.parent.mkdir(parents=True, exist_ok=True)
                source = path.relative_to('feeds/helloworld').as_posix()
                with archive.extractfile(f'{prefix}/{source}') as source_file:
                    file.write_bytes(source_file.read())
        subprocess.run([sys.executable, str(HERE / 'patch-ssr.py'), str(cls.root)], check=True)
        cls.init = (cls.root / BUILD_FILES[1]).read_text(encoding='utf-8')
        cls.rules = (cls.root / BUILD_FILES[2]).read_text(encoding='utf-8')
        for name in BUILD_FILES[1:3]:
            subprocess.run(['sh', '-n', (cls.root / name).as_posix()], check=True)

    def test_only_ucitrack_triggers_cbi_apply(self):
        control = (self.root / SSR / CBI / 'control.lua').read_text(encoding='utf-8')
        self.assertNotIn('on_apply', control)
        self.assertNotIn('/etc/init.d/shadowsocksr reload', control)
        self.assertIn('m.apply_on_parse = true', control)
        self.assertIn('m:set(section, "domain_lists_revision"', control)
        self.assertEqual((self.root / SSR / 'Makefile').read_text().count('PKG_RELEASE:=3\n'), 1)
        for page in self.pages:
            text = (self.root / page).read_text(encoding='utf-8')
            self.assertNotRegex(text, r'(?s)\bon_(?:after_)?apply\b.{0,200}/etc/init.d/shadowsocksr\s+(?:reload|restart)')

    def test_concurrent_restarts_serialize_stop_and_start(self):
        with tempfile.TemporaryDirectory(prefix='ssr-restarts-') as directory:
            work = Path(directory)
            lifecycle = function(self.init, 'with_ssr_lock() (', ')')
            restart = function(self.init, 'restart_locked() {') + function(self.init, 'restart() {')
            script = work / 'test-restart'
            script.write_text('''LOCK_FILE="$1/ssrplus.lock"
log="$1/events"
role="$2"
release="$1/release"
yield_to_ssr() { :; }
echolog() { printf '%s\\n' "$*" >&2; }
stop_with_cudy_gate() {
    [ ! -e /proc/self/fd/8 ] || return 1
    printf '%s stop\\n' "$role" >> "$log"
    if [ "$role" = first ]; then
        while [ ! -f "$release" ]; do sleep 0.02; done
    fi
}
start_with_cudy_gate() {
    [ ! -e /proc/self/fd/8 ] || return 1
    printf '%s start\\n' "$role" >> "$log"
}
''' + lifecycle + restart + '''
if [ "$role" = timeout ]; then
    flock() { command flock -x -w 0 8; }
fi
restart
''', encoding='utf-8', newline='\n')

            def process(role):
                child = subprocess.Popen(['sh', script.as_posix(), work.as_posix(), role])
                self.addCleanup(lambda: child.wait(timeout=5) if child.poll() is not None
                                else (child.kill(), child.wait(timeout=5)))
                return child

            first = process('first')
            log = work / 'events'
            for _ in range(150):
                if log.is_file() and log.read_text() == 'first stop\n':
                    break
                time.sleep(.02)
            self.assertEqual(log.read_text(), 'first stop\n')
            inode = (work / 'ssrplus.lock').stat().st_ino
            second = process('second')
            self.assertEqual(process('timeout').wait(timeout=5), 1)
            self.assertIsNone(second.poll())
            self.assertEqual(log.read_text(), 'first stop\n')
            (work / 'release').touch()
            self.assertEqual(first.wait(timeout=5), 0)
            self.assertEqual(second.wait(timeout=5), 0)
            self.assertEqual(log.read_text().splitlines(), [
                'first stop', 'first start', 'second stop', 'second start'])
            self.assertEqual((work / 'ssrplus.lock').stat().st_ino, inode)
        self.assertIn('mango-ikev2-peer-engine yield', function(self.init, 'yield_to_ssr() {'))
        for action in ('start', 'restart'):
            wrapper = function(self.init, f'{action}() {{')
            self.assertLess(wrapper.index('yield_to_ssr'), wrapper.index('with_ssr_lock'))

    def test_snapshot_refuses_partial_tables_and_rebuilds(self):
        with tempfile.TemporaryDirectory(prefix='ssr-snapshot-') as directory:
            work = Path(directory)
            main = work / 'inet'
            mangle = work / 'mangle'
            persist = work / '99-shadowsocksr.nft'
            script = work / 'test-rules'
            main.write_text('''table inet ss_spec {
    set whitelist_domain {
        type ipv4_addr
    }
    chain ss_spec_wan_ac {
        ip daddr @whitelist_domain return
    }
    chain ss_spec_wan_fw {
        tcp redirect to :12345
    }
    chain ss_spec_prerouting {
        type nat hook prerouting priority filter; policy accept;
        jump ss_spec_wan_ac
    }
    chain ss_spec_output {
        type nat hook output priority filter; policy accept;
        jump ss_spec_wan_ac
    }
}
''')
            good_mangle = '''table ip ss_spec_mangle {
    chain ss_spec_tproxy {
        meta l4proto udp tproxy ip to :12345
    }
    chain prerouting {
        type filter hook prerouting priority mangle; policy accept;
        jump ss_spec_tproxy
    }
}
'''
            chainless = '''table ip ss_spec_mangle {
    set china {
        type ipv4_addr
    }
}
'''
            pieces = ('valid_nft_snapshot', 'persist_nftables_rules', 'restore_from_persistence')
            step8 = self.rules.index('\t\t# STEP 8: Persistence exists')
            step9_end = self.rules.index('\n\telse\n\t\t# iptables', step8)
            script.write_text('''NFTABLES_RULES_DIR="$1"
NFTABLES_RULES_FILE="$1/99-shadowsocksr.nft"
USE_NFT=1
NFT=fake_nft
TPROXY="$3"
loger() { :; }
uci_get_by_type() { printf '%s\\n' "$3"; }
normalize_run_mode() { echo gfw; }
ipv6_enabled() { return 1; }
fake_nft() {
    case "$*" in
        'list table inet ss_spec') cat "$NFTABLES_RULES_DIR/inet" ;;
        'list table ip ss_spec_mangle') cat "$NFTABLES_RULES_DIR/mangle" ;;
        '-f '*) echo loaded; return 1 ;;
    esac
}
flush_r() { :; }
ipset_r() { echo rebuild; return 0; }
fw_rule() { :; }
ac_rule() { :; }
tp_rule() { :; }
ipv6_rules_apply() { :; }
gen_include() { :; }
remember_nft_interfaces() { :; }
''' + ''.join(function(self.rules, name + '() {') for name in pieces) + '''
if [ "$2" = persist ]; then
    persist_nftables_rules
    exit $?
fi
PERSISTENCE_EXISTS=1
ENABLE_AUTO_UPDATE=0
''' + self.rules[step8:step9_end], encoding='utf-8', newline='\n')

            def invoke(action, tproxy='1'):
                return subprocess.run(['sh', script.as_posix(), work.as_posix(), action, tproxy],
                                      capture_output=True, text=True)

            mangle.write_text(chainless)
            self.assertEqual(invoke('persist').returncode, 1)
            self.assertFalse(persist.exists())
            mangle.write_text(good_mangle)
            self.assertEqual(invoke('persist').returncode, 0)
            previous = persist.read_bytes()
            mangle.write_text(chainless)
            self.assertEqual(invoke('persist').returncode, 1)
            self.assertEqual(persist.read_bytes(), previous)

            persist.write_text(chainless)
            rebuilt = invoke('restore')
            self.assertEqual(rebuilt.returncode, 0, rebuilt.stderr)
            self.assertEqual(rebuilt.stdout.strip(), 'rebuild')
            self.assertFalse(persist.exists())

            # A missing mangle table is valid only when UDP TPROXY is off.
            mangle.unlink()
            self.assertEqual(invoke('persist').returncode, 1)
            self.assertEqual(invoke('persist', '0').returncode, 0)


if __name__ == '__main__':
    unittest.main()
