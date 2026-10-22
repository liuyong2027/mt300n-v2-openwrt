#!/usr/bin/lua
local u=require('uci').cursor()
local json=require('luci.jsonc')
local model=require('cudy.ssr-server')
local sid=arg[1]
assert(type(sid)=='string' and sid:match('^[%w_]+$'), 'Invalid server section')
assert(u:get('shadowsocksr',sid)=='server_config', 'Missing server_config')
local raw=assert(u:get_all('shadowsocksr',sid))
raw['.name']=sid
print(json.stringify(model.config(raw)))
