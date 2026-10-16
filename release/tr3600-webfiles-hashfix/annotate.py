#!/usr/bin/env python3
"""Disclose the verified rc1 runtime defect without replacing existing assets."""
import json
from pathlib import Path
import subprocess

repository = 'liuyong2027/mt300n-v2-openwrt'
tag = 'tr3600-v1.1.0-rc1'
release = json.loads(subprocess.check_output(['gh', 'api', f'repos/{repository}/releases/tags/{tag}']))
assert release['tag_name'] == tag and release['prerelease'] is True
image = [a for a in release['assets'] if a['name'] == 'cudy-tr3600-v1-1.1.0-rc1-sysupgrade.bin']
assert len(image) == 1 and image[0]['size'] == 50043155
marker = '<!-- cudy-webfiles-rc1-runtime-hash-defect -->'
warning = '''<!-- cudy-webfiles-rc1-runtime-hash-defect -->
> **2026-10-16 实机验收发现：本 rc1 的 WebFiles 无法正常启动，请等待修正版。**
>
> 重新编译的 Quantum 与 WebFiles 内置的旧校验值不一致，启动检查会拒绝运行。此前 CI 的文件清单校验没有覆盖这一运行检查，因此不能将构建通过视为 WebFiles 实机验收通过。
>
> 修复分支：`codex/tr3600-webfiles-runtime-hash-fix`。修复保留启动校验，并将实际编译结果绑定到管理程序，同时增加真实 ARM64 校验及篡改拒绝测试。本条说明不代表新固件已发布或已完成手机端验收。已刷设备无需因此恢复出厂；请保留配置并等待修正版。

'''
if marker not in (release.get('body') or ''):
    payload = Path('release-warning-update.json')
    payload.write_text(json.dumps({'body': warning + (release.get('body') or '')}, ensure_ascii=False))
    updated = json.loads(subprocess.check_output(['gh', 'api', '--method', 'PATCH', f'repos/{repository}/releases/{release["id"]}', '--input', str(payload)]))
    assert marker in updated['body']
    assert sorted((a['id'], a['name'], a['size']) for a in updated['assets']) == sorted((a['id'], a['name'], a['size']) for a in release['assets'])
print(json.dumps({'release': release['html_url'], 'runtime_defect_disclosed': True, 'existing_assets_replaced': False}))
