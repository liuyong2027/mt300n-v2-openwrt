#!/usr/bin/env python3
"""Prepare immutable source, evidence and checksum assets after image gates."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / 'tr3600-assets'
VERSION = '1.1.0-rc1'
commit = os.environ['GITHUB_SHA']
proof = json.loads((ASSETS / 'tr3600-verification.json').read_text())
assert proof['source_commit'] == commit
assert proof['version'] == 'tr3600-' + VERSION
assert proof['webfiles_and_DDNS']['clean_image_private_data_absent']
image = ASSETS / proof['image']
assert hashlib.sha256(image.read_bytes()).hexdigest() == proof['image_sha256']
assert '1.0.0 image has not' not in proof['hardware_validation']
subprocess.run(['git', 'archive', '--format=zip', '--output=' + str(ASSETS / ('SOURCE-' + VERSION + '.zip')), commit], cwd=ROOT, check=True)
quantum = ROOT / 'vendor/quantum'
def filter_source(info):
    parts = Path(info.name).parts
    if any(p in ('.git', 'node_modules') for p in parts):
        return None
    return info
with tarfile.open(ASSETS / ('QUANTUM-SOURCE-' + VERSION + '.tar.gz'), 'w:gz') as archive:
    archive.add(quantum, arcname='quantum-v2.0.0-stable-cudy-jti1', filter=filter_source)
build = json.loads((ASSETS / 'webfiles-build.json').read_text())
provenance = {'firmware_version': proof['version'], 'repository': os.environ['GITHUB_REPOSITORY'], 'source_commit': commit, 'run_id': os.environ['GITHUB_RUN_ID'], 'run_attempt': os.environ['GITHUB_RUN_ATTEMPT'], 'TR3600_baseline_commit': 'e298f2b015bc70eac46e0de58204616046cb119f', 'OpenWrt_commit': build['lock']['openwrt_commit'], 'Quantum_commit': build['lock']['quantum_commit'], 'Quantum_patch_sha256': build['lock']['quantum_patch_sha256'], 'Go_version': build['lock']['go_version'], 'Node_version': build['lock']['node_version'], 'new_image_hardware_acceptance': 'pending; not flashed by this build or publication', 'PPTP_included': False}
(ASSETS / ('SOURCE-PROVENANCE-' + VERSION + '.json')).write_text(json.dumps(provenance, indent=2) + '\n')
notes = '''Cudy TR3600 V1.0 / R126 — 1.1.0-rc1 测试版

新增 Cudy webpage（WebFiles）、标准 LuCI DDNS及ZeroTier直连修正；沿用1.0.0的USB共享、Xray/Mango、ZeroTier、SS、Wi-Fi和LED基线。本版不包含PPTP或L2TP/IPsec服务端。

WebFiles提供LuCI启停、最多16个独立账号及读写权限、HTTPS、可选ZeroTier与公网入口。沿用Quantum随机JWT jti修正。首次安装服务关闭、未选择USB卷、只读，ZeroTier和公网入口关闭；没有预置个人账号、CA、域名或网络ID。新安装的网页入口默认使用LAN地址的8080端口。

恢复标准DDNS及Dynu等服务商定义。保留配置升级不再删除DDNS配置；WebFiles的账号加密密钥、账号和TLS目录列入保留清单。保留配置时沿用原端口、授权卷、密码、CA和访问开关；完整新镜像的升级恢复仍需实机验证。

软件包保留Go已精简可执行文件的原始字节，避免二次strip破坏内置校验值；最终镜像哈希比较继续强制执行。Mango首次启动只创建缺失的自有防火墙区段，保留已有策略、地址伪装范围和停用规则。按用户要求，新机mangozt默认入站/出站/区域内转发均接受、IPv4地址伪装开启。\n\nZeroTier纳入固定UDP端口、按当前WAN网关限制的UPnP响应，以及防火墙重载/WAN事件/服务启停恢复。保留已有local.conf和规则，不包含个人网络ID；未将短时保活试验设为常驻，也未启用低带宽模式。不能保证所有NAT条件均直连，远端弱性能设备的首包延迟仍可能出现。首次从旧固件升级前，须把 /etc/zerotier-stable-ports.json 和 /etc/cudy-webfiles/ 加入旧固件 /etc/sysupgrade.conf，并核实备份中确有这些文件；新镜像中的保留清单不能替旧固件完成首次备份。\n\n仅适用于匹配的TR3600 V1.0定制OpenWrt。刷机前阅读README.txt和RELEASE-NOTES.txt，备份设置并校验SHA256SUMS。此sysupgrade镜像不是原厂通用升级包。本次构建和发布均不自动刷写路由器。

验证范围：CI代码回归、目标ARM64程序与库检查、最终镜像内容／架构／元数据／容量校验通过。新完整镜像尚未刷机验收。旧固件上WebFiles功能及重启测试的结果不能代替本镜像验收。

已有设备上曾记录WAN短断及FAT32未正常卸载提示；本版没有宣称修复。长期稳定性、此镜像上的手机文件操作、物理断链恢复等仍待测试。发布为Prerelease，不替代已验收稳定版本。
'''
(ASSETS / ('RELEASE-' + VERSION + '.txt')).write_text(notes)
files = sorted(p for p in ASSETS.iterdir() if p.is_file() and p.name != 'SHA256SUMS')
(ASSETS / 'SHA256SUMS').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + p.name + '\n' for p in files))
print(json.dumps({'source_commit': commit, 'assets': {p.name: {'bytes': p.stat().st_size, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in files}, 'hardware_acceptance': 'pending'}, indent=2))
