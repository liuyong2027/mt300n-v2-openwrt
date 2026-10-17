"""Run packed ARM64 LED logic and deterministic HTTP/wrapper fixtures."""
import json,os,pathlib,subprocess,sys,tempfile
kit=pathlib.Path(__file__).resolve().parent
root=pathlib.Path(sys.argv[1]).resolve()
sources=pathlib.Path(sys.argv[2]).resolve()if len(sys.argv)>2 else None
module=(sources/'luci-app-cudy-led/root/usr/lib/lua/cudy/led-runtime.lua')if sources else root/'usr/lib/lua/cudy/led-runtime.lua'
common=(sources/'led-probe/mango-connectivity-probe')if sources else root/'usr/libexec/mango-connectivity-probe'
wrapper=(sources/'led-probe/mango-probe')if sources else root/'usr/libexec/mango-probe'
env=dict(os.environ,LUA_CPATH=str(root/'usr/lib/lua/?.so'),LUA_PATH=str(root/'usr/lib/lua/?.lua')+';'+str(root/'usr/lib/lua/?/init.lua'))
lua=['qemu-aarch64-static','-L',str(root),str(root/'usr/bin/lua')]
def run(args):
    p=subprocess.run(args,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env)
    if p.returncode:sys.stderr.write(p.stdout+p.stderr)
    assert p.returncode==0,(args,p.returncode)
    print(p.stdout,end='');return p.stdout
run(lua+[str(kit/'test-led-runtime.lua'),str(root/'usr/lib/lua/cudy/led.lua'),str(module)])
out=run(lua+[str(kit/'test-led-probe-ownership.lua'),str(module)])
assert 'PASS 175 assertions:'in out
with tempfile.TemporaryDirectory(prefix='cudy-led-shared-fixtures-')as td:
    out=run(['sh',str(kit/'test-common-probe.sh'),str(common),td]);assert '20 mode/scenario cases'in out
    out=run(['sh',str(kit/'test-common-probe-wrapper.sh'),str(wrapper),str(common),td]);assert 'PASS automatic-switch wrapper:'in out
print(json.dumps({'LED_shared_probe_regressions_passed':True,'ownership_assertions':175,'HTTP_mode_scenario_cases':20,'runtime':'actual ARM64 Lua/nixio with deterministic shell HTTP/wrapper fixtures; no live sockets or sysfs writes'}))
