#!/bin/sh
set -eu
umask 077
[ "$(cat /tmp/sysinfo/board_name 2>/dev/null)" = cudy,tr3600-v1 ] || exit 0
mkdir -p /etc/cudy-ss /var/lock
chmod 700 /etc/cudy-ss
# The helper closes access when migration is incomplete or the row is invalid.
/usr/libexec/cudy-ss-zt-guard
lua - <<'LUA'
local u=require('uci').cursor()
local path='/etc/cudy-ss/guard.nft'
local old=u:get_all('firewall','cudy_ss_guard')
if old then
    assert(old['.type']=='include' and old.path==path,
        'Conflicting firewall include; refusing to overwrite')
end
assert(u:set('firewall','cudy_ss_guard','include'))
for k,v in pairs({enabled='1',type='nftables',position='ruleset-pre',path=path}) do
    assert(u:set('firewall','cudy_ss_guard',k,v))
end
assert(u:commit('firewall'))
LUA
/etc/init.d/cudy_ss enable
