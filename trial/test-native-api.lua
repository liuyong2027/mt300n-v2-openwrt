local root,dir=arg[1],assert(arg[2])
package.path=root..'/usr/lib/lua/?.lua;'..root..'/usr/lib/lua/?/init.lua;'..package.path
package.cpath=root..'/usr/lib/lua/?.so;'..package.cpath
local fs=require('nixio.fs')
local uci=require('uci')
assert(fs.mkdirr(dir))
assert(fs.chmod(dir,'rwx------'))
local state=dir..'/state'
assert(fs.mkdirr(state))
assert(fs.chmod(state,'rwx------'))
local path=dir..'/api_probe'
local file=assert(io.open(path,'wb'))
assert(file:write("config sample 'original'\n\toption value 'fixture-only'\n"))
assert(file:close())
assert(fs.chmod(path,'rw-------'))
local cursor=uci.cursor(dir,state)
assert(cursor:load('api_probe'))
assert(cursor:set('api_probe','new_include','include'))
assert(cursor:set('api_probe','new_include','type','script'))
assert(cursor:set('api_probe','original','list',{'one','two'}))
assert(cursor:commit('api_probe'))
local check=uci.cursor(dir,state)
assert(check:get('api_probe','new_include')=='include')
assert(check:get('api_probe','new_include','type')=='script')
local list=check:get('api_probe','original','list')
assert(type(list)=='table' and #list==2 and list[2]=='two')
assert(fs.unlink(path))
print('Actual nixio symbolic permissions and native UCI create/list/commit: passed')

