from pathlib import Path
import copy
import sys
import unittest

base=Path(__file__).resolve().parent
import yaml
from lupa.lua51 import LuaRuntime

def runtime():
 lua=LuaRuntime(unpack_returned_tuples=True)
 def convert(v):
  if isinstance(v,dict):return lua.table_from({k:convert(w) for k,w in v.items()})
  if isinstance(v,list):return lua.table_from([convert(w) for w in v])
  return v
 lua.globals().python_yaml_load=lambda s:convert(yaml.safe_load(s))
 lua.execute("package.preload.lyaml=function()return {load=python_yaml_load} end")
 module=lua.execute((base/'yaml_nodes.lua').read_text(encoding='utf-8'))
 return lua,module,convert

class ConverterTests(unittest.TestCase):
 def setUp(self):
  self.lua,self.module,self.convert=runtime()
  self.raw=(base/'yaml-nodes-fixture.yaml').read_text(encoding='utf-8')
  self.doc=yaml.safe_load(self.raw)
 def test_three_protocol_fields(self):
  nodes=self.module.parse(self.raw,None)
  self.assertEqual(len(nodes),3)
  self.assertEqual([nodes[i].v2ray_protocol for i in (1,2,3)],['anytls','vmess','hysteria2'])
  self.assertEqual(nodes[1].tls_host,'tls.example.invalid')
  self.assertEqual(nodes[1].insecure,'0')
  self.assertEqual(nodes[2].ws_path,'/example')
  self.assertEqual(nodes[2].ws_host,'websocket.example.invalid')
  self.assertEqual(nodes[3].hy2_auth,'synthetic-hysteria2-password')
  self.assertEqual(nodes[3].salamander,'synthetic-obfs-password')
  self.assertEqual(nodes[3].downlink_capacity,'200')
  self.assertIsNone(nodes[1].dns)
 def test_dedup_and_determinism(self):
  self.doc['proxies'].append(copy.deepcopy(self.doc['proxies'][0]))
  a=self.module.parse(yaml.safe_dump(self.doc),None)
  b=self.module.parse(self.raw,None)
  self.assertEqual(len(a),3)
  self.assertEqual(self.module.signature(a[1]),self.module.signature(b[1]))
 def test_pinned_certificate_and_legacy_ws_aliases(self):
  nodes=self.module.parse(self.raw,None)
  self.assertEqual(nodes[1].tls_CertSha,'00'*32)
  self.doc['proxies'][0]['fingerprint']='AA:'*31+'AA'
  nodes=self.module.parse(yaml.safe_dump(self.doc),None)
  self.assertEqual(nodes[1].tls_CertSha,'aa'*32)
  self.doc['proxies'][1]['ws-path']='/conflict'
  with self.assertRaisesRegex(Exception,'conflicting_ws_path'):
   self.module.parse(yaml.safe_dump(self.doc),None)
 def test_inline_provider_and_http_ua(self):
  child=yaml.safe_dump({'proxies':self.doc['proxies'][1:]})
  main={'proxy-providers':{'one':{'type':'inline','payload':[self.doc['proxies'][0]]},'two':{'type':'http','url':'https://fixture.invalid/provider','header':{'User-Agent':['mihomo/1.18.0']}}}}
  calls=[]
  def fetch(url,ua):calls.append((url,ua));return child
  self.assertEqual(len(self.module.parse(yaml.safe_dump(main),fetch)),3)
  self.assertEqual(calls,[('https://fixture.invalid/provider','mihomo/1.18.0')])
 def test_rejects_unsupported_without_partial_success(self):
  self.doc['proxies'].append({'type':'unsupported','name':'private token never printed'})
  with self.assertRaisesRegex(Exception,'yaml_nodes:unsupported_type:unsupported'):
   self.module.parse(yaml.safe_dump(self.doc),None)
 def test_rejects_bad_tls_transport_uuid(self):
  for field,value in [('uuid','bad'),('network','unknown'),('ws-opts',{'headers':{'Authorization':'secret-not-in-error'}})]:
   doc=copy.deepcopy(self.doc);doc['proxies'][1][field]=value
   with self.assertRaises(Exception) as ctx:self.module.parse(yaml.safe_dump(doc),None)
   self.assertNotIn('secret-not-in-error',str(ctx.exception))
 def test_provider_failure_not_partial_success(self):
  self.doc['proxy-providers']={'bad':{'type':'http','url':'https://fixture.invalid/unavailable'}}
  with self.assertRaises(Exception):self.module.parse(yaml.safe_dump(self.doc),lambda *args:'')
 def test_ipv6_and_special_password(self):
  p=copy.deepcopy(self.doc['proxies'][0]);p['server']='[2001:db8::123]';p['password']='a:@$`\\"'
  n=self.module.convert(self.convert(p));self.assertEqual(n.server,'2001:db8::123');self.assertEqual(n.password,p['password'])
 def test_large_or_empty_yaml(self):
  for raw in ['','proxies: []','x'*(4194304+1)]:
   with self.assertRaises(Exception):self.module.parse(raw,None)
 def test_hysteria2_zero_bandwidth(self):
  p=self.doc['proxies'][2];p['up']=0;p['down']=0
  node=self.module.convert(self.convert(p))
  self.assertEqual(node.uplink_capacity,'0');self.assertEqual(node.downlink_capacity,'0')

if __name__=='__main__':unittest.main()
