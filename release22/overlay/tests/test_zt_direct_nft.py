#!/usr/bin/env python3
"""Real nft transactions and UDP packets; invoke ONLY in a private network namespace."""
import json
from pathlib import Path
import socket
import subprocess

ROOT = Path(__file__).resolve().parents[1]
MODULE = 'package/luci-app-mango-proxy/root/usr/lib/mango/zt-direct.lua'


def command(*args, input=None):
    return subprocess.run(args, input=input, text=True, check=True, capture_output=True).stdout


def apply(policy):
    listing = command('nft', '-j', 'list', 'table', 'inet', 'fw4')
    # -e leaves the remaining command arguments as script names, so use one
    # environment-free Lua fixture file rather than interpolating packet data.
    driver = ROOT / 'reports/zt-nft-driver.lua'
    driver.write_text("local j=dofile('package/luci-app-mango-proxy/root/usr/lib/mango/zt-json.lua');local m=dofile(arg[1]);print(assert(m.transaction(j.decode(arg[2]),j.decode(io.read('*a')))))\n")
    transaction = command('lua5.1', str(driver), MODULE, json.dumps(policy), input=listing)
    command('nft', '-f', '-', input=transaction)
    return json.loads(command('nft', '-j', 'list', 'table', 'inet', 'fw4'))['nftables']


def packet(source, sport, dport, expected):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
        receiver.bind(('10.20.30.254', dport))
        receiver.settimeout(0.25)
        sender.bind((source, sport))
        sender.sendto(b'zt-test', ('10.20.30.254', dport))
        try: received = receiver.recv(100) == b'zt-test'
        except socket.timeout: received = False
        assert received == expected, (source, sport, dport, received, expected)


def main():
    assert Path('/proc/self/ns/net').readlink() != Path('/proc/1/ns/net').readlink(), 'Require private network namespace'
    (ROOT / 'reports').mkdir(exist_ok=True)
    command('ip', 'link', 'set', 'lo', 'up')
    for address in ('10.20.30.1/32', '10.20.30.2/32', '10.20.30.254/32'):
        command('ip', 'addr', 'add', address, 'dev', 'lo')
    command('nft', '-f', '-', input='add table inet fw4\nadd chain inet fw4 input_wan { type filter hook input priority 0; policy drop; }\nadd rule inet fw4 input_wan udp dport 60000 accept comment "owner-rule"\n')
    policy = {'ports': [9993, 48170, 20089], 'gateway': '10.20.30.1'}
    listing = apply(policy)
    assert len([x for x in listing if x.get('rule', {}).get('chain') == 'mango_zt_direct']) == 2
    cases = 0
    for port in policy['ports']:
        packet('10.20.30.2', 42000, port, True); cases += 1
    for source, sport, dport, expect in [('10.20.30.2', 42000, 45000, False), ('10.20.30.1', 1900, 45000, True), ('10.20.30.2', 1900, 45000, False), ('10.20.30.1', 1901, 45000, False)]:
        packet(source, sport, dport, expect); cases += 1
    policy['gateway'] = '10.20.30.2'
    apply(policy)
    packet('10.20.30.1', 1900, 45000, False); cases += 1
    packet('10.20.30.2', 1900, 45000, True); cases += 1
    policy.pop('gateway')
    apply(policy)
    packet('10.20.30.2', 1900, 45000, False); cases += 1
    packet('10.20.30.2', 42000, 9993, True); cases += 1
    for _ in range(3): listing = apply(policy)
    assert len([x for x in listing if x.get('rule', {}).get('chain') == 'input_wan' and x['rule'].get('comment') == 'mango-zt-direct-v1']) == 1
    listing = apply({'ports': []})
    assert not any(x.get('chain', {}).get('name') == 'mango_zt_direct' for x in listing)
    assert any(x.get('rule', {}).get('comment') == 'owner-rule' for x in listing)
    packet('10.20.30.2', 42000, 9993, False); cases += 1
    packet('10.20.30.2', 42000, 60000, True); cases += 1
    report = {'status': 'passed', 'real_udp_cases': cases, 'gateway_replacement': 'passed', 'wan_down_ssdp_removal': 'passed', 'idempotence': 'passed', 'owned_cleanup': 'passed', 'unrelated_owner_rule': 'preserved', 'scope': 'isolated Linux namespace, not device hardware'}
    (ROOT / 'reports/zt-direct-nft.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
