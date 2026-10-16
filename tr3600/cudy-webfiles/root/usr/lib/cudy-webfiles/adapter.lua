-- Read-only adapter: never calls enable/reconcile/guard/eject or UCI commit.
local fs = require('nixio.fs')
local u = require('uci').cursor()
local engine = require('cudy.usb')
local e = require('cudy.usb-runtime').new(u)
local json = require('luci.jsonc')
local result = {board=(fs.readfile('/tmp/sysinfo/board_name') or ''):gsub('%s+$',''), volumes={}}
local ok, err = pcall(function()
  assert(result.board == 'cudy,tr3600-v1', 'Only Cudy TR3600 v1 is supported')
  -- Modern LuCI no longer ships luci.model.network. Read netifd's live
  -- LAN status through the fixed, read-only ubus command instead.
  local pipe = assert(io.popen('/bin/ubus call network.interface.lan status 2>/dev/null'))
  local data = pipe:read(65536) or ''
  pipe:close()
  local lan = assert(json.parse(data), 'Cannot read LAN status from ubus')
  assert(lan.up == true and not lan.pending, 'LAN is not ready')
  result.lan = assert(lan['ipv4-address'] and lan['ipv4-address'][1] and
    lan['ipv4-address'][1].address, 'No LAN IPv4 address')
  result.iface = assert(lan.l3_device, 'No LAN interface')
  local status = engine.status(u,e)
  for _, row in ipairs(status.volumes) do
    local conf = u:get_all('cudy_usb', row.id)
    if row.ready and conf and (conf.read_only=='0' or conf.read_only=='1') then
      local mount = e.mount_at(row.target)
      if mount then
        result.volumes[#result.volumes+1] = {
          id=row.id, uuid=engine.uuid(row.uuid), target=row.target,
          device=mount.device, fstype=mount.fstype, readOnly=row.read_only,
          share=row.share, ready=true
        }
      end
    end
  end
end)
if not ok then io.stderr:write(tostring(err)..'\n'); os.exit(1) end
-- Encode the list explicitly: luci.jsonc may represent an empty Lua table as {}.
local rows={}
for _,v in ipairs(result.volumes) do rows[#rows+1]=json.stringify(v) end
print('{"board":'..json.stringify(result.board)..',"lan":'..json.stringify(result.lan)..
  ',"iface":'..json.stringify(result.iface)..',"volumes":['..table.concat(rows,',')..']}')
