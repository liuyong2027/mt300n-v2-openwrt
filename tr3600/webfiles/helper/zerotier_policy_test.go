package main

import (
	"net"
	"strings"
	"testing"
)

func fixtureZeroTier() (zeroTierNetwork, map[string][]net.IP) {
	return zeroTierNetwork{ID: "0123456789abcdef", Status: "OK", Type: "PRIVATE", Interface: "ztc3q2tbgr", AssignedAddresses: []string{"192.168.7.6/24"}, AllowManaged: true, Routes: []zeroTierRoute{{"192.168.9.0/24", "192.168.7.6"}}}, map[string][]net.IP{"ztc3q2tbgr": {net.ParseIP("192.168.7.6")}}
}
func TestZeroTierRequiresAuthorizedPrivateLiveRoutedNetwork(t *testing.T) {
	n, live := fixtureZeroTier()
	if len(eligibleZeroTierNetworks("192.168.9.1", []zeroTierNetwork{n}, live)) != 1 {
		t.Fatal("valid existing routed network rejected")
	}
	for _, modify := range []func(*zeroTierNetwork){func(x *zeroTierNetwork) { x.Type = "PUBLIC" }, func(x *zeroTierNetwork) { x.Status = "ACCESS_DENIED" }, func(x *zeroTierNetwork) { x.AllowManaged = false }, func(x *zeroTierNetwork) { x.Interface = "eth0" }, func(x *zeroTierNetwork) { x.Interface = `ztbad";flush ruleset` }, func(x *zeroTierNetwork) { x.Routes = []zeroTierRoute{{"0.0.0.0/0", "192.168.7.6"}} }, func(x *zeroTierNetwork) { x.Routes = []zeroTierRoute{{"192.168.9.0/24", "192.168.7.3"}} }, func(x *zeroTierNetwork) { x.AssignedAddresses = []string{"203.0.113.6/24"} }} {
		x, _ := fixtureZeroTier()
		modify(&x)
		if len(eligibleZeroTierNetworks("192.168.9.1", []zeroTierNetwork{x}, live)) != 0 {
			t.Fatalf("unsafe network accepted: %q/%q", x.Type, x.Interface)
		}
	}
	if len(eligibleZeroTierNetworks("192.168.9.1", []zeroTierNetwork{n}, nil)) != 0 {
		t.Fatal("unassigned/disappeared interface accepted")
	}
}
func TestZeroTierNetworkPinningNeverBroadensToNewNetwork(t *testing.T) {
	a := zeroTierCandidate{Network: "0123456789abcdef", Interface: "ztc3q2tbgr"}
	b := zeroTierCandidate{Network: "1111111111111111", Interface: "ztanother"}
	if _, e := selectZeroTierNetwork([]zeroTierCandidate{a, b}, ""); e == nil {
		t.Fatal("ambiguous network automatically selected")
	}
	got, e := selectZeroTierNetwork([]zeroTierCandidate{a, b}, a.Network)
	if e != nil || got != a {
		t.Fatal("pinned network not selected")
	}
	if _, e := selectZeroTierNetwork([]zeroTierCandidate{b}, a.Network); e == nil {
		t.Fatal("replacement network accepted")
	}
}
func TestZeroTierFilterKeepsWANRejectedAndLANCertificateAddress(t *testing.T) {
	s := Snapshot{LAN: "192.168.9.1", Interface: "br-lan"}
	r, e := accessFilterRule("cudy_webfiles_managed_123", s, 8080, "ztc3q2tbgr")
	if e != nil {
		t.Fatal(e)
	}
	if !strings.Contains(r, `ip daddr 192.168.9.1 tcp dport 8080`) || !strings.Contains(r, `iifname != { "br-lan", "lo", "ztc3q2tbgr" } reject`) {
		t.Fatal("access widened beyond the existing LAN endpoint or named interfaces")
	}
	if strings.Contains(r, "eth0") || strings.Contains(r, "accept") || strings.Contains(r, "zt*") {
		t.Fatal("unexpected broad allow")
	}
	base, e := accessFilterRule("cudy_webfiles_managed_123", s, 8080, "")
	if e != nil || strings.Contains(base, "ztc3q2tbgr") {
		t.Fatal("LAN-only mode lost")
	}
	for _, iface := range []string{"eth0", "zt*", `ztbad";flush ruleset`, "lo"} {
		if _, e := accessFilterRule("cudy_webfiles_managed_123", s, 8080, iface); e == nil {
			t.Fatal("unsafe interface accepted")
		}
	}
	if _, e := accessFilterRule("fw4", s, 8080, "ztc3q2tbgr"); e == nil {
		t.Fatal("foreign table accepted")
	}
}
