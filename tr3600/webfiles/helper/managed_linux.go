//go:build linux

package main

import (
	"bytes"
	"context"
	"crypto/rand"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"encoding/pem"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"syscall"
	"time"
)

const managedPrivate = "/etc/cudy-webfiles"
const managedPrivateMarker = "Cudy WebFiles LuCI private settings v0.2\n"
const managedInit = "/etc/init.d/cudy-webfiles"

func privateDir(create bool) error {
	st, e := os.Lstat(managedPrivate)
	if os.IsNotExist(e) && create {
		if e = os.Mkdir(managedPrivate, 0700); e != nil {
			return e
		}
		if e = os.WriteFile(managedPrivate+"/marker", []byte(managedPrivateMarker), 0600); e != nil {
			return e
		}
		st, e = os.Lstat(managedPrivate)
	}
	if e != nil {
		return e
	}
	u, ok := st.Sys().(*syscall.Stat_t)
	if !ok || u.Uid != 0 || !st.IsDir() || st.Mode().Perm() != 0700 || st.Mode()&os.ModeSymlink != 0 {
		return fmt.Errorf("私有设置目录权限或身份不符")
	}
	b, e := readPrivate("marker", 256)
	if e != nil || string(b) != managedPrivateMarker {
		return fmt.Errorf("私有设置标记不符")
	}
	return nil
}
func readPrivate(name string, limit int64) ([]byte, error) {
	if filepath.Base(name) != name {
		return nil, fmt.Errorf("invalid private filename")
	}
	fd, e := syscall.Open(managedPrivate+"/"+name, syscall.O_RDONLY|syscall.O_NOFOLLOW|syscall.O_CLOEXEC, 0)
	if e != nil {
		return nil, e
	}
	f := os.NewFile(uintptr(fd), name)
	defer f.Close()
	st, e := f.Stat()
	if e != nil {
		return nil, e
	}
	u, ok := st.Sys().(*syscall.Stat_t)
	if !ok || u.Uid != 0 || !st.Mode().IsRegular() || st.Mode().Perm() != 0600 || st.Size() > limit {
		return nil, fmt.Errorf("私有设置文件权限或大小不符")
	}
	return io.ReadAll(io.LimitReader(f, limit+1))
}
func writePrivate(name string, b []byte) error {
	if filepath.Base(name) != name {
		return fmt.Errorf("invalid private filename")
	}
	if e := privateDir(true); e != nil {
		return e
	}
	f, e := os.CreateTemp(managedPrivate, ".write-")
	if e != nil {
		return e
	}
	p := f.Name()
	defer os.Remove(p)
	if e = f.Chmod(0600); e == nil {
		_, e = f.Write(b)
	}
	if e == nil {
		e = f.Sync()
	}
	closeErr := f.Close()
	if e == nil {
		e = closeErr
	}
	if e != nil {
		return e
	}
	if st, e := os.Lstat(managedPrivate + "/" + name); e == nil && (!st.Mode().IsRegular() || st.Mode()&os.ModeSymlink != 0) {
		return fmt.Errorf("拒绝覆盖非普通私有文件")
	}
	return os.Rename(p, managedPrivate+"/"+name)
}
func managedKey(create bool) ([]byte, error) {
	if e := privateDir(create); e != nil {
		return nil, e
	}
	key, e := readPrivate("account.key", 32)
	if os.IsNotExist(e) && create {
		key = make([]byte, 32)
		if _, e = rand.Read(key); e != nil {
			return nil, e
		}
		if e = writePrivate("account.key", key); e != nil {
			return nil, e
		}
		return key, nil
	}
	if e != nil {
		return nil, e
	}
	if len(key) != 32 {
		return nil, fmt.Errorf("私有设置密钥无效")
	}
	return key, nil
}
func loadLegacyManagedAccount() (managedAccount, error) {
	var a managedAccount
	key, e := managedKey(false)
	if e != nil {
		return a, e
	}
	b, e := readPrivate("account.enc", 16384)
	if e != nil {
		return a, e
	}
	b, e = openManaged(key, "account", b)
	if e != nil {
		return a, fmt.Errorf("账号设置校验失败")
	}
	if e = json.Unmarshal(b, &a); e != nil {
		return a, fmt.Errorf("账号设置格式错误")
	}
	return a, validateManagedAccount(a)
}
func saveLegacyManagedAccount(a managedAccount) error {
	if e := validateManagedAccount(a); e != nil {
		return e
	}
	key, e := managedKey(true)
	if e != nil {
		return e
	}
	plain, _ := json.Marshal(a)
	stored, e := sealManaged(key, "account", plain)
	if e != nil {
		return e
	}
	return writePrivate("account.enc", stored)
}
func managedTLS(lan string) (map[string][]byte, error) {
	key, e := managedKey(false)
	if e != nil {
		return nil, e
	}
	b, e := readPrivate("tls.enc", 32768)
	var files map[string][]byte
	if os.IsNotExist(e) {
		files, e = makeTLS(lan)
		if e != nil {
			return nil, e
		}
		plain, _ := json.Marshal(files)
		b, e = sealManaged(key, "tls", plain)
		if e != nil {
			return nil, e
		}
		if e = writePrivate("tls.enc", b); e != nil {
			return nil, e
		}
	} else if e != nil {
		return nil, e
	} else {
		b, e = openManaged(key, "tls", b)
		if e != nil {
			return nil, fmt.Errorf("证书设置校验失败")
		}
		if e = json.Unmarshal(b, &files); e != nil {
			return nil, e
		}
	}
	block, _ := pem.Decode(files["tls.crt"])
	if block == nil {
		return nil, fmt.Errorf("证书格式错误")
	}
	cert, e := x509.ParseCertificate(block.Bytes)
	if e != nil {
		return nil, e
	}
	if cert.VerifyHostname(lan) != nil || time.Now().Before(cert.NotBefore) || time.Now().After(cert.NotAfter) {
		return nil, fmt.Errorf("已保存证书不适用于当前地址或已到期，请在 LuCI 重新生成证书")
	}
	return files, nil
}
func uciGet(option, fallback string) string {
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	b, e := exec.CommandContext(ctx, "uci", "-q", "get", "cudy_webfiles.main."+option).Output()
	if e != nil {
		return fallback
	}
	return string(bytes.TrimSpace(b))
}
func managedSettingsNow() managedSettings {
	p, _ := strconv.Atoi(uciGet("port", "8080"))
	return managedSettings{uciGet("volume", ""), p, uciGet("read_write", "0") == "1"}
}
func commitSettings(s managedSettings, enabled bool) error {
	if e := validateManagedSettings(s); e != nil {
		return e
	}
	text := fmt.Sprintf("set cudy_webfiles.main=webfiles\nset cudy_webfiles.main.volume='%s'\nset cudy_webfiles.main.port='%d'\nset cudy_webfiles.main.read_write='%d'\nset cudy_webfiles.main.enabled='%d'\ncommit cudy_webfiles\n", s.Volume, s.Port, map[bool]int{true: 1, false: 0}[s.ReadWrite], map[bool]int{true: 1, false: 0}[enabled])
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, "uci", "batch")
	cmd.Stdin = bytes.NewBufferString(text)
	if cmd.Run() != nil {
		return fmt.Errorf("保存网页服务设置失败")
	}
	return nil
}
func managedRunning() bool {
	b, e := os.ReadFile(runtimeDir + "/owner.json")
	if e != nil {
		return false
	}
	var o owner
	if json.Unmarshal(b, &o) != nil || o.Exe != selfExe() || o.PID <= 1 {
		return false
	}
	start, e := processStart(o.PID)
	if e != nil || start != o.Start {
		return false
	}
	exe, e := os.Readlink(fmt.Sprintf("/proc/%d/exe", o.PID))
	return e == nil && exe == o.Exe
}
func managedStatus() map[string]any {
	s := managedSettingsNow()
	running := managedRunning()
	r := map[string]any{"version": version, "display_name": "Cudy webpage", "running": running, "users": []map[string]any{}, "user_count": 0, "max_users": maxManagedUsers, "settings": s, "enabled": uciGet("enabled", "0") == "1", "account_set": false, "username": "admin", "access": "仅 LAN", "certificate_days": 30}
	registry, e := loadManagedRegistry()
	if e == nil {
		a := primaryAccount(registry)
		r["users"] = publicManagedUsers(registry)
		r["user_count"] = len(registry.Users)
		r["account_set"] = true
		r["username"] = a.Username
	} else if !errors.Is(e, os.ErrNotExist) {
		r["error"] = "无法读取已保存账号，请检查私有设置目录"
	}
	previous := map[string]any{}
	if b, e := os.ReadFile(runtimeDir + "/status.json"); e == nil {
		_ = json.Unmarshal(b, &previous)
	}
	available := int64(-1)
	if b, e := os.ReadFile("/proc/meminfo"); e == nil {
		if n, e := readMemAvailable(string(b)); e == nil {
			available = n
		}
	}
	mergeRuntimeStatus(r, previous, running, available, time.Now())
	if startup, ok := loadStartupRecord(); ok {
		r["startup"] = startup
		r["starting"] = !running && managedStarting()
	}
	if !running {
		if r["starting"] == true {
			r["stopReason"] = "正在等待 USB、局域网或可用内存就绪（最多 90 秒）"
		} else if stop, ok := publicStopRecord(previous); ok {
			r["lastStop"] = stop
			r["stopReason"] = stop.Reason
		} else if startup, ok := loadStartupRecord(); ok && startup.Stage == "failed" {
			r["stopReason"] = startup.Reason
		} else if r["enabled"] == true {
			r["stopReason"] = "进程已退出，未取得本次退出记录"
		}
	}
	if base, e := packageDir(); e == nil {
		if snap, e := getSnapshot(base); e == nil {
			r["volumes"] = snap.Volumes
			r["lan"] = snap.LAN
			r["url"] = fmt.Sprintf("https://%s:%d", snap.LAN, s.Port)
			addZeroTierStatus(r, snap.LAN, s.Port, running)
			addPublicStatus(r, running)
		}
	}
	return r
}
func initCommand(action string) error {
	ctx, cancel := context.WithTimeout(context.Background(), 12*time.Second)
	defer cancel()
	if exec.CommandContext(ctx, managedInit, action).Run() != nil {
		return fmt.Errorf("服务管理操作失败，请查看本服务诊断")
	}
	return nil
}
func managedReady() bool {
	if !managedRunning() {
		return false
	}
	b, e := os.ReadFile(runtimeDir + "/status.json")
	if e != nil {
		return false
	}
	var s struct {
		Version    string `json:"version"`
		URL        string `json:"url"`
		Warning    bool   `json:"resourceWarning"`
		UsersReady bool   `json:"usersReady"`
	}
	if json.Unmarshal(b, &s) != nil || s.Version != version || s.Warning || !s.UsersReady {
		return false
	}
	ca, e := os.ReadFile(runtimeDir + "/ca.crt")
	if e != nil {
		return false
	}
	roots := x509.NewCertPool()
	if !roots.AppendCertsFromPEM(ca) {
		return false
	}
	transport := &http.Transport{TLSClientConfig: &tls.Config{RootCAs: roots, MinVersion: tls.VersionTLS12}}
	defer transport.CloseIdleConnections()
	client := &http.Client{Transport: transport, Timeout: time.Second, CheckRedirect: func(_ *http.Request, _ []*http.Request) error { return http.ErrUseLastResponse }}
	res, e := client.Get(s.URL + "/login")
	if e != nil {
		return false
	}
	defer res.Body.Close()
	return res.StatusCode == 200
}
func stopManagedService() error {
	if b, e := os.ReadFile(runtimeDir + "/owner.json"); e == nil {
		var o owner
		if json.Unmarshal(b, &o) != nil || o.Exe != selfExe() {
			return fmt.Errorf("运行目录存在其他程序身份，拒绝停止")
		}
	}
	if e := initCommand("stop"); e != nil {
		return e
	}
	// procd acknowledges deletion before its process has finished exiting.
	// Let that shutdown finish before attempting a second owner-checked signal.
	deadline := time.Now().Add(5 * time.Second)
	for managedRunning() && time.Now().Before(deadline) {
		time.Sleep(100 * time.Millisecond)
	}
	if managedRunning() {
		ctx, cancel := context.WithTimeout(context.Background(), 12*time.Second)
		defer cancel()
		if exec.CommandContext(ctx, selfExe(), "stop").Run() != nil && managedRunning() {
			return fmt.Errorf("网页服务停止失败，请保留设备连接并检查状态")
		}
	}
	return nil
}
func startManagedService() error {
	if managedRunning() {
		return nil
	}
	if managedStarting() {
		return fmt.Errorf("网页服务正在等待启动条件就绪，请稍候或先关闭服务")
	}
	if _, e := loadManagedAccount(); e != nil {
		return fmt.Errorf("请先保存有效的网页账号和密码")
	}
	s := managedSettingsNow()
	if e := validateManagedSettings(s); e != nil {
		return e
	}
	args := []string{"check", "--volume", s.Volume, "--port", strconv.Itoa(s.Port)}
	if s.ReadWrite {
		args = append(args, "--read-write")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if exec.CommandContext(ctx, selfExe(), args...).Run() != nil {
		return fmt.Errorf("启动检查未通过，请检查 USB 授权、可用内存及系统能力")
	}
	if e := reset(); e != nil {
		return e
	}
	if e := commitSettings(s, true); e != nil {
		return e
	}
	if e := initCommand("start"); e != nil {
		commitSettings(s, false)
		return e
	}
	deadline := time.Now().Add(20 * time.Second)
	for time.Now().Before(deadline) {
		if managedReady() {
			return nil
		}
		time.Sleep(200 * time.Millisecond)
	}
	if e := stopManagedService(); e != nil {
		return e
	}
	commitSettings(s, false)
	return fmt.Errorf("服务未能启动，请检查端口是否被占用，或在 LuCI 重新生成已到期的证书")
}
func withManagedLock(fn func() error) error {
	fd, e := syscall.Open("/var/lock/cudy-webfiles-ui.lock", syscall.O_CREAT|syscall.O_RDWR|syscall.O_NOFOLLOW|syscall.O_CLOEXEC, 0600)
	if e != nil {
		return e
	}
	f := os.NewFile(uintptr(fd), "cudy-webfiles-ui.lock")
	defer f.Close()
	st, e := f.Stat()
	if e != nil {
		return e
	}
	owner, ok := st.Sys().(*syscall.Stat_t)
	if !ok || owner.Uid != 0 || !st.Mode().IsRegular() || st.Mode().Perm() != 0600 {
		return fmt.Errorf("操作锁权限或身份不符")
	}
	if e = syscall.Flock(int(f.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); e != nil {
		return fmt.Errorf("已有操作正在执行，请稍候")
	}
	defer syscall.Flock(int(f.Fd()), syscall.LOCK_UN)
	return fn()
}
func managedRPC(args []string) error {
	if len(args) == 1 && args[0] == "list" {
		fmt.Println(`{"status":{},"start":{},"stop":{},"settings":{"volume":"","port":8443,"read_write":false},"account":{"username":"","password":""},"user_save":{"original_username":"","username":"","password":"","read_write":false},"user_delete":{"username":""},"certificate":{},"renew_certificate":{},"zerotier":{"enabled":false,"network":""},"public_access":{"enabled":false,"public_ip":"","listen_port":8080,"external_port":8080},"public_certificate":{}}`)
		return nil
	}
	if len(args) != 2 || args[0] != "call" {
		return fmt.Errorf("invalid RPC invocation")
	}
	if os.Geteuid() != 0 {
		return fmt.Errorf("RPC requires root")
	}
	output := func(ok bool, result any, message string) {
		v := map[string]any{"ok": ok}
		if ok {
			v["result"] = result
		} else {
			v["message"] = message
		}
		b, _ := json.Marshal(v)
		fmt.Println(string(b))
	}
	b, e := io.ReadAll(io.LimitReader(os.Stdin, 8193))
	if e != nil || len(b) > 8192 {
		output(false, nil, "请求过大或不可读取")
		return nil
	}
	var params map[string]json.RawMessage
	if json.Unmarshal(b, &params) != nil {
		output(false, nil, "请求格式错误")
		return nil
	}
	delete(params, "ubus_rpc_session")
	method := args[1]
	if method == "public_certificate" {
		files, e := managedPublicTLS(publicConfigNow().PublicIP, false)
		if e != nil {
			output(false, nil, "公网证书尚未生成或已失效")
			return nil
		}
		output(true, map[string]any{"certificate": string(files["ca.crt"])}, "")
		return nil
	}
	if method == "status" {
		output(true, managedStatus(), "")
		return nil
	}
	if method == "certificate" {
		key, e := managedKey(false)
		if e != nil {
			output(false, nil, "请先启动服务生成证书")
			return nil
		}
		enc, e := readPrivate("tls.enc", 32768)
		if e != nil {
			output(false, nil, "证书尚未生成")
			return nil
		}
		plain, e := openManaged(key, "tls", enc)
		if e != nil {
			output(false, nil, "证书校验失败")
			return nil
		}
		var files map[string][]byte
		if json.Unmarshal(plain, &files) != nil {
			output(false, nil, "证书格式错误")
			return nil
		}
		output(true, map[string]any{"certificate": string(files["ca.crt"])}, "")
		return nil
	}
	e = withManagedLock(func() error {
		switch method {
		case "start":
			return startManagedService()
		case "stop":
			if e := stopManagedService(); e != nil {
				return e
			}
			return commitSettings(managedSettingsNow(), false)
		case "zerotier":
			return setZeroTierAccess(params)
		case "public_access":
			return setPublicAccess(params)
		case "settings":
			var s managedSettings
			p, _ := json.Marshal(params)
			if json.Unmarshal(p, &s) != nil {
				return fmt.Errorf("设置格式错误")
			}
			if e := validateManagedSettings(s); e != nil {
				return e
			}
			was := managedRunning()
			if was {
				if e := stopManagedService(); e != nil {
					return e
				}
			}
			if e := commitSettings(s, false); e != nil {
				return e
			}
			if was {
				return startManagedService()
			}
			return nil
		case "user_save":
			var edit managedUserEdit
			p, _ := json.Marshal(params)
			if json.Unmarshal(p, &edit) != nil {
				return fmt.Errorf("用户设置格式错误")
			}
			return mutateRegistry(func(r managedRegistry) (managedRegistry, error) { return editManagedUser(r, edit) })
		case "user_delete":
			var name string
			if json.Unmarshal(params["username"], &name) != nil {
				return fmt.Errorf("用户名格式错误")
			}
			return mutateRegistry(func(r managedRegistry) (managedRegistry, error) { return deleteManagedUser(r, name) })
		case "account":
			var a managedAccount
			p, _ := json.Marshal(params)
			if json.Unmarshal(p, &a) != nil {
				return fmt.Errorf("账号格式错误")
			}
			if e := validateManagedAccount(a); e != nil {
				return e
			}
			was := managedRunning()
			if was {
				if e := stopManagedService(); e != nil {
					return e
				}
			}
			if e := saveManagedAccount(a); e != nil {
				return fmt.Errorf("保存账号失败；服务已停止，原账号文件未被覆盖")
			}
			if was {
				return startManagedService()
			}
			return nil
		case "renew_certificate":
			was := managedRunning()
			if was {
				if e := stopManagedService(); e != nil {
					return e
				}
			}
			if e := privateDir(false); e != nil {
				return e
			}
			if _, e := readPrivate("tls.enc", 32768); e != nil && !os.IsNotExist(e) {
				return e
			}
			if e := os.Remove(managedPrivate + "/tls.enc"); e != nil && !os.IsNotExist(e) {
				return e
			}
			if was {
				return startManagedService()
			}
			return nil
		default:
			return fmt.Errorf("未知操作")
		}
	})
	if e != nil {
		output(false, nil, e.Error())
		return nil
	}
	output(true, managedStatus(), "")
	return nil
}
