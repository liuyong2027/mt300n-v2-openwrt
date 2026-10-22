import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from lupa.lua51 import LuaRuntime

REPO=Path(__file__).resolve().parents[2]
PROFILE=REPO/'tr3600/ssrplus'

class ProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(prefix='ssrplus-tests-',dir=REPO.parent)
        cls.tree=Path(cls.tmp.name)/'source'
        shutil.copytree(REPO,cls.tree,ignore=shutil.ignore_patterns('.git','__pycache__','openwrt','vendor','build-output','work-go-feed'))
        subprocess.run([sys.executable,'-X','utf8',str(cls.tree/'tr3600/ssrplus/profile.py')],check=True)
        cls.ss=cls.tree/'tr3600/luci-app-cudy-ss'
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def lua(self):
        lua=LuaRuntime(unpack_returned_tuples=True)
        def dofile(path):
            p=self.ss/'root'/path.lstrip('/') if path.startswith('/usr/') else Path(path)
            return lua.execute(p.read_text(encoding='utf-8'))
        lua.globals().dofile=dofile
        return lua

    def test_profile_removes_mango_dependencies(self):
        config=(self.tree/'tr3600/ssrplus/tr3600.config').read_text()
        self.assertNotIn('CONFIG_PACKAGE_luci-app-mango-proxy=y',config)
        self.assertIn('CONFIG_PACKAGE_luci-app-ssr-plus=y',config)
        self.assertIn('CONFIG_PACKAGE_kmod-nft-socket=y',config)
        self.assertIn('CONFIG_PACKAGE_kmod-veth=y',config)
        self.assertNotIn('+luci-app-mango-proxy',(self.ss/'Makefile').read_text())
        prepare=(self.tree/'scripts/prepare.sh').read_text()
        self.assertNotIn('cp -R "$kit/package/luci-app-mango-proxy"',prepare)
        self.assertNotIn('ss-integration.py',prepare)
        self.assertIn('patch-ssr.py',prepare)
        self.assertIn('80d7bfff625b33db8afe80934638d96d214ceadc',prepare)
        self.assertLess(prepare.index('./scripts/feeds install -f -p helloworld'),
            prepare.index('./scripts/feeds install -a'))
        self.assertLess(prepare.index('cp -R "$kit/work-go-feed/lang/golang" feeds/packages/lang/'),
            prepare.index('./scripts/feeds update -i packages'))
        self.assertLess(prepare.index('./scripts/feeds update -i packages'),
            prepare.index('./scripts/feeds install -f -p helloworld'))

    def test_all_installed_lua_compiles(self):
        lua=self.lua()
        roots=[self.ss/'root',self.tree/'tr3600/luci-app-cudy-led/root']
        count=0
        for root in roots:
            for p in root.rglob('*'):
                if not p.is_file():continue
                text=p.read_text(encoding='utf-8')
                if p.suffix=='.lua' or text.startswith('#!/usr/bin/lua'):
                    lua.execute('assert(loadstring(...))',text.removeprefix('#!/usr/bin/lua\n'));count+=1
        self.assertGreaterEqual(count,12)

    def test_scope_and_cipher_validation_retained(self):
        lua=self.lua()
        m=lua.globals().dofile('/usr/lib/cudy-ss/ss-zt.lua')
        raw=lua.table_from(dict(enabled='1',listen='10.42.0.2',subnet='10.42.0.0/24',interface='ztabcdef',
            network_id='0123456789abcdef',port='8388',method='aes-128-gcm',password='x'*32))
        self.assertEqual(m.validate(raw).listen,'10.42.0.2')
        for key,value in [('listen','8.8.8.8'),('subnet','0.0.0.0/0'),('method','none'),('password','short')]:
            altered=lua.table_from(dict(raw.items()));altered[key]=value
            with self.assertRaises(Exception):m.validate(altered)

    def test_private_service_is_namespace_bound(self):
        lua=self.lua();n=lua.globals().dofile('/usr/lib/cudy-ss/config.lua')
        c=lua.table_from(dict(listen='10.42.0.2',subnet='10.42.0.0/24',interface='ztabcdef',
            port=8388,method='aes-256-gcm',password='test-password-which-is-long'))
        config=n.config(c)
        self.assertEqual(config.inbounds[1].listen,'0.0.0.0')
        self.assertEqual(config.inbounds[1].settings.network,'tcp,udp')
        self.assertEqual(config.dns.servers[1],'198.18.255.1')
        self.assertEqual(config.outbounds[1].protocol,'freedom')
        guard=n.guard(c)
        self.assertIn('iifname != "ztabcdef" counter drop',guard)
        self.assertIn('ip saddr != 10.42.0.0/24 counter drop',guard)
        self.assertIn('dnat ip to 198.18.255.2:8388',guard)
        self.assertIn('ip daddr 198.18.255.2 counter drop',guard)
        self.assertNotIn('dnat',n.guard(None))
        self.assertIn('10.42.0.2',n.bridge(None,c))

    def test_no_retired_executable_in_ss_runtime(self):
        for p in (self.ss/'root').rglob('*'):
            if p.is_file():
                if p.name=='migrate.lua':continue  # Recognizes the old include without executing it.
                self.assertNotIn('/usr/libexec/mango-',p.read_text(encoding='utf-8'),str(p))
                self.assertNotIn('/etc/init.d/mango_',p.read_text(encoding='utf-8'),str(p))
                self.assertNotIn('/usr/lib/mango/',p.read_text(encoding='utf-8'),str(p))

    def test_gate_retained_on_firewall_reload(self):
        migration=(PROFILE/'migration.sh').read_text()
        self.assertIn("position='ruleset-pre'",migration)
        self.assertIn('/etc/cudy-ss/route-guard.nft',migration)
        gate=(PROFILE/'root/usr/libexec/cudy-ss-gate').read_text()
        self.assertIn('ssr-ready',gate)
        self.assertIn('iifname "css-host" counter drop',gate)

    def migration_lua(self):
        lua=self.lua()
        lua.execute('''
state={shadowsocksr={global={['.type']='global',global_server='nil'}},
 mango_proxy={main={['.type']='policy',mode='global',node='primary'},
 primary={['.name']='primary',['.type']='node',protocol='vless',address='relay.example',
 port='443',uuid='00000000-0000-4000-8000-000000000001',public_key='synthetic-public-key',sni='example.com'}},
 cudy_ss={main={password='private-existing-key',port='8388',listen='10.42.0.2'}},
 dhcp={dns={['.type']='dnsmasq',server={'127.0.0.1#1053','9.9.9.9'}}},
 firewall={mango_proxy={path='/usr/libexec/mango-fw'},owner_rule={target='REJECT'}}}
files={['/etc/cudy-ssrplus/seeded-config']=true}
u={}
function u:get(c,s,k) local a=state[c] and state[c][s]; if not a then return end;if k then return a[k] else return a['.type'] end end
function u:get_all(c,s) return state[c] and state[c][s] end
-- Native libuci intentionally has neither get_first nor section.
function u:set(c,s,k,v)
 if v==nil then
  state[c]=state[c] or {};state[c][s]=state[c][s] or {}
  state[c][s]['.type']=k;state[c][s]['.name']=s
 else assert(state[c] and state[c][s]);state[c][s][k]=v end
 return true
end
function u:delete(c,s,k) if k then state[c][s][k]=nil else state[c][s]=nil end;return true end
function u:foreach(c,t,fn) for s,a in pairs(state[c] or {}) do if a['.type']==t then a['.name']=s;fn(a) end end end
function u:commit(c) return true end
f={access=function(p) return files[p] or false end,
 writefile=function(p,v) if interrupt_marker then error('simulated interrupted marker') end;files[p]=v;return true end,
 chmod=function() return true end,remove=function(p) files[p]=nil;return true end}
package.loaded['nixio.fs']=f
package.loaded['uci']={cursor=function() return u end}
interrupt_marker=false
''')
        return lua

    def test_node_migration_preserves_private_service_and_is_retryable(self):
        lua=self.migration_lua()
        lua.execute('interrupt_marker=true;assert(u.get_first==nil and u.section==nil)')
        source=(PROFILE/'root/usr/lib/cudy-ss/migrate.lua').read_text()
        with self.assertRaises(Exception):lua.execute(source)
        lua.execute('interrupt_marker=false')
        lua.execute(source)
        lua.execute('''
assert(state.shadowsocksr.global.global_server=='migrated_primary')
assert(state.shadowsocksr.global.run_mode=='all')
assert(state.shadowsocksr.migrated_primary.reality=='1')
assert(state.shadowsocksr.migrated_primary.vmess_id==state.mango_proxy.primary.uuid)
assert(state.cudy_ss.main.password=='private-existing-key')
assert(state.cudy_ss.main.listen=='10.42.0.2')
assert(state.firewall.owner_rule.target=='REJECT')
assert(state.firewall.mango_proxy==nil)
assert(state.dhcp.dns.server[1]=='9.9.9.9')
assert(state.shadowsocksr.access_control.Interface[2]=='cudy_ss')
''')
        lua.execute(source)  # Completed migrations are a no-op.

    def test_native_uci_creates_missing_global_and_access_control_sections(self):
        lua=self.migration_lua()
        lua.execute('state.shadowsocksr={}')
        lua.execute((PROFILE/'root/usr/lib/cudy-ss/migrate.lua').read_text())
        lua.execute('''
assert(state.shadowsocksr.global['.type']=='global')
assert(state.shadowsocksr.global.global_server=='migrated_primary')
assert(state.shadowsocksr.access_control['.type']=='access_control')
assert(files['/etc/cudy-ssrplus/migration-v1.done'])
''')

    def test_leftover_seed_preserves_imported_nodes_and_current_settings(self):
        lua=self.migration_lua()
        lua.execute('''
local g=state.shadowsocksr.global
g.global_server='cfg024a8f';g.run_mode='gfw';g.udp_relay_server='custom-udp'
g.prefer_nft='0';g.router_proxy='0';g.custom_ports='80,443'
state.shadowsocksr.cfg024a8f={['.type']='servers',server='owner-relay.example',password='owner-imported-key'}
state.shadowsocksr.cfg_second={['.type']='servers',server='second-relay.example'}
state.shadowsocksr.access_control={['.type']='access_control',Interface={'lan'},router_proxy='0',wan_bp_ips={'203.0.113.7'}}
state.mango_proxy.main.bypass4={'198.51.100.7'}
state.dhcp.dns.filter_aaaa='0'
''')
        lua.execute((PROFILE/'root/usr/lib/cudy-ss/migrate.lua').read_text())
        lua.execute('''
local g=state.shadowsocksr.global
assert(g.global_server=='cfg024a8f' and g.run_mode=='gfw')
assert(g.udp_relay_server=='custom-udp' and g.prefer_nft=='0' and g.router_proxy=='0' and g.custom_ports=='80,443')
assert(state.shadowsocksr.cfg024a8f.password=='owner-imported-key')
assert(state.shadowsocksr.cfg_second.server=='second-relay.example')
local ac=state.shadowsocksr.access_control
assert(ac.router_proxy=='0' and ac.Interface[2]=='cudy_ss')
assert(#ac.wan_bp_ips==2 and ac.wan_bp_ips[1]=='203.0.113.7' and ac.wan_bp_ips[2]=='198.18.255.0/30')
assert(state.dhcp.dns.filter_aaaa=='0' and state.dhcp.dns.server[1]=='9.9.9.9')
assert(files['/etc/cudy-ssrplus/seeded-config']==nil)
''')

    def test_retry_preserves_changes_to_an_already_migrated_node(self):
        lua=self.migration_lua()
        source=(PROFILE/'root/usr/lib/cudy-ss/migrate.lua').read_text()
        lua.execute('interrupt_marker=true')
        with self.assertRaises(Exception):lua.execute(source)
        lua.execute("interrupt_marker=false;state.shadowsocksr.migrated_primary.server='owner-edited.example';state.shadowsocksr.global.run_mode='gfw'")
        lua.execute(source)
        lua.execute("assert(state.shadowsocksr.migrated_primary.server=='owner-edited.example');assert(state.shadowsocksr.global.run_mode=='gfw')")

    def test_led_snapshot_uses_native_uci_and_handles_direct_mode(self):
        lua=self.migration_lua()
        lua.execute('''
uci=package.loaded['uci'];fs=f;M={dir='/var/run/cudy-led'}
function M.board() return 'cudy,tr3600-v1' end
function M.now() return 123 end
function M.capture() return 'default via 192.0.2.1' end
function M.blocked() return false end
os.execute=function() return 0 end
''')
        lua.execute((PROFILE/'led-adapter.lua').read_text())
        lua.execute('''
M.identity=function() return 'synthetic-identity' end
state.shadowsocksr.global.global_server='cfg024a8f';state.shadowsocksr.global.run_mode='gfw'
assert(M.snapshot().mode=='gfw' and M.snapshot().ready)
state.shadowsocksr.global.run_mode='all';assert(M.snapshot().mode=='global')
state.shadowsocksr.global.run_mode='router';assert(M.snapshot().mode=='split')
state.shadowsocksr.global.global_server='nil';assert(M.snapshot().mode=='direct')
state.shadowsocksr.global.global_server='';assert(M.snapshot().mode=='direct')
state.shadowsocksr={};assert(M.snapshot().mode=='direct')
''')

    def test_namespace_ownership_and_collision_checks(self):
        helper=(PROFILE/'root/usr/libexec/cudy-ss-netns').read_text()
        self.assertIn('owned ||',helper)
        self.assertIn('ip netns pids',helper)
        self.assertIn('check-prefix.lua',helper)
        self.assertIn('disable_ipv6',helper)

    def test_routing_prefix_collision_is_rejected(self):
        source=(PROFILE/'root/usr/lib/cudy-ss/check-prefix.lua').read_text()
        for line,allowed in [('default via 192.168.1.1 dev eth0',True),
            ('192.168.1.0/24 dev br-lan',True),('198.18.0.0/15 dev other',False),
            ('local 198.18.255.1 dev other table local',False)]:
            lua=self.lua()
            lua.globals().test_line=line
            lua.execute('io.popen=function() return {lines=function() local done=false; return function() if not done then done=true;return test_line end end end,close=function() end} end')
            if allowed:lua.execute(source)
            else:
                with self.assertRaises(Exception):lua.execute(source)

    def test_atomic_ss_transaction_retained(self):
        worker=(self.ss/'root/usr/libexec/cudy-ss-worker').read_text(encoding='utf-8')
        for action in ('snapshot=','protect=','commit=','rollback_guard=','rollback_verify='):
            self.assertIn(action,worker)
        self.assertIn('/etc/init.d/cudy_ss_core restart',worker)
        self.assertIn('/usr/bin/xray run -test',worker)
        self.assertNotIn('mango',worker)

    def test_zt_defaults_remove_old_service_enable(self):
        text=(self.ss/'root/etc/uci-defaults/94-cudy-zt-zone').read_text()
        self.assertNotIn('/etc/init.d/mango_',text)
        self.assertIn("uci -q delete firewall.mango_proxy",text)
        self.assertIn("if ! uci -q get firewall.mango_zt",text)

class SourceSelectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='ssrplus-source-tests-',dir=REPO.parent)
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.feed=self.root/'openwrt/feeds/helloworld/xray-core'
        self.feed.mkdir(parents=True)
        (self.feed/'Makefile').write_text('PKG_VERSION:=26.10.21\nPKG_RELEASE:=1\n'
            '\t$(GO_BIN_PATH) python3 $(PKG_BUILD_DIR)/tools/eip93/overlay.py --go go --out $(PKG_BUILD_DIR)/.eip93-overlay\n')
        self.package=self.root/'openwrt/package/feeds/helloworld/xray-core'
        self.package.parent.mkdir(parents=True)
        self.link(self.feed,self.package)
        spec=importlib.util.spec_from_file_location('check_config',PROFILE/'check_config.py')
        self.check=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.check)
        self.config='# CONFIG_XRAY_CORE_NAIVE is not set\n'

    def link(self,target,path):
        if os.name=='nt':
            # Junctions exercise the same resolved directory identity on Windows.
            quote=lambda value:"'"+str(value).replace("'","''")+"'"
            subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',
                'New-Item -ItemType Junction -Path '+quote(path)+' -Target '+quote(target)+' | Out-Null'],check=True)
        else:path.symlink_to(target,target_is_directory=True)

    def test_matching_xray_source_is_accepted(self):
        self.check.check_xray_source(self.root,self.config)

    def test_old_packages_feed_is_rejected(self):
        if os.name=='nt':self.package.rmdir()
        else:self.package.unlink()
        old=self.root/'openwrt/feeds/packages/net/xray-core';old.mkdir(parents=True)
        (old/'Makefile').write_text('PKG_VERSION:=26.3.27\nPKG_RELEASE:=1\n')
        self.link(old,self.package)
        with self.assertRaisesRegex(AssertionError,'Wrong Xray feed'):
            self.check.check_xray_source(self.root,self.config)

    def test_duplicate_xray_package_is_rejected(self):
        duplicate=self.root/'openwrt/package/feeds/packages/xray-core'
        duplicate.parent.mkdir(parents=True)
        self.link(self.feed,duplicate)
        with self.assertRaisesRegex(AssertionError,'Expected one Xray source'):
            self.check.check_xray_source(self.root,self.config)

    def test_wrong_version_is_rejected(self):
        (self.feed/'Makefile').write_text('PKG_VERSION:=26.3.27\nPKG_RELEASE:=1\n')
        with self.assertRaisesRegex(AssertionError,'Wrong Xray version'):
            self.check.check_xray_source(self.root,self.config)

    def test_obsolete_overlay_go_path_is_rejected(self):
        p=self.feed/'Makefile'
        p.write_text(p.read_text().replace('$(GO_BIN_PATH) python3','python3').replace('--go go','--go $(STAGING_DIR_HOSTPKG)/bin/go'))
        with self.assertRaisesRegex(AssertionError,'Xray overlay must use the selected Go compiler'):
            self.check.check_xray_source(self.root,self.config)

    def go_sources(self):
        for name in ('golang','golang1.27'):
            source=self.root/'openwrt/feeds/packages/lang/golang'/name
            source.mkdir(parents=True)
            (source/'Makefile').write_text('PKG_NAME:='+name+'\n')
            package=self.root/'openwrt/package/feeds/packages'/name
            package.parent.mkdir(parents=True,exist_ok=True)
            self.link(source,package)

    def test_matching_go_host_sources_are_accepted(self):
        self.go_sources()
        self.check.check_go_sources(self.root)

    def test_missing_versioned_go_host_package_is_rejected(self):
        self.go_sources()
        package=self.root/'openwrt/package/feeds/packages/golang1.27'
        if os.name=='nt':package.rmdir()
        else:package.unlink()
        with self.assertRaisesRegex(AssertionError,'Missing or duplicate Go host package'):
            self.check.check_go_sources(self.root)

    def test_wrong_go_host_source_is_rejected(self):
        self.go_sources()
        package=self.root/'openwrt/package/feeds/packages/golang1.27'
        if os.name=='nt':package.rmdir()
        else:package.unlink()
        self.link(self.feed,package)
        with self.assertRaisesRegex(AssertionError,'Wrong Go feed'):
            self.check.check_go_sources(self.root)

    def test_missing_or_enabled_cronet_option_is_rejected(self):
        for config in ('','CONFIG_XRAY_CORE_NAIVE=y\n',self.config+'CONFIG_XRAY_CORE_NAIVE=y\n'):
            with self.assertRaises(AssertionError):
                self.check.check_xray_source(self.root,config)


class OverlayPatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='ssrplus-overlay-tests-',dir=REPO.parent)
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.makefile=self.root/'feeds/helloworld/xray-core/Makefile'
        self.makefile.parent.mkdir(parents=True)
        self.command='\tpython3 $(PKG_BUILD_DIR)/tools/eip93/overlay.py --go $(STAGING_DIR_HOSTPKG)/bin/go --out $(PKG_BUILD_DIR)/.eip93-overlay\n'
        self.makefile.write_text(self.command)
        self.init=self.root/'feeds/helloworld/luci-app-ssr-plus/root/etc/init.d/shadowsocksr'
        self.init.parent.mkdir(parents=True)
        self.init.write_text('start() {\n :\n}\nstop() {\n :\n}\n')
        rules=self.root/'feeds/helloworld/luci-app-ssr-plus/root/usr/bin/ssr-rules'
        rules.parent.mkdir(parents=True)
        rules.write_text('gen_include_nft() {\n\tcat <<-EOF >>"$FWI"\n\t\ttrue\n\tEOF\n\tchmod +x "$FWI"\n}\n')

    def run_patch(self):
        return subprocess.run([sys.executable,str(PROFILE/'patch-ssr.py'),str(self.root)],capture_output=True,text=True)

    def test_overlay_uses_standard_go_path(self):
        result=self.run_patch()
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('$(GO_BIN_PATH) python3',self.makefile.read_text())
        self.assertIn('--go go --out',self.makefile.read_text())
        self.assertNotIn('$(STAGING_DIR_HOSTPKG)/bin/go',self.makefile.read_text())
        self.assertIn('/usr/libexec/cudy-ss-gate started',self.init.read_text())

    def test_changed_or_duplicate_overlay_command_is_rejected(self):
        for command in ('',self.command+self.command):
            self.makefile.write_text(command)
            result=self.run_patch()
            self.assertNotEqual(result.returncode,0)
            self.assertIn('Pinned Xray overlay command changed',result.stderr)
            self.assertEqual(self.makefile.read_text(),command)


if __name__=='__main__':unittest.main(verbosity=2)

