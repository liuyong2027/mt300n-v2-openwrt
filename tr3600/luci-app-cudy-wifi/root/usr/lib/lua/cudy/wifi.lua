-- Shared configuration engine. The caller supplies private storage and fixed commands.
local M = {}
local wifi_fields = {'ssid','key','encryption','ieee80211w','ieee80211k',
    'rrm_neighbor_report','rrm_beacon_report','bss_transition'}
local steer_fields = {'enabled','network','local_mode','syslog','debug_level',
    'ssid_list','band_steering_interval','band_steering_min_snr',
    'assoc_steering','probe_steering','load_kick_enabled',
    'min_snr','min_connect_snr','roam_trigger_snr','roam_scan_snr'}

local function copy(v)
    if type(v) ~= 'table' then return v end
    local out = {}; for k,x in pairs(v) do out[k] = copy(x) end; return out
end
local function lan(v)
    return v == 'lan' or (type(v) == 'table' and #v == 1 and v[1] == 'lan')
end
local function ap(u, name, band, active)
    if type(name) ~= 'string' or not name:match('^[%w_]+$') then return end
    local s = u:get_all('wireless',name)
    if not s or s['.type'] ~= 'wifi-iface' or s.mode ~= 'ap' or not lan(s.network) then return end
    local d = u:get_all('wireless',s.device)
    if not d or d['.type'] ~= 'wifi-device' or d.band ~= band then return end
    if active and (s.disabled == '1' or d.disabled == '1') then return end
    return s
end
local function select_ap(u, requested, band)
    if requested and requested ~= '' then return requested end
    local found = {}
    u:foreach('wireless','wifi-iface',function(s)
        if ap(u,s['.name'],band,true) then found[#found+1] = s['.name'] end
    end)
    if #found == 1 then return found[1] end
end
local function snapshot(u, config, section, fields)
    local values = {}
    for _,key in ipairs(fields) do
        local value = u:get(config,section,key)
        if value == nil then values[key] = false else values[key] = copy(value) end
    end
    return values
end
local function restore(u, config, section, values, fields)
    for _,key in ipairs(fields) do
        if values[key] == false then u:delete(config,section,key)
        else assert(u:set(config,section,key,copy(values[key]))) end
    end
end
local function valid_values(values, fields)
    if type(values) ~= 'table' then return false end
    for _,key in ipairs(fields) do
        local v = values[key]
        if v ~= false and type(v) ~= 'string' and type(v) ~= 'table' then return false end
        if type(v) == 'table' then for _,s in pairs(v) do if type(s) ~= 'string' then return false end end end
    end
    return true
end
local function valid_backup(u,b)
    return type(b) == 'table' and b.version == 1 and b.ap2g ~= b.ap5g and
        ap(u,b.ap2g,'2g',false) and ap(u,b.ap5g,'5g',false) and
        type(b.steer) == 'string' and u:get('usteer',b.steer) == 'usteer' and
        valid_values(b.two,wifi_fields) and valid_values(b.five,wifi_fields) and
        valid_values(b.steering,steer_fields)
end
local function state(u,two,five,steer)
    return {version=1,ap2g=two,ap5g=five,steer=steer,
        two=snapshot(u,'wireless',two,wifi_fields),five=snapshot(u,'wireless',five,wifi_fields),
        steering=snapshot(u,'usteer',steer,steer_fields)}
end
local function put_state(u,b)
    restore(u,'wireless',b.ap2g,b.two,wifi_fields)
    restore(u,'wireless',b.ap5g,b.five,wifi_fields)
    restore(u,'usteer',b.steer,b.steering,steer_fields)
    assert(u:commit('wireless')); assert(u:commit('usteer'))
end
local function activate(env,boot)
    if boot then return true end
    return env.run('/sbin/wifi reload') and env.run('/etc/init.d/usteer restart')
end

function M.apply(u,env,boot)
    if env.board() ~= 'cudy,tr3600-v1' then return nil,'仅支持 Cudy TR3600 v1' end
    local c = u:get_all('cudy_wifi','main') or {}
    if c.enabled ~= '0' and c.enabled ~= '1' then return nil,'双频合一开关配置无效' end
    local backup,problem = env.load()
    if problem then return nil,'原无线配置备份无法读取，未修改网络' end
    if backup and not valid_backup(u,backup) then return nil,'原无线配置备份与当前接口不匹配，未修改网络' end
    if c.enabled == '0' then
        if not backup then return true,'双频合一已关闭，原无线配置保持不变' end
        local live = state(u,backup.ap2g,backup.ap5g,backup.steer)
        local ok = pcall(function() put_state(u,backup); assert(activate(env,boot)) end)
        if not ok then
            pcall(function() put_state(u,live); activate(env,boot) end)
            return nil,'恢复无线配置失败，已尝试恢复操作前配置；原备份保留'
        end
        if not env.erase() then return nil,'无线配置已恢复，但原备份清理失败，请重试' end
        return true,'已恢复合一前的两个独立无线网络'
    end
    local two = select_ap(u,c.ap2g,'2g')
    local five = select_ap(u,c.ap5g,'5g')
    if not two or not five or two == five or not ap(u,two,'2g',true) or not ap(u,five,'5g',true) then
        return nil,'请先配置并启用两个频段的局域网接入点，再选择对应接口'
    end
    if backup and (backup.ap2g ~= two or backup.ap5g ~= five) then
        return nil,'请先关闭双频合一，再更换接入点'
    end
    local ssid = c.ssid
    if type(ssid) ~= 'string' or #ssid < 1 or #ssid > 32 or ssid:find('[%z\1-\31\127]') then
        return nil,'无线名称须为 1–32 字节，不能包含控制字符'
    end
    local conflict = false
    u:foreach('wireless','wifi-iface',function(s)
        if s.mode == 'ap' and s['.name'] ~= two and s['.name'] ~= five and s.ssid == ssid then conflict = true end
    end)
    if conflict then return nil,'共同无线名称已被其他接入点使用，请选择独立名称' end
    local encryption = c.encryption or 'sae-mixed'
    if encryption ~= 'psk2' and encryption ~= 'sae-mixed' and encryption ~= 'sae' then return nil,'不支持此加密方式' end
    local key = c.key
    if not key or key == '' then key = u:get('wireless',five,'key') end
    if type(key) ~= 'string' or #key < 8 or #key > 63 or key:find('[^ -~]') then
        return nil,'请设置 8–63 位可打印英文字符密码；留空仅可沿用有效的 5 GHz 密码'
    end
    if c.steering ~= '0' and c.steering ~= '1' then return nil,'频段引导开关配置无效' end
    if not env.available() then return nil,'频段引导组件未安装，未修改网络' end
    local sections = {}
    u:foreach('usteer','usteer',function(s) sections[#sections+1] = s['.name'] end)
    if #sections ~= 1 then return nil,'频段引导配置须恰好包含一个服务配置段' end
    local steer = sections[1]
    local live = state(u,two,five,steer)
    if not backup and not env.save(live) then return nil,'无法保存原无线配置，未修改网络' end
    local ok = pcall(function()
        for _,name in ipairs({two,five}) do
            local values = {ssid=ssid,key=key,encryption=encryption,
                ieee80211w=encryption == 'sae' and '2' or (encryption == 'sae-mixed' and '1' or '0'),
                ieee80211k=c.steering,rrm_neighbor_report=c.steering,
                rrm_beacon_report=c.steering,bss_transition=c.steering}
            for field,value in pairs(values) do assert(u:set('wireless',name,field,value)) end
        end
        local values = {enabled=c.steering,network='lan',local_mode='1',syslog='1',debug_level='1',
            ssid_list={ssid},band_steering_interval=c.steering == '1' and '30000' or '0',
            band_steering_min_snr='-60',assoc_steering='0',probe_steering='0',load_kick_enabled='0',
            min_snr='0',min_connect_snr='0',roam_trigger_snr='0',roam_scan_snr='0'}
        for field,value in pairs(values) do assert(u:set('usteer',steer,field,value)) end
        assert(u:commit('wireless')); assert(u:commit('usteer'))
        assert(activate(env,boot))
    end)
    if not ok then
        local restored = pcall(function() put_state(u,live); assert(activate(env,boot)) end)
        if not backup and restored then env.erase() end
        return nil,'应用失败，已尝试恢复操作前配置，请检查系统日志'
    end
    return true,c.steering == '1' and '双频合一和频段引导已启用' or '双频合一已启用，频段引导已关闭'
end
return M
