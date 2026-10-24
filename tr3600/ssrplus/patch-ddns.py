"""Scope direct marked curl to the built-in Dynu provider in the SSR image.

Usage: patch-ddns.py ROOTFS
Apply after ddns-scripts and the Cudy network overlay have been installed.
Exact anchors deliberately reject upstream API drift; this never reads UCI.
"""
import argparse
from pathlib import Path
import sys

MARKER = '# Cudy SSR Dynu direct sockets: preserve CURL arguments and WAN binding.'
ANCHOR = '\tlocal __PROG  __RUNPROG\n'
BLOCK = '''\tlocal CURL="$CURL" USE_CURL="$USE_CURL"
\t# Cudy SSR Dynu direct sockets: preserve CURL arguments and WAN binding.
\tif [ "${service_name:-}" = "cudy-dynu-https" ]; then
\t\tcase "$CURL" in
\t\t\t/usr/bin/curl|/usr/bin/curl\\ *) CURL="/usr/libexec/cudy-ddns-curl${CURL#/usr/bin/curl}" ;;
\t\t\t/usr/libexec/cudy-ddns-curl|/usr/libexec/cudy-ddns-curl\\ *) : ;;
\t\t\t*) write_log 3 'Dynu direct curl unavailable; no request sent'; return 1 ;;
\t\tesac
\t\tUSE_CURL=1
\tfi
'''


def patch_paths(framework, resolver):
    framework, resolver = Path(framework), Path(resolver)
    text = framework.read_text()
    original = text
    if MARKER not in text:
        assert text.count(ANCHOR) == 1, 'DDNS do_transfer anchor changed'
        text = text.replace(ANCHOR, ANCHOR + BLOCK)
    else:
        assert text.count(BLOCK) == 1, 'DDNS direct socket patch differs'
    data = resolver.read_text()
    old = '/usr/bin/curl -4 --interface '
    new = '/usr/libexec/cudy-ddns-curl -4 --interface '
    if old in data:
        assert data.count(old) == 1 and new not in data
        data = data.replace(old, new)
    else:
        assert data.count(new) == 1, 'Dynu resolver curl anchor changed'
    # Validate both inputs before the first write.
    if text != original:
        framework.write_text(text, encoding='utf-8', newline='\n')
    if data != resolver.read_text():
        resolver.write_text(data, encoding='utf-8', newline='\n')


def patch(root):
    root = Path(root)
    patch_paths(root / 'usr/lib/ddns/dynamic_dns_functions.sh',
                root / 'usr/libexec/cudy-dynu-resolve')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', nargs='?', type=Path)
    parser.add_argument('--framework', type=Path)
    parser.add_argument('--resolver', type=Path)
    args = parser.parse_args()
    if args.root:
        assert not args.framework and not args.resolver
        patch(args.root)
    else:
        assert args.framework and args.resolver
        patch_paths(args.framework, args.resolver)
