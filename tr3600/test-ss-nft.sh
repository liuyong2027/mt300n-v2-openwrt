#!/bin/sh
set -eu
# Called inside an isolated host network namespace; no router is modified.
kit=$(pwd)
temp=$(mktemp -d /tmp/cudy-ss-nft-XXXXXX)
trap 'rm -f "$temp/old.nft" "$temp/new.nft" "$temp/bridge.nft"; rmdir "$temp"' EXIT HUP INT TERM
lua5.1 - "$temp" "$kit" <<'LUA'
local base,kit=arg[1],arg[2]
local M=dofile(kit..'/tr3600/luci-app-cudy-ss/root/usr/lib/mango/ss-zt.lua')
local function raw(port) return {enabled='1',port=tostring(port),method='aes-128-gcm',password=string.rep('N',32),listen='192.168.77.6',subnet='192.168.77.0/24',interface='ztfixture01',network_id='0123456789abcdef'} end
for name,text in pairs({old=M.guard(M.validate(raw(8388))),new=M.guard(M.validate(raw(8389))),bridge=M.bridge(raw(8388),raw(8389))}) do local f=assert(io.open(base..'/'..name..'.nft','w'));f:write(text);f:close() end
LUA
ip link set lo up
ip addr add 192.168.77.6/32 dev lo
ip link add ztfixture01 type dummy
ip link set ztfixture01 up
for name in old bridge new; do nft -c -f "$temp/$name.nft"; nft -f "$temp/$name.nft"; done
nft -f "$temp/new.nft"
python3 - <<'PY'
import socket
with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as s:
    for port in (8388,8389): s.sendto(b'fixture',('192.168.77.6',port))
PY
rules=$(nft list table inet cudy_ss_retired)
printf '%s\n' "$rules" | grep -E 'dport 8388 .*counter packets 1 bytes [1-9][0-9]* drop'
printf '%s\n' "$rules" | grep -E 'dport 8389 .*counter packets 1 bytes [1-9][0-9]* drop'
nft destroy table inet cudy_ss_retired
nft list table inet cudy_ss_zt | grep 'dport 8389'
echo 'PASS real nft atomic old/new endpoint guards and rejected wrong-interface UDP during port transition'
