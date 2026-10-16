//go:build linux

package main

import (
	"context"
	"encoding/json"
	"fmt"
	"net"
	"os"
	"os/exec"
	"strings"
	"time"
)

func zeroTierConfigNow() zeroTierAccessConfig {
	return zeroTierAccessConfig{uciGet("zerotier", "0") == "1", uciGet("zerotier_network", "")}
}
func discoverZeroTier(ctx context.Context, lan string) ([]zeroTierCandidate, error) {
	ctx, cancel := context.WithTimeout(ctx, 2*time.Second)
	defer cancel()
	b, e := exec.CommandContext(ctx, "zerotier-cli", "-j", "listnetworks").Output()
	if e != nil || len(b) > 65536 {
		return nil, fmt.Errorf("无法读取 ZeroTier 网络状态")
	}
	var networks []zeroTierNetwork
	if json.Unmarshal(b, &networks) != nil {
		return nil, fmt.Errorf("ZeroTier 网络状态格式无效")
	}
	live := map[string][]net.IP{}
	for _, n := range networks {
		if !zeroTierInterface.MatchString(n.Interface) {
			continue
		}
		i, e := net.InterfaceByName(n.Interface)
		if e != nil || i.Flags&net.FlagUp == 0 {
			continue
		}
		addresses, e := i.Addrs()
		if e != nil {
			continue
		}
		for _, a := range addresses {
			ip, _, e := net.ParseCIDR(a.String())
			if e == nil && ip.To4() != nil {
				live[n.Interface] = append(live[n.Interface], ip)
			}
		}
	}
	return eligibleZeroTierNetworks(lan, networks, live), nil
}
func writeZeroTierConfig(c zeroTierAccessConfig) error {
	if c.Network != "" && !zeroTierNetworkID.MatchString(c.Network) {
		return fmt.Errorf("ZeroTier 网络标识无效")
	}
	text := fmt.Sprintf("set cudy_webfiles.main.zerotier='%d'\nset cudy_webfiles.main.zerotier_network='%s'\ncommit cudy_webfiles\n", map[bool]int{true: 1, false: 0}[c.Enabled], c.Network)
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, "uci", "batch")
	cmd.Stdin = strings.NewReader(text)
	if cmd.Run() != nil {
		return fmt.Errorf("保存 ZeroTier 访问设置失败")
	}
	return nil
}
func runtimeZeroTier() (zeroTierAccessStatus, bool) {
	var owner owner
	b, e := os.ReadFile(runtimeDir + "/owner.json")
	if e != nil || json.Unmarshal(b, &owner) != nil || owner.Exe != selfExe() {
		return zeroTierAccessStatus{}, false
	}
	start, e := processStart(owner.PID)
	if e != nil || start != owner.Start {
		return zeroTierAccessStatus{}, false
	}
	var s struct {
		Version string               `json:"version"`
		PID     int                  `json:"runPID"`
		Start   string               `json:"runStart"`
		Access  zeroTierAccessStatus `json:"zerotier"`
	}
	b, e = os.ReadFile(runtimeDir + "/status.json")
	if e != nil || json.Unmarshal(b, &s) != nil || s.Version != version || s.PID != owner.PID || s.Start != owner.Start {
		return zeroTierAccessStatus{}, false
	}
	return s.Access, true
}
func addZeroTierStatus(result map[string]any, lan string, port int, running bool) {
	cfg := zeroTierConfigNow()
	z := zeroTierAccessStatus{Enabled: cfg.Enabled, Network: cfg.Network, URL: fmt.Sprintf("https://%s:%d", lan, port)}
	if running {
		if active, ok := runtimeZeroTier(); ok {
			z.Active = active.Active
			z.Interface = active.Interface
			z.Address = active.Address
			z.Error = active.Error
			z.Pending = active.Enabled != cfg.Enabled || active.Network != cfg.Network
		} else {
			z.Pending = cfg.Enabled
		}
	}
	if z.Active {
		result["access"] = "LAN + ZeroTier"
	} else if cfg.Enabled {
		result["access"] = "LAN（ZeroTier 待就绪）"
	}
	result["zerotier"] = z
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	if candidates, e := discoverZeroTier(ctx, lan); e == nil {
		result["zerotier_networks"] = candidates
	}
}
func watchZeroTier(ctx context.Context, lan string, port int) <-chan zeroTierAccessStatus {
	updates := make(chan zeroTierAccessStatus, 1)
	go func() {
		defer close(updates)
		for {
			cfg := zeroTierConfigNow()
			state := zeroTierAccessStatus{Enabled: cfg.Enabled, Network: cfg.Network, URL: fmt.Sprintf("https://%s:%d", lan, port)}
			if cfg.Enabled {
				candidates, e := discoverZeroTier(ctx, lan)
				if e != nil {
					state.Error = "ZeroTier 状态暂不可用，保留 LAN 访问"
				} else if !zeroTierNetworkID.MatchString(cfg.Network) {
					state.Error = "未固定已授权的 ZeroTier 网络"
				} else if candidate, e := selectZeroTierNetwork(candidates, cfg.Network); e != nil {
					state.Error = "ZeroTier 网络或 LAN 托管路由暂未就绪"
				} else {
					state.Active = true
					state.Interface = candidate.Interface
					state.Address = candidate.Address
				}
			}
			select {
			case updates <- state:
			case <-ctx.Done():
				return
			}
			timer := time.NewTimer(5 * time.Second)
			select {
			case <-timer.C:
			case <-ctx.Done():
				timer.Stop()
				return
			}
		}
	}()
	return updates
}
func setZeroTierAccess(params map[string]json.RawMessage) error {
	var input struct {
		Enabled bool   `json:"enabled"`
		Network string `json:"network"`
	}
	b, _ := json.Marshal(params)
	if json.Unmarshal(b, &input) != nil {
		return fmt.Errorf("ZeroTier 设置格式错误")
	}
	previous := zeroTierConfigNow()
	next := zeroTierAccessConfig{Enabled: input.Enabled, Network: previous.Network}
	if input.Network != "" {
		next.Network = strings.ToLower(input.Network)
	}
	if next.Enabled {
		base, e := packageDir()
		if e != nil {
			return e
		}
		s, e := getSnapshot(base)
		if e != nil {
			return e
		}
		candidates, e := discoverZeroTier(context.Background(), s.LAN)
		if e != nil {
			return e
		}
		candidate, e := selectZeroTierNetwork(candidates, next.Network)
		if e != nil {
			return e
		}
		next.Network = candidate.Network
	}
	if e := writeZeroTierConfig(next); e != nil {
		return e
	}
	if !managedRunning() {
		return nil
	}
	deadline := time.Now().Add(12 * time.Second)
	for time.Now().Before(deadline) {
		if !managedRunning() {
			break
		}
		if current, ok := runtimeZeroTier(); ok && current.Enabled == next.Enabled && current.Network == next.Network && current.Active == next.Enabled {
			return nil
		}
		time.Sleep(150 * time.Millisecond)
	}
	if e := writeZeroTierConfig(previous); e != nil {
		return fmt.Errorf("访问规则未确认生效，且恢复原访问设置失败，请检查本服务状态")
	}
	return fmt.Errorf("ZeroTier 访问规则未确认生效，已恢复原访问设置")
}
