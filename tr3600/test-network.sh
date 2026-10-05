#!/bin/sh
# Execute the real hotplug script with mocked commands; never change a NIC.
set -eu
task_script=${1:-tr3600/network-root/etc/hotplug.d/iface/95-cudy-tr3600-eee}
task_dir=$(mktemp -d)
trap 'rm -f "$task_dir/result"; rmdir "$task_dir"' EXIT
cat() { printf '%s\n' "$task_board"; }
uci() { printf '%s\n' "$task_device"; }
ethtool() { printf '%s\n' "$*" > "$task_dir/result"; }
logger() { :; }
check() {
    ACTION=$1 INTERFACE=$2 task_board=$3 task_device=$4
    rm -f "$task_dir/result"
    ( . "$task_script" )
    if [ "$5" = apply ]; then
        [ "$(command cat "$task_dir/result")" = '--set-eee eth0 eee off tx-lpi off' ]
    else
        [ ! -e "$task_dir/result" ]
    fi
}
check ifup wan cudy,tr3600-v1 eth0 apply
check ifdown wan cudy,tr3600-v1 eth0 skip
check ifup lan cudy,tr3600-v1 eth0 skip
check ifup wan other,device eth0 skip
check ifup wan cudy,tr3600-v1 eth1 skip
check ifup wan cudy,tr3600-v1 '' skip
printf 'WAN EEE hook: positive case and five isolation guards passed\n'
