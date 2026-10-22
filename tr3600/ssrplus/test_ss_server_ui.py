"""Exercise the installed private validator and actual CBI approval snippet.

The CBI stub follows Flag/AbstractValue parse order, including unchecked flags,
empty optional values and writes staged before later validation failures.
"""
from pathlib import Path
import unittest

import test_profile as profile_tests


PROFILE = Path(__file__).resolve().parent
SECRET = 'synthetic-private-password-32chars'
APPROVAL = '0123456789abcdef|ztabcdef|10.42.0.2|10.42.0.0/24'


class PrivateServerUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        profile_tests.ProfileTests.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        profile_tests.ProfileTests.tearDownClass.__func__(cls)

    def page(self, configured=False, online=True, private=True):
        lua = profile_tests.ProfileTests.lua(self)
        model = lua.execute((PROFILE/'root/usr/lib/lua/cudy/ssr-server.lua').read_text())
        lua.globals().package.loaded['cudy.ssr-server'] = model
        lua.globals().configured = configured
        lua.globals().online = online
        lua.globals().private = private
        lua.globals().secret = SECRET
        lua.execute(r'''
sid = private and 'cudy_zt_private' or 'ordinary_server'
row={['.name']=sid,['.type']='server_config',type='shadowsocks',enable='0',
    server_port='8388',ss_method='aes-128-gcm',ss_network='tcp,udp'}
if private then row.cudy_private='1';row.cudy_access='zerotier' else row.cudy_access='loopback' end
if configured then
    row.ss_password=secret;row.cudy_zt_network_id='0123456789abcdef';row.cudy_zt_interface='ztabcdef'
    row.cudy_zt_listen='10.42.0.2';row.cudy_zt_subnet='10.42.0.0/24'
end
local function copy(source) local out={};for k,v in pairs(source) do out[k]=v end;return out end
original=copy(row);writes={};posted={};global_enable='0'
local u={}
function u:get_all(pkg,name) assert(pkg=='shadowsocksr' and name==sid);return copy(row) end
function u:get(pkg,name,key) assert(pkg=='shadowsocksr' and name==sid);return key and row[key] or row['.type'] end
function u:set(pkg,name,key,value)
    assert(pkg=='shadowsocksr' and name==sid,'A UI write escaped the selected server row')
    writes[#writes+1]={key,value};row[key]=value;return true
end
m={uci=u,save=true}
function m:formvalue(key) return posted[key] end
function translate(value) return value end
Flag='Flag';Value='Value';ListValue='ListValue';DummyValue='DummyValue'
s={fields={},children={}}
function s:option(kind,name,label)
    local field={map=m,option=name,kind=kind,rmempty=false,values={}}
    function field:value(value,label) self.values[value]=label or value end
    function field:validate(value,section)
        if self.kind==ListValue and next(self.values) and not self.values[value] then return nil,'Invalid choice' end
        return value
    end
    function field:write(section,value) return self.map.uci:set('shadowsocksr',section,self.option,value) end
    function field:remove(section) row[self.option]=nil end
    function field:cfgvalue(section) return row[self.option] end
    self.fields[name]=field;self.children[#self.children+1]=field;return field
end
for _,entry in ipairs({{Flag,'enable'},{ListValue,'type'},{Value,'server_port'},
    {Value,'ss_password'},{ListValue,'ss_method'},{ListValue,'ss_network'}}) do s:option(entry[1],entry[2]) end
s.fields.ss_method.validate=function(self,value,section)
    -- The patched private method field defers to the complete-candidate wrapper.
    if private then return value end
    local ok,result=pcall(require('cudy.ssr-server').method,value,posted['cbid.shadowsocksr.'..section..'.ss_password'] or row.ss_password)
    if not ok then return nil,result end
    return value
end
networks={}
if online then networks={{id='0123456789abcdef',portDeviceName='ztabcdef',type='PRIVATE',status='OK',assignedAddresses={'10.42.0.2/24'}}} end
package.loaded['luci.jsonc']={parse=function() return networks end}
luci={sys={exec=function(command)
    assert(command=='timeout 3 zerotier-cli -j listnetworks 2>/dev/null');return 'synthetic networks'
end}}
package.loaded['luci.sys']=luci.sys
function submit(values)
    posted=values;m.save=true
    for _,field in ipairs(s.children) do
        if field.kind~=DummyValue then
            local key='cbid.shadowsocksr.'..sid..'.'..field.option
            local value=posted[key]
            if field.kind==Flag then
                if posted['cbi.cbe.shadowsocksr.'..sid..'.'..field.option] then value=value and '1' or '0'
                else value=nil end
            end
            if value and #value>0 then
                local valid,problem=field:validate(value,sid)
                if valid then
                    if field.kind==Flag or valid~=field:cfgvalue(sid) then field:write(sid,valid) end
                else m.save=false end
            elseif field.rmempty then field:remove(sid)
            else m.save=false end
        end
    end
    if not m.save then row=copy(original) end -- Unsaved cursor changes do not commit.
    return m.save
end
''')
        lua.execute((PROFILE/'server-access-ui.lua').read_text())
        self.assertEqual(len(lua.globals().writes), 0, 'Opening a page wrote configuration')
        return lua

    def submit(self, lua, **changes):
        sid = lua.globals().sid
        values = {key: value for key, value in lua.globals().row.items() if not key.startswith('.')}
        values.update(_cudy_zt_approval=APPROVAL if values.get('cudy_zt_network_id') else '')
        values.update(changes)
        checked = values.pop('enable', '0') == '1'
        form = {'cbid.shadowsocksr.'+sid+'.'+key: value for key, value in values.items()}
        form['cbi.cbe.shadowsocksr.'+sid+'.enable'] = '1'
        if checked:
            form['cbid.shadowsocksr.'+sid+'.enable'] = '1'
        return lua.globals().submit(lua.table_from(form))

    def test_fresh_off_empty_credentials_remain_unapproved(self):
        lua = self.page()
        self.assertTrue(self.submit(lua, ss_password=''))
        row = lua.globals().row
        self.assertEqual(row.enable, '0')
        self.assertIsNone(row.ss_password)
        for key in ('network_id','interface','listen','subnet'):
            self.assertIsNone(row['cudy_zt_'+key])
        self.assertEqual(lua.globals().s.fields._cudy_zt_approval.cfgvalue(None, None), '')

    def test_one_connected_network_requires_explicit_approval(self):
        for changes in ({'enable':'1','ss_password':SECRET}, {'ss_password':SECRET}):
            with self.subTest(changes=changes):
                lua = self.page()
                self.assertFalse(self.submit(lua, **changes))
                self.assertIsNone(lua.globals().row.cudy_zt_network_id)
                self.assertFalse(any(item[1].startswith('cudy_zt_') for item in lua.globals().writes.values()))

    def test_explicit_approval_preserves_off_and_global_switch(self):
        lua = self.page()
        self.assertTrue(self.submit(lua, ss_password=SECRET, _cudy_zt_approval=APPROVAL))
        row = lua.globals().row
        self.assertEqual(row.enable, '0')
        self.assertEqual(lua.globals().global_enable, '0')
        self.assertEqual(row.cudy_zt_network_id, '0123456789abcdef')
        self.assertEqual(row.cudy_zt_interface, 'ztabcdef')
        self.assertEqual(row.cudy_zt_listen, '10.42.0.2')
        self.assertEqual(row.cudy_zt_subnet, '10.42.0.0/24')
        self.assertIsNone(row._cudy_zt_approval, 'Virtual approval selector was persisted')

    def test_enable_and_new_approval_validate_complete_form_before_writes(self):
        lua = self.page()
        self.assertTrue(self.submit(lua, enable='1', ss_password=SECRET, _cudy_zt_approval=APPROVAL))
        self.assertEqual(lua.globals().row.enable, '1')
        self.assertEqual(lua.globals().global_enable, '0')

    def test_existing_offline_approval_can_be_retained_or_enabled(self):
        for enable in ('0','1'):
            with self.subTest(enable=enable):
                lua = self.page(configured=True, online=False)
                self.assertTrue(self.submit(lua, enable=enable))
                self.assertEqual(lua.globals().row.cudy_zt_network_id, '0123456789abcdef')
                self.assertFalse(any(item[1].startswith('cudy_zt_') for item in lua.globals().writes.values()))

    def test_new_unknown_or_offline_scope_is_rejected(self):
        for online, approval in ((False, APPROVAL), (True, APPROVAL.replace('10.42.0.0/24','0.0.0.0/0'))):
            with self.subTest(online=online, approval=approval):
                lua = self.page(online=online)
                self.assertFalse(self.submit(lua, ss_password=SECRET, _cudy_zt_approval=approval))
                self.assertIsNone(lua.globals().row.cudy_zt_network_id)

    def test_private_port_password_cipher_and_transport_match_runtime(self):
        bad = [('server_port', str(port)) for port in (1,1023,1053,10808,10809,10810,12345,65536)]
        bad += [('ss_password', value) for value in ('short','x'*23,'x'*129,'x'*24+'\n')]
        bad += [('ss_method','xchacha20-ietf-poly1305'),('ss_network','udp,tcp')]
        for key, value in bad:
            with self.subTest(key=key, value=value):
                lua = self.page(configured=True)
                self.assertFalse(self.submit(lua, **{key:value}))
        for password in ('x'*24,'x'*128,'密'*8):
            with self.subTest(password=password):
                lua = self.page(configured=True)
                self.assertTrue(self.submit(lua, ss_password=password))

    def test_fresh_off_private_port_is_still_checked(self):
        lua = self.page()
        self.assertFalse(self.submit(lua, server_port='1053', ss_password=''))

    def test_generic_server_keeps_ordinary_password_rules(self):
        lua = self.page(private=False)
        self.assertIsNone(lua.globals().s.fields._cudy_zt_approval)
        self.assertTrue(self.submit(lua, ss_password='ordinary-short-password', _cudy_zt_approval=''))


if __name__ == '__main__':
    unittest.main(verbosity=2)
