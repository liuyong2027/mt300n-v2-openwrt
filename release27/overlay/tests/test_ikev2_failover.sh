#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
python3 tests/test_ikev2_runtime.py
for script in package/luci-app-mango-ikev2/root/etc/hotplug.d/iface/*; do
    sh -n "$script"
done
