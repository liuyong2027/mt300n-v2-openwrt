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
        self.assertIn('11e0a48737097f8b0e0ec0dd080350ea7fd08d94',prepare)

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

    def test_node_migration_preserves_private_service_and_is_retryable(self):
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
function u:get(c,s,k) local a=state[c] and state[c][s]; if not a then return end;return k and a[k] or a['.type'] end
function u:get_all(c,s) return state[c] and state[c][s] end
function u:get_first(c,t,k) for s,a in pairs(state[c] or {}) do if a['.type']==t then return k and a[k] or s end end end
function u:section(c,t,s,a) state[c]=state[c] or {};state[c][s]=a or {};state[c][s]['.type']=t;state[c][s]['.name']=s;return s end
function u:set(c,s,k,v) assert(state[c] and state[c][s]);state[c][s][k]=v;return true end
function u:delete(c,s,k) if k then state[c][s][k]=nil else state[c][s]=nil end;return true end
function u:foreach(c,t,fn) for s,a in pairs(state[c] or {}) do if a['.type']==t then a['.name']=s;fn(a) end end end
function u:commit(c) return true end
f={access=function(p) return files[p] or false end,
 writefile=function(p,v) if interrupt_marker then error('simulated interrupted marker') end;files[p]=v;return true end,
 chmod=function() return true end,remove=function(p) files[p]=nil;return true end}
package.loaded['nixio.fs']=f
package.loaded['uci']={cursor=function() return u end}
interrupt_marker=true
''')
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

if __name__=='__main__':unittest.main(verbosity=2)

