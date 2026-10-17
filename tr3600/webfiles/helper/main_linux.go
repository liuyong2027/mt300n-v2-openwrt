//go:build linux

package main

import (
	"context"
	"crypto/sha256"
	"debug/elf"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"syscall"
	"time"
)

const runtimeDir = "/tmp/cudy-webfiles-managed"
const runtimeMarker = "Cudy WebFiles managed test v0.2\n"

type workerSpec struct {
	Volume       Volume
	Root, Binary string
	ReadOnly     bool
	Mount        MountInfo
}
type owner struct {
	PID        int
	Start, Exe string
}

func fatal(err error) { fmt.Fprintln(os.Stderr, "ERROR:", err); os.Exit(1) }
func main() {
	if len(os.Args) > 1 && os.Args[1] == "__public_gateway" {
		if err := publicGatewayWorker(); err != nil {
			fatal(err)
		}
		return
	}
	if len(os.Args) > 1 && os.Args[1] == "__worker" {
		if err := worker(); err != nil {
			fatal(err)
		}
		return
	}
	if len(os.Args) > 1 && os.Args[1] == "__probe" {
		if err := syscall.Mount("", "/", "", syscall.MS_REC|syscall.MS_PRIVATE, ""); err != nil {
			fatal(err)
		}
		return
	}
	if err := dispatch(); err != nil {
		fatal(err)
	}
}
func packageDir() (string, error) {
	exe, err := os.Executable()
	if err != nil {
		return "", err
	}
	exe, err = filepath.EvalSymlinks(exe)
	return filepath.Dir(filepath.Dir(exe)), err
}
func dispatch() error {
	if len(os.Args) < 2 {
		usage()
		return nil
	}
	action := os.Args[1]
	if action == "verify-binary" {
		if len(os.Args) != 3 {
			return fmt.Errorf("usage: cudy-webfiles verify-binary PATH")
		}
		if err := verifyBinary(os.Args[2]); err != nil {
			return err
		}
		fmt.Println("VERIFIED: static ARM64 Quantum matches the embedded SHA256")
		return nil
	}
	if action == "rpc" {
		return managedRPC(os.Args[2:])
	}
	if action == "version" {
		fmt.Println("Cudy WebFiles", version, "/ Quantum v2.0.0-stable+cudy-jti1")
		return nil
	}
	if action == "stop" {
		return stop()
	}
	if action == "reset" {
		return reset()
	}
	if action == "status" {
		b, e := os.ReadFile(runtimeDir + "/status.json")
		if e != nil {
			return e
		}
		var state map[string]any
		if e = json.Unmarshal(b, &state); e != nil {
			return e
		}
		state["running"] = false
		if ob, e := os.ReadFile(runtimeDir + "/owner.json"); e == nil {
			var o owner
			if json.Unmarshal(ob, &o) == nil {
				start, e := processStart(o.PID)
				if e == nil && start == o.Start {
					state["running"] = true
				}
			}
		}
		b, _ = json.MarshalIndent(state, "", "  ")
		fmt.Println(string(b))
		return nil
	}
	if os.Geteuid() != 0 {
		return fmt.Errorf("run this command from a root SSH session")
	}
	if runtime.GOARCH != "arm64" {
		return fmt.Errorf("requires ARM64")
	}
	base, err := packageDir()
	if err != nil {
		return err
	}
	f := flag.NewFlagSet(action, flag.ContinueOnError)
	id := f.String("volume", "", "authorized volume ID from list")
	port := f.Int("port", 8080, "LAN HTTPS port")
	rw := f.Bool("read-write", false, "allow writes if Cudy authorization also allows them")
	if err = f.Parse(os.Args[2:]); err != nil {
		return err
	}
	if f.NArg() != 0 {
		return fmt.Errorf("unexpected arguments")
	}
	if action == "boot-run" {
		return runAtBoot(base, *id, *port, *rw)
	}
	snap, err := getSnapshot(base)
	if err != nil {
		return err
	}
	if action == "list" {
		b, _ := json.MarshalIndent(snap, "", "  ")
		fmt.Println(string(b))
		return nil
	}
	if action != "check" && action != "run" {
		usage()
		return fmt.Errorf("unknown command")
	}
	vol, mount, err := getGuard(base, *id)
	if err != nil {
		return err
	}
	if *rw && vol.ReadOnly {
		return fmt.Errorf("Cudy authorization is read-only; cannot enable writes")
	}
	if *port < 1024 || *port > 65535 {
		return fmt.Errorf("port must be 1024..65535")
	}
	if err = verifyBinary(base + "/bin/filebrowser"); err != nil {
		return err
	}
	if err = probeNamespaces(); err != nil {
		return fmt.Errorf("required mount/PID namespaces unavailable: %w (no unsafe fallback)", err)
	}
	if err = exec.Command("nft", "--version").Run(); err != nil {
		return fmt.Errorf("nft is required for the temporary LAN-only input filter: %w", err)
	}
	memData, err := os.ReadFile("/proc/meminfo")
	if err != nil {
		return err
	}
	mem, err := readMemAvailable(string(memData))
	if err != nil {
		return err
	}
	fmt.Printf("READY: %s %s %s; LAN %s (%s); MemAvailable=%d KiB; mode=%s\n", vol.ID, vol.Device, vol.Target, snap.LAN, snap.Interface, mem, map[bool]string{true: "read-write", false: "read-only"}[*rw])
	if action == "check" {
		return nil
	}
	if mem < 128*1024 {
		return fmt.Errorf("MemAvailable below the test startup threshold of 128 MiB")
	}
	return runService(base, vol, mount, *port, *rw)
}
func usage() {
	fmt.Printf("Cudy WebFiles %s (ARM64/OpenWrt, LuCI managed account)\n  cudy-webfiles list\n  cudy-webfiles check --volume usb_UUID\n  cudy-webfiles run --volume usb_UUID [--read-write] [--port 8443]\n  cudy-webfiles status\n  cudy-webfiles stop\n  cudy-webfiles rpc list\n", version)
}
func getSnapshot(base string) (Snapshot, error) {
	s, e := getSnapshotContext(context.Background(), base, 2*time.Second)
	var startup *startupError
	if errors.As(e, &startup) && startup.Code == "startup_adapter_timeout" {
		return s, &serviceStopError{"status_check_timeout", "USB/LAN 状态检查超过 2 秒，已保护性停止", e}
	}
	return s, e
}
func getSnapshotContext(parent context.Context, base string, limit time.Duration) (Snapshot, error) {
	ctx, cancel := context.WithTimeout(parent, limit)
	defer cancel()
	cmd := exec.CommandContext(ctx, "/usr/bin/lua", base+"/adapter.lua")
	out, err := cmd.Output()
	if err != nil {
		if ctx.Err() == context.DeadlineExceeded {
			return Snapshot{}, &startupError{"startup_adapter_timeout", "USB/LAN 状态检查暂未完成，等待重试", true, ctx.Err()}
		}
		if exit, ok := err.(*exec.ExitError); ok {
			message := string(exit.Stderr)
			for _, transient := range []string{"Cannot read LAN status from ubus", "LAN is not ready", "No LAN IPv4 address", "No LAN interface"} {
				if strings.Contains(message, transient) {
					return Snapshot{}, &startupError{"startup_lan_wait", "等待局域网接口及地址就绪", true, err}
				}
			}
			return Snapshot{}, &startupError{"startup_adapter_failed", "USB/LAN 状态适配器检查失败，拒绝启动", false, err}
		}
		return Snapshot{}, &startupError{"startup_adapter_failed", "无法执行 USB/LAN 状态检查，拒绝启动", false, err}
	}
	var s Snapshot
	if err = json.Unmarshal(out, &s); err != nil {
		return s, &startupError{"startup_snapshot_invalid", "USB/LAN 状态格式无效，拒绝启动", false, err}
	}
	if err = validateSnapshot(s); err != nil {
		return s, &startupError{"startup_snapshot_invalid", "USB/LAN 状态身份校验失败，拒绝启动", false, err}
	}
	return s, nil
}
func getGuard(base, id string) (Volume, MountInfo, error) {
	s, e := getSnapshot(base)
	if e != nil {
		return Volume{}, MountInfo{}, e
	}
	return guardVolume(s, id)
}
func guardVolume(s Snapshot, id string) (Volume, MountInfo, error) {
	v, e := selectVolume(s, id)
	if e != nil {
		return v, MountInfo{}, e
	}
	resolved, e := filepath.EvalSymlinks(v.Target)
	if e != nil || resolved != v.Target {
		return v, MountInfo{}, fmt.Errorf("mount path is unavailable or uses a symlink")
	}
	b, e := os.ReadFile("/proc/self/mountinfo")
	if e != nil {
		return v, MountInfo{}, e
	}
	m, e := parseMount(string(b), v.Target)
	if e != nil {
		return v, m, e
	}
	return v, m, mountMatches(v, m)
}
func reset() error {
	if os.Geteuid() != 0 {
		return fmt.Errorf("reset requires root")
	}
	st, e := os.Lstat(runtimeDir)
	if os.IsNotExist(e) {
		return nil
	}
	if e != nil {
		return e
	}
	if !st.IsDir() || st.Mode()&os.ModeSymlink != 0 {
		return fmt.Errorf("unsafe runtime directory")
	}
	marker, e := os.ReadFile(runtimeDir + "/package-marker")
	if e != nil || string(marker) != runtimeMarker {
		return fmt.Errorf("directory is not owned by this test kit; refusing reset")
	}
	if b, e := os.ReadFile(runtimeDir + "/owner.json"); e == nil {
		var o owner
		if json.Unmarshal(b, &o) != nil {
			return fmt.Errorf("invalid owner file")
		}
		start, err := processStart(o.PID)
		if err == nil && start == o.Start {
			return fmt.Errorf("test process is still running; stop it first")
		}
	}
	if b, e := os.ReadFile(runtimeDir + "/table.txt"); e == nil {
		t := string(b)
		if !regexpTable(t) {
			return fmt.Errorf("invalid firewall table name")
		}
		if e = nftApply("delete table inet " + t + "\n"); e != nil {
			fmt.Fprintln(os.Stderr, "Table may already be removed:", e)
		}
	}
	return os.RemoveAll(runtimeDir)
}
func regexpTable(t string) bool {
	if !strings.HasPrefix(t, "cudy_webfiles_managed_") {
		return false
	}
	_, e := strconv.ParseUint(strings.TrimPrefix(t, "cudy_webfiles_managed_"), 10, 32)
	return e == nil
}
func verifyBinary(path string) error {
	expected, e := hex.DecodeString(quantumHash)
	if e != nil || len(expected) != sha256.Size {
		return fmt.Errorf("Quantum SHA256 was not bound to this helper at build time")
	}
	f, e := os.Open(path)
	if e != nil {
		return e
	}
	defer f.Close()
	h := sha256.New()
	if _, e = io.Copy(h, f); e != nil {
		return e
	}
	if hex.EncodeToString(h.Sum(nil)) != quantumHash {
		return fmt.Errorf("packaged ARM64 Quantum SHA256 mismatch")
	}
	ef, e := elf.Open(path)
	if e != nil {
		return e
	}
	defer ef.Close()
	if ef.Machine != elf.EM_AARCH64 {
		return fmt.Errorf("Quantum is not AArch64")
	}
	for _, p := range ef.Progs {
		if p.Type == elf.PT_INTERP {
			return fmt.Errorf("this kit expects a static upstream executable; dynamic ELF requires a reviewed library adapter")
		}
	}
	return nil
}
func selfExe() string {
	e, err := os.Executable()
	if err != nil {
		panic(err)
	}
	return e
}
func probeNamespaces() error {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	c := exec.CommandContext(ctx, selfExe(), "__probe")
	c.SysProcAttr = &syscall.SysProcAttr{Cloneflags: syscall.CLONE_NEWNS | syscall.CLONE_NEWPID, Pdeathsig: syscall.SIGKILL}
	out, e := c.CombinedOutput()
	if e != nil {
		return fmt.Errorf("%s: %w", strings.TrimSpace(string(out)), e)
	}
	return nil
}
func processStart(pid int) (string, error) {
	b, e := os.ReadFile(fmt.Sprintf("/proc/%d/stat", pid))
	if e != nil {
		return "", e
	}
	i := strings.LastIndex(string(b), ")")
	if i < 0 {
		return "", fmt.Errorf("bad proc stat")
	}
	f := strings.Fields(string(b)[i+1:])
	if len(f) < 20 {
		return "", fmt.Errorf("short proc stat")
	}
	return f[19], nil
}
func stop() error {
	if os.Geteuid() != 0 {
		return fmt.Errorf("stop requires root")
	}
	st, e := os.Lstat(runtimeDir)
	if os.IsNotExist(e) {
		fmt.Println("Stopped (no active test)")
		return nil
	}
	if e != nil {
		return e
	}
	if !st.IsDir() || st.Mode()&os.ModeSymlink != 0 {
		return fmt.Errorf("unsafe runtime directory")
	}
	b, e := os.ReadFile(runtimeDir + "/owner.json")
	if os.IsNotExist(e) {
		fmt.Println("Stopped (no owner marker)")
		return nil
	}
	if e != nil {
		return e
	}
	var o owner
	if e = json.Unmarshal(b, &o); e != nil {
		return e
	}
	if o.PID <= 1 {
		return fmt.Errorf("invalid owner PID")
	}
	start, e := processStart(o.PID)
	if e != nil {
		return fmt.Errorf("stale test directory; inspect and remove %s manually", runtimeDir)
	}
	exe, e := os.Readlink(fmt.Sprintf("/proc/%d/exe", o.PID))
	if e != nil || exe != o.Exe || start != o.Start {
		return fmt.Errorf("owner identity changed; refusing to signal another process")
	}
	if e = syscall.Kill(o.PID, syscall.SIGTERM); e != nil {
		return e
	}
	for i := 0; i < 100; i++ {
		if _, e = os.Stat(runtimeDir + "/owner.json"); os.IsNotExist(e) {
			fmt.Println("Stopped")
			return nil
		}
		time.Sleep(100 * time.Millisecond)
	}
	return fmt.Errorf("stop timed out; inspect process %d before unplugging", o.PID)
}
func nftScript(table string, s Snapshot, port int) (string, error) {
	rule, err := accessFilterRule(table, s, port, "")
	if err != nil {
		return "", err
	}
	return fmt.Sprintf("add table inet %s\nadd chain inet %s input { type filter hook input priority -10; policy accept; }\n", table, table) + rule, nil
}
func nftApply(script string) error {
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	c := exec.CommandContext(ctx, "nft", "-f", "-")
	c.Stdin = strings.NewReader(script)
	out, e := c.CombinedOutput()
	if e != nil {
		return fmt.Errorf("temporary firewall filter failed: %s: %w", out, e)
	}
	return nil
}

type cappedLog struct {
	f       *os.File
	written int64
}

func (l *cappedLog) Write(p []byte) (int, error) {
	n := len(p)
	left := int64(2*1024*1024) - l.written
	if left <= 0 {
		return n, nil
	}
	q := p
	if int64(len(q)) > left {
		q = q[:left]
	}
	k, e := l.f.Write(q)
	l.written += int64(k)
	return n, e
}
func runService(base string, vol Volume, mount MountInfo, port int, rw bool) (err error) {
	return runServiceContext(context.Background(), base, vol, mount, port, rw)
}
func runServiceContext(ctx context.Context, base string, vol Volume, mount MountInfo, port int, rw bool) (err error) {
	if ctx.Err() != nil {
		return ctx.Err()
	}
	signals := make(chan os.Signal, 1)
	signal.Notify(signals, syscall.SIGINT, syscall.SIGTERM, syscall.SIGHUP)
	defer signal.Stop(signals)
	if err = os.Mkdir(runtimeDir, 0700); err != nil {
		return fmt.Errorf("test already running or stale runtime directory: %w", err)
	}
	if err = os.WriteFile(runtimeDir+"/package-marker", []byte(runtimeMarker), 0600); err != nil {
		return err
	}
	// Keep diagnostics and certificates after stop; only the owner marker and firewall rule are removed.
	defer os.Remove(runtimeDir + "/owner.json")
	start, err := processStart(os.Getpid())
	if err != nil {
		return err
	}
	o := owner{os.Getpid(), start, selfExe()}
	b, _ := json.Marshal(o)
	if err = os.WriteFile(runtimeDir+"/owner.json", b, 0600); err != nil {
		return err
	}
	defer func() { recordManagedStop(err, o) }()
	os.Mkdir(runtimeDir+"/input", 0700)
	os.Mkdir(runtimeDir+"/jail", 0700)
	s, err := getSnapshotContext(ctx, base, 5*time.Second)
	if err != nil {
		return err
	}
	fresh, err := getSnapshotContext(ctx, base, 5*time.Second)
	if err != nil {
		return err
	}
	v, m, err := guardVolume(fresh, vol.ID)
	if err != nil {
		return err
	}
	if v != vol || m != mount {
		return fmt.Errorf("USB authorization changed during startup")
	}
	ln, err := net.Listen("tcp", net.JoinHostPort(s.LAN, strconv.Itoa(port)))
	if err != nil {
		return &serviceStopError{"startup_listener_unavailable", "局域网地址或 HTTPS 端口不可用，请检查端口占用", err}
	}
	ln.Close()
	registry, err := ensureManagedRegistry()
	if err != nil {
		return &serviceStopError{"startup_account_unavailable", "无法读取有效网页账号，请检查 LuCI 账号设置", err}
	}
	account := primaryAccount(registry)
	tlsFiles, err := managedTLS(s.LAN)
	if err != nil {
		return &serviceStopError{"startup_certificate_unavailable", "已保存的 HTTPS 证书不适用于当前地址或时间，请检查系统时间及证书有效期", err}
	}
	for n, data := range tlsFiles {
		if err = os.WriteFile(runtimeDir+"/input/"+n, data, 0600); err != nil {
			return err
		}
	}
	os.WriteFile(runtimeDir+"/ca.crt", tlsFiles["ca.crt"], 0644)
	config, err := makeConfig(vol, s.LAN, port, rw, "/usb", "/state", "/cache", account.Password)
	if err != nil {
		return err
	}
	config, err = managedQuantumConfig(config, account)
	if err != nil {
		return err
	}
	if err = os.WriteFile(runtimeDir+"/input/config.yaml", config, 0600); err != nil {
		return err
	}
	table := "cudy_webfiles_managed_" + strconv.Itoa(os.Getpid())
	script, err := nftScript(table, s, port)
	if err != nil {
		return err
	}
	if err = nftApply(script); err != nil {
		return err
	}
	os.WriteFile(runtimeDir+"/table.txt", []byte(table), 0600)
	defer func() {
		if e := nftApply("delete table inet " + table + "\n"); e != nil {
			fmt.Fprintln(os.Stderr, "Cleanup warning:", e)
		}
	}()
	spec := workerSpec{Volume: vol, Root: runtimeDir + "/jail", Binary: base + "/bin/filebrowser", ReadOnly: !rw || vol.ReadOnly, Mount: mount}
	b, _ = json.Marshal(spec)
	if err = os.WriteFile(runtimeDir+"/worker.json", b, 0600); err != nil {
		return err
	}
	logFile, err := os.OpenFile(runtimeDir+"/quantum.log", os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0600)
	if err != nil {
		return err
	}
	defer logFile.Close()
	writer := &cappedLog{f: logFile}
	cmd := exec.Command(selfExe(), "__worker")
	cmd.SysProcAttr = &syscall.SysProcAttr{Cloneflags: syscall.CLONE_NEWNS | syscall.CLONE_NEWPID, Pdeathsig: syscall.SIGKILL}
	cmd.Stdout = writer
	cmd.Stderr = writer
	if ctx.Err() != nil {
		return ctx.Err()
	}
	if err = cmd.Start(); err != nil {
		return err
	}
	done := make(chan error, 1)
	go func() { done <- cmd.Wait() }()
	terminate := func() { _ = cmd.Process.Kill(); <-done }
	fmt.Printf("HTTPS: https://%s:%d\nAccount: %s (managed in LuCI)\nCA certificate: %s/ca.crt\n", s.LAN, port, account.Username, runtimeDir)
	initContext, cancelInit := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancelInit()
	usersInitialized := make(chan error, 1)
	go func() {
		usersInitialized <- initializeManagedUsers(initContext, fmt.Sprintf("https://%s:%d", s.LAN, port), tlsFiles["ca.crt"], registry, spec.ReadOnly)
	}()
	usersReady := false
	stats, err := os.OpenFile(runtimeDir+"/resources.csv", os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0600)
	if err != nil {
		terminate()
		return err
	}
	defer stats.Close()
	fmt.Fprintln(stats, "time,mem_available_kib,worker_tree_rss_kib,load1")
	baseline := signature(s, vol, mount)
	zeroTierContext, cancelZeroTier := context.WithCancel(context.Background())
	defer cancelZeroTier()
	zeroTierUpdates := watchZeroTier(zeroTierContext, s.LAN, port)
	zeroTierState := zeroTierAccessStatus{URL: fmt.Sprintf("https://%s:%d", s.LAN, port)}
	publicUpdates, closePublic := watchPublicGateway(context.Background(), s.LAN, port, tlsFiles["ca.crt"], o)
	defer closePublic()
	publicState := publicAccessStatus{Config: publicConfigNow()}
	ticker := time.NewTicker(time.Second)
	defer ticker.Stop()
	count := 0
	minMem := int64(1 << 60)
	for {
		select {
		case update, open := <-publicUpdates:
			if !open {
				publicUpdates = nil
				continue
			}
			publicState = update
		case update, open := <-zeroTierUpdates:
			if !open {
				zeroTierUpdates = nil
				continue
			}
			iface := ""
			if update.Active {
				iface = update.Interface
			}
			rule, e := accessFilterRule(table, s, port, iface)
			if e == nil {
				e = nftApply("flush chain inet " + table + " input\n" + rule)
			}
			if e != nil {
				terminate()
				return &serviceStopError{"access_policy_update_failed", "访问规则更新失败，服务已保护性停止", e}
			}
			zeroTierState = update
		case e := <-usersInitialized:
			if e != nil {
				terminate()
				return &serviceStopError{"user_initialization_failed", "用户初始化未通过，服务已停止", e}
			}
			usersReady = true
			usersInitialized = nil
		case <-signals:
			terminate()
			return nil
		case e := <-done:
			return &serviceStopError{"worker_exited", "隔离的文件服务进程已退出", e}
		case <-ticker.C:
			now, e := getSnapshot(base)
			if e != nil {
				terminate()
				if _, ok := e.(*serviceStopError); ok {
					return e
				}
				return &serviceStopError{"status_check_failed", "无法读取 USB/LAN 状态，已保护性停止", e}
			}
			v, m, e := guardVolume(now, vol.ID)
			if e != nil || signature(now, v, m) != baseline {
				terminate()
				return &serviceStopError{"access_state_changed", "USB 挂载、授权或 LAN 状态变化，已保护性停止", e}
			}
			mb, _ := os.ReadFile("/proc/meminfo")
			mem, e := readMemAvailable(string(mb))
			if e != nil {
				terminate()
				return e
			}
			if mem < minMem {
				minMem = mem
			}
			load, _ := os.ReadFile("/proc/loadavg")
			load1 := strings.Fields(string(load))
			lv := ""
			if len(load1) > 0 {
				lv = load1[0]
			}
			rss := treeRSS(cmd.Process.Pid)
			count++
			if count%5 == 0 {
				fmt.Fprintf(stats, "%s,%d,%d,%s\n", time.Now().Format(time.RFC3339), mem, rss, lv)
				stats.Sync()
			}
			status := map[string]any{"version": version, "url": fmt.Sprintf("https://%s:%d", s.LAN, port), "volume": vol.ID, "readOnly": spec.ReadOnly, "memAvailableKiB": mem, "minMemAvailableKiB": minMem, "workerTreeRssKiB": rss, "resourceWarning": mem < 96*1024, "guardIntervalSeconds": 1, "usersReady": usersReady, "userCount": len(registry.Users), "runPID": o.PID, "runStart": o.Start}
			status["zerotier"] = zeroTierState
			status["public_access"] = publicState
			sb, _ := json.MarshalIndent(status, "", "  ")
			os.WriteFile(runtimeDir+"/status.json.tmp", append(sb, '\n'), 0600)
			os.Rename(runtimeDir+"/status.json.tmp", runtimeDir+"/status.json")
			if mem < 64*1024 {
				terminate()
				return &serviceStopError{"memory_low", "可用内存低于 64 MiB，已停止保护路由器", nil}
			}
		}
	}
}
func treeRSS(pid int) int64 {
	// OpenWrt may omit /proc/PID/task/TID/children (CONFIG_CHECKPOINT_RESTORE).
	// Build the process tree from status files visible in the supervisor's proc.
	type process struct {
		parent int
		rss    int64
	}
	processes := map[int]process{}
	entries, _ := os.ReadDir("/proc")
	for _, entry := range entries {
		n, err := strconv.Atoi(entry.Name())
		if err != nil || n < 1 {
			continue
		}
		b, err := os.ReadFile("/proc/" + entry.Name() + "/status")
		if err != nil {
			continue
		}
		p := process{}
		for _, line := range strings.Split(string(b), "\n") {
			fields := strings.Fields(line)
			if len(fields) < 2 {
				continue
			}
			switch fields[0] {
			case "PPid:":
				p.parent, _ = strconv.Atoi(fields[1])
			case "VmRSS:":
				p.rss, _ = strconv.ParseInt(fields[1], 10, 64)
			}
		}
		processes[n] = p
	}
	seen := map[int]bool{}
	queue := []int{pid}
	var total int64
	for len(queue) > 0 {
		n := queue[0]
		queue = queue[1:]
		if seen[n] {
			continue
		}
		seen[n] = true
		total += processes[n].rss
		for child, p := range processes {
			if p.parent == n {
				queue = append(queue, child)
			}
		}
	}
	return total
}
func mkdir(path string) error { return os.MkdirAll(path, 0755) }
func bind(src, dst string, ro bool) error {
	st, e := os.Stat(src)
	if e != nil {
		return e
	}
	if st.IsDir() {
		if e = mkdir(dst); e != nil {
			return e
		}
	} else {
		if e = mkdir(filepath.Dir(dst)); e != nil {
			return e
		}
		f, e := os.OpenFile(dst, os.O_CREATE|os.O_WRONLY, 0755)
		if e != nil {
			return e
		}
		f.Close()
	}
	if e = syscall.Mount(src, dst, "", syscall.MS_BIND, ""); e != nil {
		return e
	}
	flags := uintptr(syscall.MS_BIND | syscall.MS_REMOUNT | syscall.MS_NOSUID | syscall.MS_NODEV)
	if ro {
		flags |= syscall.MS_RDONLY
	}
	return syscall.Mount("", dst, "", flags, "")
}
func worker() error {
	// Private state files use explicit 0600/0700 permissions. Internal jail
	// directories must remain traversable by UID 65534 even when a detached
	// launcher inherits a restrictive umask such as 077.
	syscall.Umask(0022)
	if os.Getpid() != 1 {
		return fmt.Errorf("worker must be PID 1 in a new PID namespace")
	}
	b, e := os.ReadFile(runtimeDir + "/worker.json")
	if e != nil {
		return e
	}
	var spec workerSpec
	if e = json.Unmarshal(b, &spec); e != nil {
		return e
	}
	if spec.Root != runtimeDir+"/jail" {
		return fmt.Errorf("invalid jail path")
	}
	if e = syscall.Mount("", "/", "", syscall.MS_REC|syscall.MS_PRIVATE, ""); e != nil {
		return e
	}
	// Compare the inherited mount namespace immediately before pinning the authorized mount.
	b, e = os.ReadFile("/proc/self/mountinfo")
	if e != nil {
		return e
	}
	m, e := parseMount(string(b), spec.Volume.Target)
	if e != nil || !sameClonedMount(spec.Mount, m) {
		return fmt.Errorf("mount changed before isolation")
	}
	if e = syscall.Mount("tmpfs", spec.Root, "tmpfs", syscall.MS_NOSUID|syscall.MS_NODEV, "size=1m,mode=0755"); e != nil {
		return e
	}
	root := spec.Root
	for _, name := range []string{"app", "usb", "state", "cache", "dev", "proc", "tmp"} {
		if e = mkdir(root + "/" + name); e != nil {
			return e
		}
	}
	if e = bind(spec.Binary, root+"/app/filebrowser", true); e != nil {
		return e
	}
	if e = bind(spec.Volume.Target, root+"/usb", spec.ReadOnly); e != nil {
		return e
	}
	if e = syscall.Mount("", root+"/usb", "", syscall.MS_BIND|syscall.MS_REMOUNT|syscall.MS_NOSUID|syscall.MS_NODEV|syscall.MS_NOEXEC|map[bool]uintptr{true: syscall.MS_RDONLY, false: 0}[spec.ReadOnly], ""); e != nil {
		return e
	}
	// Hide existing Samba databases with a read-only empty mount only inside this namespace.
	metadata := root + "/usb/.samba-metadata"
	if st, err := os.Lstat(metadata); err == nil {
		if !st.IsDir() || st.Mode()&os.ModeSymlink != 0 {
			return fmt.Errorf("unsafe Samba metadata directory")
		}
		if e = mkdir(root + "/blocked"); e != nil {
			return e
		}
		if e = bind(root+"/blocked", metadata, true); e != nil {
			return e
		}
	} else if !os.IsNotExist(err) {
		return err
	}
	for _, item := range []struct{ name, size string }{{"state", "32m"}, {"cache", "16m"}, {"tmp", "4m"}} {
		if e = syscall.Mount("tmpfs", root+"/"+item.name, "tmpfs", syscall.MS_NOSUID|syscall.MS_NODEV|syscall.MS_NOEXEC, "size="+item.size+",mode=0700,uid=65534,gid=65534"); e != nil {
			return e
		}
	}
	for _, name := range []string{"tls.crt", "tls.key", "config.yaml"} {
		data, e := os.ReadFile(runtimeDir + "/input/" + name)
		if e != nil {
			return e
		}
		dst := root + "/state/" + name
		if e = os.WriteFile(dst, data, 0600); e != nil {
			return e
		}
		if e = os.Chown(dst, 65534, 65534); e != nil {
			return e
		}
	}
	// Mount only a private /proc and the three required device nodes; no router /etc, /root or /sys.
	if e = syscall.Mount("proc", root+"/proc", "proc", syscall.MS_NOSUID|syscall.MS_NODEV|syscall.MS_NOEXEC, ""); e != nil {
		return e
	}
	for _, n := range []string{"null", "urandom", "random"} {
		if e = bind("/dev/"+n, root+"/dev/"+n, false); e != nil {
			return e
		}
		if e = syscall.Mount("", root+"/dev/"+n, "", syscall.MS_BIND|syscall.MS_REMOUNT|syscall.MS_NOSUID, ""); e != nil {
			return e
		}
	}
	if e = syscall.Chdir(root); e != nil {
		return e
	}
	if e = syscall.Chroot("."); e != nil {
		return e
	}
	if e = syscall.Chdir("/"); e != nil {
		return e
	}
	if _, _, errno := syscall.Syscall6(syscall.SYS_PRCTL, 38, 1, 0, 0, 0, 0); errno != 0 {
		return errno
	} // PR_SET_NO_NEW_PRIVS
	command := func(args ...string) *exec.Cmd {
		cmd := exec.Command("/app/filebrowser", append([]string{"-c", "/state/config.yaml"}, args...)...)
		cmd.Dir = "/state"
		cmd.Env = []string{"PATH=/disabled-tools", "HOME=/state", "TMPDIR=/tmp", "GOMAXPROCS=2", "GOMEMLIMIT=160MiB", "GOGC=75"}
		cmd.Stdout, cmd.Stderr = os.Stdout, os.Stderr
		cmd.SysProcAttr = &syscall.SysProcAttr{Credential: &syscall.Credential{Uid: 65534, Gid: 65534, Groups: []uint32{}}, Pdeathsig: syscall.SIGKILL}
		return cmd
	}
	// Indexing/exclusion rules alone do not enforce downloads. Install a real deny rule.
	if e = command("set", "rule", "-s", "USB", "-p", "/.samba-metadata/", "-r", "all").Run(); e != nil {
		return fmt.Errorf("Samba metadata access rule failed: %w", e)
	}
	cmd := command()
	if e = cmd.Start(); e != nil {
		return e
	}
	return cmd.Wait()
}
