#!/bin/bash
# Test infrastructure only: never copied into the OpenWrt tree or firmware.
set -euo pipefail
repo=$(cd "$(dirname "$0")/../.." && pwd)
source_dir="$repo/vendor/qemu-ddns"
commit=f671ce11d2a15a58ab752d7cf0b2890c9022c7ba # upstream QEMU v8.2.10
patch="$repo/tr3600/ssrplus/qemu-so-mark.patch"
test ! -e "$source_dir"
mkdir -p "$repo/vendor" "$repo/reports"
git init "$source_dir"
git -C "$source_dir" remote add origin https://github.com/qemu/qemu.git
git -C "$source_dir" fetch --depth=1 origin "$commit"
git -C "$source_dir" checkout --detach FETCH_HEAD
test "$(git -C "$source_dir" rev-parse HEAD)" = "$commit"
git -C "$source_dir" diff --exit-code
git -C "$source_dir" apply --check "$patch"
git -C "$source_dir" apply "$patch"
# All three revisions are pinned in this exact upstream commit's wrap files.
(cd "$source_dir" && meson subprojects download keycodemapdb berkeley-softfloat-3 berkeley-testfloat-3)
mkdir "$source_dir/build"
(
  cd "$source_dir/build"
  ../configure --target-list=aarch64-linux-user --disable-system --disable-tools \
    --disable-docs --disable-guest-agent --disable-werror --disable-download \
    --disable-capstone --disable-slirp --disable-gtk --disable-sdl --disable-vnc
  ninja -j2 qemu-aarch64
)
python3 - "$repo" "$commit" <<'PY'
import hashlib
import json
from pathlib import Path
import subprocess
import sys

repo = Path(sys.argv[1])
executable = repo / 'vendor/qemu-ddns/build/qemu-aarch64'
patch = repo / 'tr3600/ssrplus/qemu-so-mark.patch'
proof = {
    'purpose': 'test-only ARM64 SO_MARK syscall forwarding; never installed in firmware',
    'source_url': 'https://github.com/qemu/qemu',
    'source_commit': sys.argv[2],
    'patch_sha256': hashlib.sha256(patch.read_bytes()).hexdigest(),
    'executable': str(executable.relative_to(repo)),
    'executable_sha256': hashlib.sha256(executable.read_bytes()).hexdigest(),
    'version': subprocess.check_output([str(executable), '--version'], text=True).splitlines()[0],
    'semantics': 'forward SO_MARK to real host setsockopt/getsockopt; no success or permission emulation',
}
(repo / 'reports/ddns-qemu-build.json').write_text(json.dumps(proof, indent=2) + '\n')
print(json.dumps(proof, indent=2))
PY
