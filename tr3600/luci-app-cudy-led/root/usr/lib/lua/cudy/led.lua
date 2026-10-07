-- Pure state machine. No UCI, network, filesystem or LED access.
local M = {}
local function minute(v)
    if type(v) ~= 'string' then return end
    local h,m=v:match('^(%d%d):(%d%d)$')
    h,m=tonumber(h),tonumber(m)
    if h and m and h < 24 and m < 60 then return h*60+m end
end
function M.config(raw)
    raw=raw or {}
    local c={mode=raw.mode or 'status',night=raw.night or '0',
        first=minute(raw.night_start or '23:00'),last=minute(raw.night_end or '07:00')}
    if not ({status=true,default=true,off=true})[c.mode] or
       (c.night ~= '0' and c.night ~= '1') or not c.first or not c.last or c.first == c.last then
        return nil,'指示灯模式或时间设置无效'
    end
    return c
end
function M.night(c,s)
    if c.night ~= '1' or not s.clock_ok or type(s.minute) ~= 'number' then return false end
    if c.first < c.last then return s.minute >= c.first and s.minute < c.last end
    return s.minute >= c.first or s.minute < c.last
end
function M.frame(state,night)
    if state == 'release' then return {release=true,state=state} end
    local out={state=state,white='off',red='off'}
    if state == 'offline' then out.red='on'
    elseif state == 'failed' then out.red='slow'
    elseif state == 'healthy' then out.white='on'
    elseif state == 'unknown' then out.white='wait' end
    if night then out.white='off' end -- fault red remains visible
    return out
end
local function reset(m,s)
    m.id=s.id; m.mode=s.mode; m.since=s.now
    m.ok=0; m.bad=0; m.last=nil; m.state='unknown'; m.offline=nil
end
function M.step(m,c,s)
    if s.suspended or s.failsafe or s.board ~= 'cudy,tr3600-v1' then return M.frame('release') end
    if c.mode == 'default' then return M.frame('release') end
    if c.mode == 'off' then return M.frame('off') end
    if m.id ~= s.id or m.mode ~= s.mode or not m.since or s.now < m.since then reset(m,s) end
    local state='unknown'
    if s.uplink == 1 then
        m.offline=m.offline or s.now
        m.ok=0; m.bad=0; m.state='unknown'
        if s.now-m.offline >= 10 then state='offline' end
    else
        if m.offline then reset(m,s) end
        m.offline=nil
        if s.uplink == 0 and not s.busy and s.id and s.id ~= '' and
           (s.mode == 'direct' or s.mode == 'split' or s.mode == 'global' or s.mode == 'gfw') then
            local p=s.sample
            if s.mode ~= 'direct' and s.ready == false and s.now-m.since >= 180 then
                -- A dead core is a local fault, independent of the probe toggle.
                p={id=s.id,key='not-ready:'..math.floor(s.now/60),at=s.now,result=false}
            elseif s.mode ~= 'direct' and not s.ready then p=nil end
            local ttl=type(p)=='table' and p.result == false and 660 or 150
            if type(p) == 'table' and p.id == s.id and type(p.at) == 'number' and
               p.at >= m.since and p.at <= s.now and s.now-p.at <= ttl and
               type(p.key) == 'string' and (p.result == true or p.result == false) then
                if p.key ~= m.last then
                    m.last=p.key
                    if p.result then
                        m.ok=m.ok+1; m.bad=0
                        if m.ok >= 2 then m.state='healthy' end
                    else
                        m.bad=m.bad+1; m.ok=0
                        -- One failure clears healthy; confirmed fault survives one recovery round.
                        if m.state ~= 'failed' then m.state='unknown' end
                        if m.bad >= 3 then m.state='failed' end
                    end
                end
                state=m.state
            else m.ok=0; m.bad=0; m.state='unknown' end
        else m.ok=0; m.bad=0; m.state='unknown' end
    end
    return M.frame(state,M.night(c,s))
end
return M
