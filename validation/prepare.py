import ast
from pathlib import Path
import urllib.request
roots=list(Path('openwrt/build_dir').glob('target-*/root-ramips'))
assert len(roots)==1
path=roots[0]/'usr/share/shadowsocksr/gen_config.lua'
path.parent.mkdir(parents=True,exist_ok=True)
url='https://raw.githubusercontent.com/fw876/helloworld/2abdc9aa9e19607774dc9789709212b70b8607c6/luci-app-ssr-plus/root/usr/share/shadowsocksr/gen_config.lua'
with urllib.request.urlopen(url,timeout=60) as response:
    text=response.read().decode()
tree=ast.parse(Path('trial/transform.py').read_text())
for item in tree.body:
    if not isinstance(item,ast.Expr) or not isinstance(item.value,ast.Call):continue
    call=item.value
    if not isinstance(call.func,ast.Name) or call.func.id!='replace':continue
    if not isinstance(call.args[0],ast.Name) or call.args[0].id!='gen':continue
    before,after=map(ast.literal_eval,call.args[1:3])
    count=next((ast.literal_eval(k.value) for k in call.keywords if k.arg=='count'),1)
    assert text.count(before)==count,(before,text.count(before))
    text=text.replace(before,after)
path.write_text(text)
