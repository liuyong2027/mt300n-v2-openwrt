"""Model/UI checks for ordinary SS; packed acceptance is a separate Linux test."""
import argparse
from pathlib import Path
import unittest
from lupa.lua51 import LuaRuntime

HERE=Path(__file__).resolve().parent

def source():
    s=(HERE/'root/usr/lib/lua/cudy/ssr-server.lua').read_text(encoding='utf-8')
    return s.replace('return M\n',(HERE/'unified-model.lua').read_text(encoding='utf-8')+'\nreturn M\n')

class UnifiedModelTests(unittest.TestCase):
    def setUp(self):
        self.lua=LuaRuntime(unpack_returned_tuples=True)
        self.model=self.lua.execute(source())

    def rows(self,scope='public',network='tcp,udp',**extra):
        row={'.name':'ordinary', 'type':'shadowsocks','enable':'1','server_port':'18388',
            'ss_password':'synthetic-ordinary-key','ss_method':'aes-256-gcm',
            'ss_network':network,'cudy_access':scope}
        row.update(extra)
        return self.lua.table_from([self.lua.table_from(row)])

    def test_all_seven_methods_and_transport(self):
        for method in self.model.methods.values():
            key=('AAECAwQFBgcICQoLDA0ODw==' if method=='2022-blake3-aes-128-gcm' else
                'AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=') if method.startswith('2022-') else 'ordinary-key'
            for network in ('tcp','udp','tcp,udp'):
                config=self.model.namespace_config(self.rows(network=network,ss_method=method,ss_password=key))
                self.assertEqual(config.inbounds[1].settings.method,method)
                self.assertEqual(config.inbounds[1].settings.network,network)
                self.assertEqual(config.inbounds[1].listen,'0.0.0.0')
                self.assertEqual(config.dns.servers[1],'198.18.255.1')
                self.assertIsNone(config.outbounds[1].streamSettings)

    def test_scope_guards_apply_after_conntrack_before_dnat(self):
        lan=self.lua.table_from({'device':'lanfixture','addresses':self.lua.table_from(['10.99.0.1'])})
        for scope in ('loopback','lan','public'):
            rules=self.model.rules(self.rows(scope=scope),lan,None)
            self.assertIn('priority -190',rules)
            self.assertIn('ct direction reply',rules)
            self.assertIn('priority -180',rules)
            self.assertIn('ct status dnat tcp dport 18388 accept',rules)
            if scope=='lan':self.assertIn('iifname "lanfixture" ip daddr 10.99.0.1',rules)
            if scope=='loopback':
                ingress=rules.split('chain ingress {')[1].split('chain local_ingress')[0]
                self.assertNotIn('dnat',ingress)
                self.assertIn('ip daddr 127.0.0.1',rules)

    def test_missing_lan_keeps_network_ingress_closed(self):
        rules=self.model.rules(self.rows(scope='lan'),self.lua.table_from({}),None)
        ingress=rules.split('chain ingress {')[1].split('chain local_ingress')[0]
        self.assertNotIn('dnat',ingress)
        self.assertIn('th dport 18388 counter drop',rules)

    def test_multiple_servers_and_collision_rejection(self):
        rows=self.rows();second=self.rows(scope='lan')[1];second['.name']='second';second.server_port='18389';rows[2]=second
        self.assertEqual(len(self.model.namespace_config(rows).inbounds),2)
        second.server_port='18388'
        with self.assertRaises(Exception):self.model.namespace_config(rows)

    def test_inactive_mapping_and_direct_peer_protection(self):
        rules=self.model.rules(self.rows(),None,self.lua.table_from({}))
        self.assertNotIn('dnat ip to',rules)
        self.assertIn('ip daddr 198.18.255.2 counter drop',rules)

    def test_retired_identity_never_reaches_ordinary_core(self):
        for extra in ({'cudy_private':'1'},{'cudy_access':'zerotier'},{'.name':'cudy_zt_private'}):
            with self.assertRaises(Exception):self.model.namespace_config(self.rows(**extra))

    def test_ui_only_three_scopes_and_legacy_fallback(self):
        self.lua.execute('''translate=function(v)return v end;ListValue='list';
local raw={accept_lan='1'}
s={};function s:option(kind,name,label)
 o={map={uci={get_all=function()return raw end}},values={}}
 function o:value(v,label)self.values[v]=label end
 return o
end''')
        self.lua.execute((HERE/'unified-access-ui.lua').read_text(encoding='utf-8'))
        o=self.lua.globals().o
        self.assertEqual(set(o['values'].keys()),{'loopback','lan','public'})
        self.assertEqual(o.cfgvalue(o,'ordinary'),'lan')
        self.assertEqual(o.validate(o,'public','ordinary'),'public')
        self.assertIsNone(o.validate(o,'zerotier','ordinary')[0])

def integration(root):
    runtime=root/'package/luci-app-cudy-ss/root'
    package=root/'feeds/helloworld/luci-app-ssr-plus'
    lua=LuaRuntime(unpack_returned_tuples=True)
    for base in (runtime,package/'luasrc'):
        for path in base.rglob('*'):
            if path.is_file():
                try:s=path.read_text(encoding='utf-8')
                except UnicodeDecodeError:continue
                if path.suffix=='.lua' or s.startswith('#!/usr/bin/lua'):
                    lua.execute('assert(loadstring(...))',s.removeprefix('#!/usr/bin/lua\n'))
    for relative in ('etc/config/cudy_ss','usr/libexec/cudy-ss-zt','usr/lib/cudy-ss/config.lua',
        'usr/libexec/cudy-ss-zt-watch','usr/libexec/cudy-ss-zt-guard','lib/upgrade/keep.d/cudy-ss',
        'usr/lib/cudy-ss/ss-zt.lua','usr/lib/cudy-ss/ss-server-migrate.lua'):
        assert not (runtime/relative).exists(),relative
    page=(package/'luasrc/model/cbi/shadowsocksr/server-config.lua').read_text(encoding='utf-8')
    assert 'cudy_private' not in page and 'cudy_zt_' not in page
    assert "o:value('public'" in page
    init=(package/'root/etc/init.d/shadowsocksr').read_text(encoding='utf-8')
    server=init.split('start_server() {',1)[1].split('\nstart_switch()',1)[0]
    assert 'gen_cudy_ss_server.lua' not in server
    assert 'cudy_ss owns these inbounds' in server
    assert '-m "$(cudy_ss_client_interfaces)"' in init
    print('PASS prepared unified runtime, UI and init syntax; retired private runtime absent')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--integration-root')
    args,rest=parser.parse_known_args()
    if args.integration_root:integration(Path(args.integration_root))
    else:unittest.main(argv=['test_unified_ss.py']+rest,verbosity=2)
