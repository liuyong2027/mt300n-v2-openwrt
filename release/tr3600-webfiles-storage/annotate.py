# Disclose verified rc2 upgrade mode defect; preserve all published assets.
import json
from pathlib import Path
import subprocess

repository='liuyong2027/mt300n-v2-openwrt'
tag='tr3600-v1.1.0-rc2'
release=json.loads(subprocess.check_output(['gh','api',f'repos/{repository}/releases/tags/{tag}']))
assert release['tag_name']==tag and release['prerelease'] is True
image=[a for a in release['assets'] if a['name']=='cudy-tr3600-v1-1.1.0-rc2-sysupgrade.bin']
assert len(image)==1 and image[0]['size']==50043155
assert image[0]['digest']=='sha256:aabd2ed69c74d1ed4001811a4e7ec64dae84c1e8864888c292e489bde5e9f382'
marker='<!-- cudy-webfiles-rc2-upgrade-storage-mode-defect -->'
warning='''<!-- cudy-webfiles-rc2-upgrade-storage-mode-defect -->
> **2026-10-17 实机验收发现：保留配置升级后，WebFiles 可能因账号目录权限而无法启动。**
>
> 账号和证书文件已保留，但仅归档文件的升级恢复过程会把父目录重建为 755；程序要求私有目录权限为 700，因此拒绝读取。现场只修正目录权限后，原 guest 账号与原 CA 均恢复使用，无需重建密码或证书。
>
> 修复分支：`codex/tr3600-webfiles-upgrade-storage-mode`。修复只在目录、标记及文件身份符合预期时恢复目录权限；不读取或替换账号密钥、加密账号及证书。原生路由器与 ARM64 Lua/nixio 回归覆盖真实 tar 恢复和异常文件拒绝。新的完整固件尚未发布；这台设备此前的 WAN 反复断链原因也尚未查明，不能将短时恢复千兆视为全部实机验收通过。

'''
before=sorted((a['id'],a['name'],a['size'],a.get('digest')) for a in release['assets'])
if marker not in (release.get('body') or ''):
    payload=Path('release-warning-update.json')
    payload.write_text(json.dumps({'body':warning+(release.get('body') or '')},ensure_ascii=False))
    updated=json.loads(subprocess.check_output(['gh','api','--method','PATCH',f'repos/{repository}/releases/{release["id"]}','--input',str(payload)]))
    assert marker in updated['body']
    assert sorted((a['id'],a['name'],a['size'],a.get('digest')) for a in updated['assets'])==before
print(json.dumps({'release':release['html_url'],'upgrade_defect_disclosed':True,'existing_assets_replaced':False}))
