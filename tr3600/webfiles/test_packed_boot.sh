#!/bin/sh
set -eu
root="$1"
test "$(id -u)" = 0
mount --make-rprivate /
mount -t tmpfs -o mode=1777,nosuid,nodev tmpfs /tmp
set +e
qemu-aarch64-static "$root/usr/lib/cudy-webfiles/bin/cudy-webfiles" boot-run --volume invalid > /tmp/boot.stdout 2> /tmp/boot.stderr
result=$?
set -e
test "$result" = 1
python3 - <<'PY'
import json,stat
from pathlib import Path
p=Path('/tmp/cudy-webfiles-startup.json');s=p.lstat();r=json.loads(p.read_text())
assert stat.S_ISREG(s.st_mode) and stat.S_IMODE(s.st_mode)==0o600 and s.st_uid==0 and s.st_nlink==1
assert r['version']=='0.6.6' and r['stage']=='failed' and r['code']=='startup_invalid_settings' and r['attempts']==0
assert not Path('/tmp/cudy-webfiles-managed').exists()
assert '网页服务启动设置无效' in Path('/tmp/boot.stderr').read_text()
print(json.dumps({'actual_packed_ARM64_boot_action':'passed','early_failure_diagnostic':'passed','diagnostic_root0600':True,'worker_started':False,'host_tmp_isolated_by_mount_namespace':True}))
PY
