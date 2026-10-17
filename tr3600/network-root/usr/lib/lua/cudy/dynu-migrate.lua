-- Idempotent migration; never read or log account/password values.
local M={}
function M.apply(u)
    local sections={}
    u:foreach('ddns','service',function(s)
        local provider=s.service_name
        if (provider=='dynu.com' or provider=='cudy-dynu-https')
            and s.use_ipv6~='1' and (s.update_url or '')==''
            and (s.update_script or '')=='' and s.cudy_https_revision~='1' then
            sections[#sections+1]=s['.name']
        end
    end)
    if #sections==0 then return 0 end
    local options={service_name='cudy-dynu-https',ip_source='web',
        ip_url='https://ipv4.icanhazip.com',bind_network='wan',use_https='1',
        cacert='/etc/ssl/certs/ca-certificates.crt',use_ipv6='0',force_ipversion='1',
        check_interval='10',check_unit='minutes',force_interval='72',force_unit='hours',
        retry_interval='60',retry_unit='seconds',retry_max_count='5',
        use_logfile='0',use_syslog='2',cudy_https_revision='1'}
    for _,name in ipairs(sections)do
        for key,value in pairs(options)do assert(u:set('ddns',name,key,value))end
    end
    if not u:get('ddns','global')then assert(u:section('ddns','ddns','global',{}))end
    assert(u:set('ddns','global','use_curl','1'))
    assert(u:commit('ddns'))
    return #sections
end
return M
