local M = dofile(assert(arg[1], 'transaction module path required'))
local count = 0
local secret = 'DO-NOT-EXPOSE-CANDIDATE-SECRET'
local function test(name, fn)
    fn()
    count = count + 1
    print('PASS ' .. name)
end
local function same(a, b)
    assert(#a == #b, 'unexpected callback count: ' .. table.concat(a, ','))
    for i, value in ipairs(a) do assert(value == b[i], 'unexpected callback order') end
end
local function harness(fail, thrown)
    local old = {enabled=true, port=8388, password='PRIVATE-OLD'}
    local candidate = {enabled=true, port=8389, password=secret}
    local calls, env = {}, {}
    local counts = {}
    local function result(name)
        counts[name] = (counts[name] or 0) + 1
        local key = name .. ':' .. counts[name]
        if fail == key or fail == name then
            if thrown then error(secret) end
            return false
        end
        return true
    end
    env.snapshot = function()
        calls[#calls+1] = 'snapshot'
        if not result('snapshot') then return nil end
        return old
    end
    env.protect = function(previous, next)
        assert(previous == old and next == candidate)
        calls[#calls+1] = 'protect'
        return result('protect')
    end
    for _, name in ipairs({'stage','commit','guard','verify'}) do
        local step = name
        env[step] = function(next)
            assert(next == candidate)
            calls[#calls+1] = step
            return result(step)
        end
    end
    for _, name in ipairs({'restore','rollback_guard','rollback_verify'}) do
        local step = name
        env[step] = function(previous)
            assert(previous == old)
            calls[#calls+1] = step
            return result(step)
        end
    end
    env.reload = function()
        calls[#calls+1] = 'reload'
        return result('reload')
    end
    env.finalize = function(value)
        assert(value == candidate or value == old)
        calls[#calls+1] = value == old and 'finalize-old' or 'finalize'
        return result('finalize')
    end
    return env, candidate, old, calls, counts
end
local sequence = {'snapshot','stage','protect','commit','guard','reload','verify','finalize'}
local recovery = {'restore','rollback_guard','reload','rollback_verify','finalize-old'}
local function expected(before, rollback)
    local out = {}
    for _, step in ipairs(sequence) do out[#out+1] = step; if step == before then break end end
    if rollback then for _, step in ipairs(recovery) do out[#out+1] = step end end
    return out
end
local function no_secret(message)
    assert(type(message)=='string' and not message:find(secret,1,true))
end

test('success preserves stage protection commit guard reload verification cleanup order',function()
    local env, candidate, _, calls = harness()
    local ok, message, rolled = M.apply(candidate,env)
    assert(ok and message=='applied' and rolled==nil)
    same(calls,sequence)
end)
for _, step in ipairs({'snapshot','stage'}) do
    for _, thrown in ipairs({false,true}) do
        test(step .. ' failure has no live mutation or recovery',function()
            local env, candidate, _, calls = harness(step,thrown)
            local ok, message, rolled = M.apply(candidate,env)
            assert(not ok and message==step..' failed' and rolled==nil)
            no_secret(message)
            same(calls,expected(step,false))
        end)
    end
end
for _, step in ipairs({'protect','commit','guard','reload','verify','finalize'}) do
    for _, thrown in ipairs({false,true}) do
        test(step .. ' failure attempts complete verified rollback',function()
            local fail = step .. ':1'
            local env, candidate, _, calls = harness(fail,thrown)
            local ok, message, rolled = M.apply(candidate,env)
            local label = step=='protect' and 'protection' or step
            assert(not ok and message==label..' failed' and rolled==true)
            no_secret(message)
            same(calls,expected(step,true))
        end)
    end
end
for _, step in ipairs({'restore','rollback_guard','reload','rollback_verify','finalize'}) do
    for _, thrown in ipairs({false,true}) do
        test(step .. ' recovery failure preserves original failure and later attempts',function()
            local env, candidate, old, calls = harness()
            env.verify=function(next)
                assert(next==candidate);calls[#calls+1]='verify';return false
            end
            if step=='reload' then
                local n=0
                env.reload=function()
                    calls[#calls+1]='reload';n=n+1
                    if n==2 then if thrown then error(secret) end;return false end
                    return true
                end
            elseif step=='finalize' then
                env.finalize=function(value)
                    assert(value==old);calls[#calls+1]='finalize-old'
                    if thrown then error(secret) end;return false
                end
            else
                env[step]=function(value)
                    assert(value==old);calls[#calls+1]=step
                    if thrown then error(secret) end;return false
                end
            end
            local ok,message,rolled=M.apply(candidate,env)
            assert(not ok and message=='verify failed' and rolled==false)
            no_secret(message)
            local order=expected('verify',true)
            if step~='finalize' then order[#order]=nil end
            same(calls,order)
        end)
    end
end
test('port change retains old and new guards until candidate is verified',function()
    local env,candidate,old,calls=harness()
    local guards={[old.port]=true}
    env.protect=function(previous,next)
        assert(previous==old and next==candidate)
        calls[#calls+1]='protect';guards[next.port]=true;return true
    end
    env.commit=function(next)
        assert(guards[old.port] and guards[next.port]);calls[#calls+1]='commit';return true
    end
    env.guard=function(next)
        assert(guards[old.port] and guards[next.port]);calls[#calls+1]='guard';return true
    end
    env.reload=function()
        assert(guards[old.port] and guards[candidate.port]);calls[#calls+1]='reload';return true
    end
    env.verify=function(next)
        assert(guards[old.port] and guards[next.port]);calls[#calls+1]='verify';return true
    end
    env.finalize=function(next)
        assert(next==candidate and calls[#calls]=='verify')
        calls[#calls+1]='finalize';guards[old.port]=nil;return true
    end
    assert(M.apply(candidate,env))
    assert(not guards[old.port] and guards[candidate.port])
    same(calls,sequence)
end)
test('disable verifies listener absence before old protection removal',function()
    local env,candidate,old,calls=harness()
    candidate.enabled=false
    local guarded,listener,verified=true,true,false
    env.protect=function(previous,next)
        assert(previous==old and not next.enabled and guarded and listener)
        calls[#calls+1]='protect';return true
    end
    env.guard=function(next)
        assert(not next.enabled and guarded and listener);calls[#calls+1]='guard';return true
    end
    env.reload=function()
        assert(guarded);calls[#calls+1]='reload';listener=false;return true
    end
    env.verify=function(next)
        assert(not next.enabled and guarded and not listener)
        calls[#calls+1]='verify';verified=true;return true
    end
    env.finalize=function(next)
        assert(next==candidate and verified and not listener)
        calls[#calls+1]='finalize';guarded=false;return true
    end
    assert(M.apply(candidate,env));assert(not guarded and not listener)
    same(calls,sequence)
end)
test('truthy callback values cannot masquerade as verified success',function()
    local env,candidate,_,calls=harness()
    env.stage=function(next) assert(next==candidate);calls[#calls+1]='stage';return 'yes' end
    local ok,message,rolled=M.apply(candidate,env)
    assert(not ok and message=='stage failed' and rolled==nil)
    same(calls,{'snapshot','stage'})
end)
test('invalid environment returns generic failure before invoking callbacks',function()
    for _,env in ipairs({{}, {snapshot=function() error(secret) end}}) do
        local ok,message,rolled=M.apply({},env)
        assert(not ok and message=='invalid environment' and rolled==nil)
    end
    local ok,message,rolled=M.apply({},nil)
    assert(not ok and message=='invalid environment' and rolled==nil)
end)
print('SS configuration transaction: '..count..' tests passed')
