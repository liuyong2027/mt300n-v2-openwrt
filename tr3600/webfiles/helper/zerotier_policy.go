package main

import (
	"fmt"
	"net"
	"regexp"
	"sort"
	"strconv"
	"strings"
)

type zeroTierRoute struct {
	Target string `json:"target"`
	Via    string `json:"via"`
}
type zeroTierNetwork struct {
	ID                string          `json:"id"`
	Status            string          `json:"status"`
	Type              string          `json:"type"`
	Interface         string          `json:"portDeviceName"`
	AssignedAddresses []string        `json:"assignedAddresses"`
	AllowManaged      bool            `json:"allowManaged"`
	Routes            []zeroTierRoute `json:"routes"`
}
type zeroTierCandidate struct {
	Network   string `json:"network"`
	Interface string `json:"interface"`
	Address   string `json:"address"`
	Route     string `json:"route"`
}
type zeroTierAccessConfig struct {
	Enabled bool   `json:"enabled"`
	Network string `json:"network"`
}
type zeroTierAccessStatus struct {
	Enabled   bool   `json:"enabled"`
	Active    bool   `json:"active"`
	Network   string `json:"network,omitempty"`
	Interface string `json:"interface,omitempty"`
	Address   string `json:"address,omitempty"`
	URL       string `json:"url,omitempty"`
	Error     string `json:"error,omitempty"`
	Pending   bool   `json:"pending,omitempty"`
}

var zeroTierNetworkID = regexp.MustCompile(`^[0-9a-f]{16}$`)
var zeroTierInterface = regexp.MustCompile(`^zt[a-z0-9]{1,13}$`)

// Only an existing, authorized private network with a live assigned address
// and a managed route back to this LAN can broaden the local input filter.
func eligibleZeroTierNetworks(lan string, networks []zeroTierNetwork, live map[string][]net.IP) []zeroTierCandidate {
	ip := net.ParseIP(lan)
	if ip == nil || ip.To4() == nil || !ip.IsPrivate() {
		return nil
	}
	var out []zeroTierCandidate
	seen := map[string]bool{}
	for _, n := range networks {
		if !zeroTierNetworkID.MatchString(n.ID) || seen[n.ID] || n.Status != "OK" || n.Type != "PRIVATE" || !n.AllowManaged || !zeroTierInterface.MatchString(n.Interface) {
			continue
		}
		for _, assigned := range n.AssignedAddresses {
			address, _, err := net.ParseCIDR(assigned)
			if err != nil || address.To4() == nil || !address.IsPrivate() {
				continue
			}
			present := false
			for _, actual := range live[n.Interface] {
				if actual.Equal(address) {
					present = true
					break
				}
			}
			if !present {
				continue
			}
			for _, route := range n.Routes {
				_, prefix, err := net.ParseCIDR(route.Target)
				if err != nil || prefix.IP.To4() == nil || !prefix.IP.IsPrivate() || !prefix.Contains(ip) {
					continue
				}
				ones, _ := prefix.Mask.Size()
				if ones == 0 || !net.ParseIP(route.Via).Equal(address) {
					continue
				}
				out = append(out, zeroTierCandidate{n.ID, n.Interface, address.String(), prefix.String()})
				seen[n.ID] = true
				break
			}
			if seen[n.ID] {
				break
			}
		}
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Network < out[j].Network })
	return out
}
func selectZeroTierNetwork(candidates []zeroTierCandidate, pinned string) (zeroTierCandidate, error) {
	if pinned != "" {
		if !zeroTierNetworkID.MatchString(pinned) {
			return zeroTierCandidate{}, fmt.Errorf("ZeroTier 网络标识无效")
		}
		for _, c := range candidates {
			if c.Network == pinned {
				return c, nil
			}
		}
		return zeroTierCandidate{}, fmt.Errorf("指定 ZeroTier 网络未就绪，或缺少到本机 LAN 的托管路由")
	}
	if len(candidates) != 1 {
		return zeroTierCandidate{}, fmt.Errorf("请选择一个已就绪并配置了 LAN 托管路由的私有 ZeroTier 网络")
	}
	return candidates[0], nil
}
func accessFilterRule(table string, s Snapshot, port int, zt string) (string, error) {
	if !regexp.MustCompile(`^cudy_webfiles_managed_[0-9]+$`).MatchString(table) || !ifaceName.MatchString(s.Interface) || port < 1024 || port > 65535 {
		return "", fmt.Errorf("invalid access filter identity")
	}
	ip := net.ParseIP(s.LAN)
	if ip == nil || ip.To4() == nil || !ip.IsPrivate() {
		return "", fmt.Errorf("invalid LAN address")
	}
	allowed := []string{"lo", s.Interface}
	if zt != "" {
		if !zeroTierInterface.MatchString(zt) || zt == s.Interface {
			return "", fmt.Errorf("invalid ZeroTier interface")
		}
		allowed = append(allowed, zt)
	}
	sort.Strings(allowed)
	quoted := make([]string, len(allowed))
	for i, v := range allowed {
		quoted[i] = strconv.Quote(v)
	}
	return fmt.Sprintf("add rule inet %s input ip daddr %s tcp dport %d iifname != { %s } reject\n", table, ip.String(), port, strings.Join(quoted, ", ")), nil
}
