//go:build linux

package main

import (
	"bytes"
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"encoding/pem"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"os/exec"
	"regexp"
	"strconv"
	"strings"
	"syscall"
	"time"
)

type publicWAN struct {
	Address   string `json:"address"`
	Interface string `json:"interface"`
}

func publicWANNow() (publicWAN, error) {
	var out publicWAN
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	b, e := exec.CommandContext(ctx, "ubus", "call", "network.interface.wan", "status").Output()
	var s struct {
		Up        bool   `json:"up"`
		Device    string `json:"l3_device"`
		Addresses []struct {
			Address string `json:"address"`
		} `json:"ipv4-address"`
	}
	if e != nil || len(b) > 65536 || json.Unmarshal(b, &s) != nil || !s.Up || len(s.Addresses) != 1 {
		return out, fmt.Errorf("当前 WAN IPv4 未就绪或不唯一")
	}
	ip := net.ParseIP(s.Addresses[0].Address)
	if ip == nil || ip.To4() == nil || !ip.IsPrivate() {
		return out, fmt.Errorf("本入口需要上级路由器分配的私有 WAN IPv4")
	}
	i, e := net.InterfaceByName(s.Device)
	if e != nil || i.Flags&net.FlagUp == 0 {
		return out, fmt.Errorf("WAN 接口未就绪")
	}
	a, e := i.Addrs()
	if e != nil {
		return out, fmt.Errorf("无法核验 WAN 地址")
	}
	found := false
	for _, v := range a {
		actual, _, e := net.ParseCIDR(v.String())
		if e == nil && actual.Equal(ip) {
			found = true
		}
	}
	if !found {
		return out, fmt.Errorf("WAN 实际地址与接口状态不一致")
	}
	return publicWAN{ip.String(), s.Device}, nil
}
func publicConfigNow() publicAccessConfig {
	port, _ := strconv.Atoi(uciGet("public_port", "8080"))
	external, _ := strconv.Atoi(uciGet("public_external_port", "8080"))
	return publicAccessConfig{uciGet("public_enabled", "0") == "1", uciGet("public_ip", ""), external, uciGet("public_listen_ip", ""), port, uciGet("public_interface", "")}
}
func writePublicConfig(c publicAccessConfig) error {
	if c.PublicIP != "" && validatePublicAccess(c, managedStatusLAN(), managedSettingsNow().Port) != nil {
		return fmt.Errorf("公网入口设置校验失败")
	}
	text := fmt.Sprintf("set cudy_webfiles.main.public_enabled='%d'\nset cudy_webfiles.main.public_ip='%s'\nset cudy_webfiles.main.public_external_port='%d'\nset cudy_webfiles.main.public_listen_ip='%s'\nset cudy_webfiles.main.public_port='%d'\nset cudy_webfiles.main.public_interface='%s'\ncommit cudy_webfiles\n", map[bool]int{true: 1, false: 0}[c.Enabled], c.PublicIP, c.ExternalPort, c.ListenIP, c.ListenPort, c.Interface)
	if c.PublicIP == "" && (c.Enabled || c.ListenIP != "" || c.Interface != "") {
		return fmt.Errorf("公网入口未配置")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, "uci", "batch")
	cmd.Stdin = strings.NewReader(text)
	if cmd.Run() != nil {
		return fmt.Errorf("保存公网入口设置失败")
	}
	return nil
}
func managedStatusLAN() string {
	if base, e := packageDir(); e == nil {
		if s, e := getSnapshot(base); e == nil {
			return s.LAN
		}
	}
	return ""
}
func managedPublicTLS(ip string, create bool) (map[string][]byte, error) {
	if !usablePublicAddress(ip) {
		return nil, fmt.Errorf("公网 IPv4 或域名无效")
	}
	key, e := managedKey(false)
	if e != nil {
		return nil, e
	}
	name, purpose := publicTLSStorage(ip)
	b, e := readPrivate(name, 32768)
	var saved struct {
		IP    string
		Files map[string][]byte
	}
	if e == nil {
		b, e = openManaged(key, purpose, b)
		if e != nil || json.Unmarshal(b, &saved) != nil {
			return nil, fmt.Errorf("公网证书校验失败")
		}
	}
	if e != nil && !os.IsNotExist(e) {
		return nil, fmt.Errorf("无法读取公网证书")
	}
	valid := false
	if saved.IP == ip {
		if block, _ := pem.Decode(saved.Files["tls.crt"]); block != nil {
			if cert, e := x509.ParseCertificate(block.Bytes); e == nil && cert.VerifyHostname(ip) == nil && time.Now().After(cert.NotBefore) && time.Now().Before(cert.NotAfter) {
				valid = true
			}
		}
	}
	if !valid {
		if !create {
			return nil, fmt.Errorf("公网证书缺失、地址已变或已到期，请重新保存公网入口")
		}
		files, e := makeTLS(ip)
		if e != nil {
			return nil, e
		}
		saved.IP = ip
		saved.Files = files
		plain, _ := json.Marshal(saved)
		enc, e := sealManaged(key, purpose, plain)
		if e != nil {
			return nil, e
		}
		if e = writePrivate(name, enc); e != nil {
			return nil, e
		}
	}
	return saved.Files, nil
}
func runtimePublic(o owner) (publicAccessStatus, bool) {
	var s struct {
		Version string             `json:"version"`
		PID     int                `json:"runPID"`
		Start   string             `json:"runStart"`
		Public  publicAccessStatus `json:"public_access"`
	}
	b, e := os.ReadFile(runtimeDir + "/status.json")
	if e != nil || json.Unmarshal(b, &s) != nil || s.Version != version || s.PID != o.PID || s.Start != o.Start {
		return publicAccessStatus{}, false
	}
	return s.Public, true
}
func addPublicStatus(result map[string]any, running bool) {
	c := publicConfigNow()
	state := publicAccessStatus{Config: c}
	if usablePublicAddress(c.PublicIP) {
		state.URL = publicURL(c)
	}
	if running {
		var o owner
		if b, e := os.ReadFile(runtimeDir + "/owner.json"); e == nil && json.Unmarshal(b, &o) == nil {
			if p, ok := runtimePublic(o); ok && p.Config == c {
				state = p
			}
		}
	}
	result["public_access"] = state
	if usablePublicDomain(c.PublicIP) {
		ctx, cancel := context.WithTimeout(context.Background(), time.Second)
		ips, e := net.DefaultResolver.LookupIP(ctx, "ip4", c.PublicIP)
		cancel()
		resolved := []string{}
		if e == nil {
			for _, ip := range ips {
				if usablePublicIPv4(ip.String()) && len(resolved) < 8 {
					resolved = append(resolved, ip.String())
				}
			}
		}
		result["public_dns"] = map[string]any{"name": c.PublicIP, "ipv4": resolved, "ready": len(resolved) > 0, "checkedAt": time.Now().Format(time.RFC3339)}
	}
	if wan, e := publicWANNow(); e == nil {
		result["public_candidate"] = wan
	}
	if state.Active {
		result["access"] = fmt.Sprint(result["access"]) + " + 公网 HTTPS"
	}
}
func setPublicAccess(params map[string]json.RawMessage) error {
	old := publicConfigNow()
	c := old
	var oldTLS []byte
	var oldTLSError error
	restoreName := ""
	committed := false
	defer func() {
		if restoreName != "" && !committed {
			if oldTLSError == nil {
				_ = writePrivate(restoreName, oldTLS)
			} else {
				_ = os.Remove(managedPrivate + "/" + restoreName)
			}
		}
	}()
	if json.Unmarshal(params["enabled"], &c.Enabled) != nil {
		return fmt.Errorf("公网开关格式错误")
	}
	if c.Enabled {
		if json.Unmarshal(params["public_ip"], &c.PublicIP) != nil || json.Unmarshal(params["listen_port"], &c.ListenPort) != nil || json.Unmarshal(params["external_port"], &c.ExternalPort) != nil {
			return fmt.Errorf("公网地址或端口格式错误")
		}
		c.PublicIP = canonicalPublicAddress(c.PublicIP)
		wan, e := publicWANNow()
		if e != nil {
			return e
		}
		c.ListenIP = wan.Address
		c.Interface = wan.Interface
		if e = validatePublicAccess(c, managedStatusLAN(), managedSettingsNow().Port); e != nil {
			return e
		}
		restoreName, _ = publicTLSStorage(c.PublicIP)
		oldTLS, oldTLSError = readPrivate(restoreName, 32768)
		if oldTLSError != nil && !os.IsNotExist(oldTLSError) {
			return fmt.Errorf("无法备份原公网证书")
		}
		if _, e = managedPublicTLS(c.PublicIP, true); e != nil {
			return e
		}
	}
	if e := writePublicConfig(c); e != nil {
		return e
	}
	if !managedRunning() {
		committed = true
		return nil
	}
	for until := time.Now().Add(14 * time.Second); time.Now().Before(until); time.Sleep(250 * time.Millisecond) {
		var o owner
		if b, e := os.ReadFile(runtimeDir + "/owner.json"); e == nil && json.Unmarshal(b, &o) == nil {
			if s, ok := runtimePublic(o); ok && s.Config == c {
				if !c.Enabled || s.Active {
					committed = true
					return nil
				}
				if s.Error != "" {
					break
				}
			}
		}
	}
	_ = writePublicConfig(old)
	return fmt.Errorf("公网入口未能就绪，已请求恢复原开关；LAN 与 ZeroTier 保留")
}

type nftPublicRule struct {
	Handle  uint64 `json:"handle"`
	Comment string `json:"comment"`
}

func publicRules() ([]nftPublicRule, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	b, e := exec.CommandContext(ctx, "nft", "-j", "list", "chain", "inet", "fw4", "input").Output()
	var s struct {
		Nftables []struct {
			Rule *nftPublicRule `json:"rule"`
		} `json:"nftables"`
	}
	if e != nil || len(b) > 262144 || json.Unmarshal(b, &s) != nil {
		return nil, fmt.Errorf("无法核验入口防火墙规则")
	}
	var out []nftPublicRule
	for _, v := range s.Nftables {
		if v.Rule != nil && regexp.MustCompile(`^cudy-webfiles-public-[0-9]+-[0-9]+$`).MatchString(v.Rule.Comment) {
			out = append(out, *v.Rule)
		}
	}
	return out, nil
}
func removePublicRule(comment string) error {
	rules, e := publicRules()
	if e != nil {
		return e
	}
	var script string
	for _, r := range rules {
		if r.Comment == comment {
			script += fmt.Sprintf("delete rule inet fw4 input handle %d\n", r.Handle)
		}
	}
	if script != "" {
		return nftApply(script)
	}
	return nil
}
func cleanStalePublicRules() {
	rules, e := publicRules()
	if e != nil {
		return
	}
	for _, r := range rules {
		parts := strings.Split(r.Comment, "-")
		pid, _ := strconv.Atoi(parts[3])
		start, e := processStart(pid)
		if e != nil || start != parts[4] {
			_ = removePublicRule(r.Comment)
		}
	}
}
func ensurePublicRule(c publicAccessConfig, lan string, port int, comment string) error {
	rules, e := publicRules()
	if e != nil {
		return e
	}
	n := 0
	for _, r := range rules {
		if r.Comment == comment {
			n++
		}
	}
	if n == 1 {
		return nil
	}
	if n > 1 {
		if e = removePublicRule(comment); e != nil {
			return e
		}
	}
	s, e := publicRule(c, lan, port, comment)
	if e != nil {
		return e
	}
	return nftApply(s)
}

type publicChild struct {
	cmd     *exec.Cmd
	done    chan error
	expires time.Time
}

func (p *publicChild) stop() {
	if p != nil {
		_ = p.cmd.Process.Kill()
		<-p.done
	}
}
func startPublicChild(in publicGatewayInput) (*publicChild, error) {
	files, e := managedPublicTLS(in.Config.PublicIP, false)
	if e != nil {
		return nil, e
	}
	in.Files = files
	if e = os.MkdirAll(runtimeDir+"/public-jail", 0700); e != nil {
		return nil, e
	}
	st, e := os.Lstat(runtimeDir + "/public-jail")
	if e != nil || !st.IsDir() || st.Mode()&os.ModeSymlink != 0 {
		return nil, fmt.Errorf("公网隔离目录身份无效")
	}
	b, _ := json.Marshal(in)
	cmd := exec.Command(selfExe(), "__public_gateway")
	cmd.Env = []string{"GOMEMLIMIT=24MiB", "GOGC=50"}
	cmd.Stdin = bytes.NewReader(b)
	cmd.Stdout = io.Discard
	cmd.Stderr = io.Discard
	cmd.SysProcAttr = &syscall.SysProcAttr{Cloneflags: syscall.CLONE_NEWNS | syscall.CLONE_NEWPID, Pdeathsig: syscall.SIGKILL}
	if cmd.Start() != nil {
		return nil, fmt.Errorf("公网隔离进程启动失败")
	}
	block, _ := pem.Decode(files["tls.crt"])
	cert, _ := x509.ParseCertificate(block.Bytes)
	p := &publicChild{cmd: cmd, done: make(chan error, 1), expires: cert.NotAfter}
	go func() { p.done <- cmd.Wait() }()
	roots := x509.NewCertPool()
	roots.AppendCertsFromPEM(files["ca.crt"])
	tr := &http.Transport{TLSClientConfig: &tls.Config{RootCAs: roots, ServerName: in.Config.PublicIP, MinVersion: tls.VersionTLS12}, DialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
		return (&net.Dialer{}).DialContext(ctx, "tcp4", net.JoinHostPort(in.Config.ListenIP, strconv.Itoa(in.Config.ListenPort)))
	}}
	defer tr.CloseIdleConnections()
	client := &http.Client{Transport: tr, Timeout: 700 * time.Millisecond, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	for i := 0; i < 6; i++ {
		r, e := client.Get(publicURL(in.Config) + "/login")
		if e == nil {
			io.Copy(io.Discard, io.LimitReader(r.Body, 1024))
			r.Body.Close()
			if r.StatusCode == 200 {
				os.WriteFile(runtimeDir+"/public-ca.crt", files["ca.crt"], 0644)
				return p, nil
			}
		}
		time.Sleep(150 * time.Millisecond)
	}
	p.stop()
	return nil, fmt.Errorf("公网 HTTPS 本机证书或登录页检查未通过")
}
func watchPublicGateway(ctx context.Context, lan string, port int, ca []byte, o owner) (<-chan publicAccessStatus, func()) {
	updates := make(chan publicAccessStatus, 1)
	finished := make(chan struct{})
	ctx, cancel := context.WithCancel(ctx)
	go func() {
		defer close(finished)
		defer close(updates)
		comment := fmt.Sprintf("cudy-webfiles-public-%d-%s", o.PID, o.Start)
		cleanStalePublicRules()
		var child *publicChild
		var current publicAccessConfig
		var lastError string
		var failed publicAccessConfig
		failedSet := false
		stop := func() {
			if child != nil {
				child.stop()
				child = nil
			}
			_ = removePublicRule(comment)
		}
		defer stop()
		for {
			c := publicConfigNow()
			s := publicAccessStatus{Config: c}
			if usablePublicAddress(c.PublicIP) {
				s.URL = publicURL(c)
			}
			if c != current {
				stop()
				current = c
				failedSet = false
				lastError = ""
			}
			if c.Enabled {
				e := validatePublicAccess(c, lan, port)
				wan, we := publicWANNow()
				if e == nil && (we != nil || wan.Address != c.ListenIP || wan.Interface != c.Interface) {
					e = fmt.Errorf("WAN 地址或接口变化，公网入口已关闭；重新保存后启用")
				}
				var runtime struct {
					Ready bool   `json:"usersReady"`
					PID   int    `json:"runPID"`
					Start string `json:"runStart"`
				}
				b, _ := os.ReadFile(runtimeDir + "/status.json")
				_ = json.Unmarshal(b, &runtime)
				if e == nil && (!runtime.Ready || runtime.PID != o.PID || runtime.Start != o.Start) {
					e = fmt.Errorf("等待文件服务账号初始化完成")
				}
				if e != nil {
					stop()
					s.Error = e.Error()
				} else if !failedSet || failed != c {
					if child != nil {
						select {
						case <-child.done:
							child = nil
							_ = removePublicRule(comment)
							failed = c
							failedSet = true
							lastError = "公网隔离进程已退出，请关闭后重新开启入口"
						default:
						}
					}
					if child == nil && !failedSet {
						child, e = startPublicChild(publicGatewayInput{Config: c, LAN: lan, Port: port, BackendCA: ca})
						if e != nil {
							failed = c
							failedSet = true
							lastError = e.Error()
						}
					}
					if child != nil {
						if !time.Now().Before(child.expires) {
							stop()
							failed = c
							failedSet = true
							lastError = "公网证书已到期，请重新保存入口并导入新公网 CA"
						} else if treeRSS(child.cmd.Process.Pid) > 64*1024 {
							stop()
							failed = c
							failedSet = true
							lastError = "公网入口内存超过 64 MiB，已保护性停止"
						} else if e = ensurePublicRule(c, lan, port, comment); e != nil {
							stop()
							failed = c
							failedSet = true
							lastError = "公网防火墙规则未能核验，入口已关闭"
						}
					}
				}
				if lastError != "" {
					s.Error = lastError
				}
				if child != nil {
					s.Active = true
					s.PID = child.cmd.Process.Pid
					s.RSSKiB = treeRSS(s.PID)
				}
			} else {
				stop()
			}
			select {
			case updates <- s:
			case <-ctx.Done():
				return
			}
			select {
			case <-time.After(3 * time.Second):
			case <-ctx.Done():
				return
			}
		}
	}()
	return updates, func() { cancel(); <-finished }
}
func publicGatewayWorker() error {
	b, e := io.ReadAll(io.LimitReader(os.Stdin, 65537))
	if e != nil || len(b) > 65536 {
		return fmt.Errorf("invalid gateway input")
	}
	var in publicGatewayInput
	if json.Unmarshal(b, &in) != nil || validatePublicAccess(in.Config, in.LAN, in.Port) != nil {
		return fmt.Errorf("invalid gateway identity")
	}
	if e = syscall.Mount("", "/", "", syscall.MS_REC|syscall.MS_PRIVATE, ""); e != nil {
		return e
	}
	if e = syscall.Chroot(runtimeDir + "/public-jail"); e != nil {
		return e
	}
	if e = syscall.Chdir("/"); e != nil {
		return e
	}
	if e = syscall.Setgroups([]int{}); e != nil {
		return e
	}
	if e = syscall.Setgid(65534); e != nil {
		return e
	}
	if e = syscall.Setuid(65534); e != nil {
		return e
	}
	if _, _, e := syscall.Syscall6(syscall.SYS_PRCTL, 38, 1, 0, 0, 0, 0); e != 0 {
		return e
	}
	return servePublicGateway(in)
}
