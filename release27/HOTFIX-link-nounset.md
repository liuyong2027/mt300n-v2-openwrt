# Hotfix — mango-ikev2-link nounset

## Problem
R27 `mango-ikev2-link` uses `set -eu` then sources `/lib/functions/network.sh`.
`network_flush_cache` unsets `__NETWORK_CACHE`; the next read under `set -u` aborts with:
`__NETWORK_CACHE: parameter not set`. `xfrm-mango` is never created and IKEv2 stays down.

## Fix
Use `set -e` (drop `-u`) in `/usr/libexec/mango-ikev2-link`.

## Applied
GL2 `192.168.8.1` after keep-config flash to R27 image from Actions run 42639271989 (2026-11-10).
