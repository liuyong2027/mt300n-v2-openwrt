#!/bin/sh
set -eu
umask 077
task_dir=$(mktemp -d)
trap 'rm -f "$task_dir/wireless" "$task_dir/usteer" "$task_dir/cudy_wifi" "$task_dir/delta/wireless" "$task_dir/delta/usteer" "$task_dir/delta/cudy_wifi"; rmdir "$task_dir/delta" "$task_dir"' EXIT
mkdir "$task_dir/delta"
cat > "$task_dir/wireless" <<'EOF'
config wifi-device 'r2'
 option band '2g'
config wifi-device 'r5'
 option band '5g'
config wifi-iface 'ap2'
 option device 'r2'
 option mode 'ap'
 option network 'lan'
 option ssid 'Separate-2G'
 option key 'OldPass_2G'
 option encryption 'psk2'
config wifi-iface 'ap5'
 option device 'r5'
 option mode 'ap'
 list network 'lan'
 option ssid 'Separate-5G'
 option key 'OldPass_5G'
 option encryption 'sae-mixed'
EOF
cat > "$task_dir/usteer" <<'EOF'
config usteer 'main'
 option enabled '0'
 option network 'lan'
 list ssid_list 'OldScope'
EOF
cat > "$task_dir/cudy_wifi" <<'EOF'
config wifi 'main'
 option enabled '1'
 option steering '1'
 option ssid 'Unified-Test'
 option encryption 'sae-mixed'
EOF
"${CUDY_TEST_LUA:-lua}" "$1" "$2" "$task_dir"
