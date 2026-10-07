#!/bin/bash
set -Eeuo pipefail
root=$(realpath "$1")
module=tr3600/luci-app-cudy-ss/root/usr/lib/mango/ss-zt.lua
transaction=tr3600/luci-app-cudy-ss/root/usr/lib/mango/ss-transaction.lua
export CUDY_TEST_ROOT="$root" LUA_CPATH="$root/usr/lib/lua/?.so" LUA_PATH="$root/usr/lib/lua/?.lua;$root/usr/lib/lua/?/init.lua"
qemu-aarch64-static -L "$root" "$root/usr/bin/lua" tr3600/test-ss.lua "$module"
qemu-aarch64-static -L "$root" "$root/usr/bin/lua" tr3600/test-ss-settings.lua "$module"
qemu-aarch64-static -L "$root" "$root/usr/bin/lua" tr3600/test-ss-setup.lua "$module"
qemu-aarch64-static -L "$root" "$root/usr/bin/lua" tr3600/test-ss-transaction.lua "$transaction"
export CUDY_SS_TEST_DIR="$(mktemp -d /tmp/cudy-ss-XXXXXX)" CUDY_SS_SOURCE="$PWD/tr3600"
qemu-aarch64-static -L "$root" "$root/usr/bin/lua" tr3600/test-ss-real.lua
test "$(stat -c %a "$CUDY_SS_TEST_DIR/config/cudy_ss")" = 600
test "$(stat -c %a "$CUDY_SS_TEST_DIR/run")" = 700
for path in usr/libexec/cudy-ss-zt-guard usr/libexec/cudy-ss-zt-watch usr/libexec/cudy-ss-job etc/init.d/cudy_ss etc/uci-defaults/95-cudy-ss; do
    qemu-aarch64-static -L "$root" "$root/bin/busybox" sh -n "tr3600/luci-app-cudy-ss/root/$path"
done
for path in usr/libexec/cudy-ss-zt usr/libexec/cudy-ss-worker usr/libexec/rpcd/cudy.ss; do
    qemu-aarch64-static -L "$root" "$root/usr/bin/lua" -e "assert(loadfile('tr3600/luci-app-cudy-ss/root/$path'))"
done
mkdir -p reports/ss-configs
lua5.1 - "$module" <<'LUA'
local M=dofile(arg[1]);local n=0
local function stringify(v)
 if type(v)=='table' then
  local array=#v>0;local parts={}
  if array then for _,x in ipairs(v) do parts[#parts+1]=stringify(x) end
  else for k,x in pairs(v) do parts[#parts+1]=string.format('%q',k)..':'..stringify(x) end end
  return (array and '[' or '{')..table.concat(parts,',')..(array and ']' or '}')
 elseif type(v)=='string' then return string.format('%q',v)
 else return tostring(v) end
end
for _,method in ipairs({'aes-128-gcm','aes-256-gcm','chacha20-ietf-poly1305'}) do
 local c=M.validate({enabled='1',port='8388',method=method,password=string.rep('K',32),listen='192.168.77.6',subnet='192.168.77.0/24',interface='ztfixture01',network_id='0123456789abcdef'})
 local b={inbounds={{tag='loopback',listen='127.0.0.1',port=10808,protocol='socks',settings={udp=true}}},outbounds={{tag='direct',protocol='freedom'},{tag='proxy',protocol='freedom'}},routing={rules={{type='field',domain={'domain:example.com'},outboundTag='proxy'}}}}
 M.augment(b,c,true)
 local f=assert(io.open('reports/ss-configs/'..method..'.json','w'));f:write(stringify(b));f:close();n=n+1
end
assert(n==3)
LUA
for path in reports/ss-configs/*.json; do
    XRAY_LOCATION_ASSET="$root/usr/share/xray" qemu-aarch64-static -L "$root" "$root/usr/bin/xray" run -test -config "$path"
done
python3 - <<'PY'
from pathlib import Path
import json
assert len(list(Path('reports/ss-configs').glob('*.json')))==3
Path('reports/ss-validation.json').write_text(json.dumps({'actual_arm64_settings_and_scope':'passed','actual_arm64_worker_uci_private_backup':'passed; service/nft substituted in lifecycle fixture','actual_arm64_cipher_configs':3,'network_namespace_nft':'separate mandatory test','hardware_upgrade_reboot':'pending'},indent=2))
PY
