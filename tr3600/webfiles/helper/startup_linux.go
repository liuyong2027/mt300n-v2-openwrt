//go:build linux

package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"strings"
	"syscall"
	"time"
)

const startupStatePath = "/tmp/cudy-webfiles-startup.json"
const startupWaitLimit = 90 * time.Second

type startupRecord struct {
	Version     string `json:"version"`
	BootID      string `json:"bootID"`
	PID         int    `json:"pid"`
	Start       string `json:"processStart"`
	Stage       string `json:"stage"`
	Code        string `json:"code"`
	Reason      string `json:"reason"`
	Attempts    int    `json:"attempts"`
	StartedAt   string `json:"startedAt"`
	UpdatedAt   string `json:"updatedAt"`
	WaitSeconds int    `json:"waitSeconds"`
}

func writeStartupRecord(path string, r startupRecord) error {
	if st, e := os.Lstat(path); e == nil {
		u, ok := st.Sys().(*syscall.Stat_t)
		if !ok || u.Uid != 0 || u.Nlink != 1 || !st.Mode().IsRegular() || st.Mode().Perm() != 0600 {
			return fmt.Errorf("启动状态文件身份或权限不符")
		}
	} else if !os.IsNotExist(e) {
		return e
	}
	f, e := os.CreateTemp(filepath.Dir(path), ".cudy-webfiles-startup-*")
	if e != nil {
		return e
	}
	defer os.Remove(f.Name())
	data, _ := json.Marshal(r)
	_, e = f.Write(append(data, '\n'))
	closeErr := f.Close()
	if e != nil {
		return e
	}
	if closeErr != nil {
		return closeErr
	}
	return os.Rename(f.Name(), path)
}

func loadStartupRecord() (startupRecord, bool) {
	return readStartupRecord(startupStatePath, version, bootID())
}

func readStartupRecord(path, expectedVersion, expectedBoot string) (startupRecord, bool) {
	var r startupRecord
	fd, e := syscall.Open(path, syscall.O_RDONLY|syscall.O_NOFOLLOW|syscall.O_CLOEXEC, 0)
	if e != nil {
		return r, false
	}
	f := os.NewFile(uintptr(fd), "startup-state")
	defer f.Close()
	st, e := f.Stat()
	if e != nil {
		return r, false
	}
	u, ok := st.Sys().(*syscall.Stat_t)
	if !ok || u.Uid != 0 || u.Nlink != 1 || !st.Mode().IsRegular() || st.Mode().Perm() != 0600 || st.Size() > 4096 {
		return r, false
	}
	b, e := io.ReadAll(io.LimitReader(f, 4097))
	if e != nil || json.Unmarshal(b, &r) != nil || r.Version != expectedVersion || r.BootID != expectedBoot || r.PID <= 1 {
		return r, false
	}
	return r, true
}

func managedStarting() bool {
	r, ok := loadStartupRecord()
	if !ok || (r.Stage != "verifying" && r.Stage != "waiting" && r.Stage != "launching") {
		return false
	}
	s, e := processStart(r.PID)
	x, xe := os.Readlink(fmt.Sprintf("/proc/%d/exe", r.PID))
	return e == nil && xe == nil && s == r.Start && x == selfExe()
}

func runAtBoot(base, id string, port int, rw bool) (err error) {
	start, e := processStart(os.Getpid())
	if e != nil {
		return e
	}
	r := startupRecord{Version: version, BootID: bootID(), PID: os.Getpid(), Start: start, Stage: "verifying", Code: "startup_verifying", Reason: "正在检查启动条件", StartedAt: time.Now().UTC().Format(time.RFC3339Nano), WaitSeconds: int(startupWaitLimit / time.Second)}
	update := func() error {
		r.UpdatedAt = time.Now().UTC().Format(time.RFC3339Nano)
		return writeStartupRecord(startupStatePath, r)
	}
	if e = update(); e != nil {
		return e
	}
	defer func() {
		if err != nil {
			r.Stage = "failed"
			r.Code, r.Reason, _ = startupSummary(err)
			var stop *serviceStopError
			if errors.As(err, &stop) {
				r.Code, r.Reason = stopSummary(err)
			}
		} else {
			r.Stage, r.Code, r.Reason = "stopped", "requested", "收到关闭或终止信号，服务已停止"
		}
		_ = update()
	}()
	signalCtx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM, syscall.SIGHUP)
	defer stop()
	ctx, cancel := context.WithTimeout(signalCtx, startupWaitLimit)
	defer cancel()
	if !volumeID.MatchString(id) || port < 1024 || port > 65535 {
		return &startupError{"startup_invalid_settings", "网页服务启动设置无效", false, nil}
	}
	// Immutable and system-capability guards fail immediately, with no respawn.
	if e = verifyBinary(base + "/bin/filebrowser"); e != nil {
		return &startupError{"startup_binary_invalid", "文件服务程序校验失败，拒绝启动", false, e}
	}
	if e = probeNamespaces(); e != nil {
		return &startupError{"startup_isolation_unavailable", "进程隔离不可用，拒绝启动", false, e}
	}
	if e = exec.Command("nft", "--version").Run(); e != nil {
		return &startupError{"startup_firewall_unavailable", "防火墙工具不可用，拒绝启动", false, e}
	}
	var vol Volume
	var mount MountInfo
	r.Stage = "waiting"
	probe := func(ctx context.Context) error {
		for option, expected := range map[string]string{"enabled": "1", "volume": id, "port": fmt.Sprint(port), "read_write": map[bool]string{true: "1", false: "0"}[rw]} {
			optionCtx, end := context.WithTimeout(ctx, 2*time.Second)
			b, e := exec.CommandContext(optionCtx, "uci", "-q", "get", "cudy_webfiles.main."+option).Output()
			end()
			if e != nil {
				return &startupError{"startup_settings_unavailable", "暂时无法读取网页启动设置，等待重试", true, e}
			}
			if strings.TrimSpace(string(b)) != expected {
				return &startupError{"startup_settings_changed", "启动设置已关闭或改变，已取消本次启动", false, nil}
			}
		}
		s, e := getSnapshotContext(ctx, base, 5*time.Second)
		if e != nil {
			return e
		}
		found := false
		for _, v := range s.Volumes {
			if v.ID == id {
				found = true
				break
			}
		}
		if !found {
			return &startupError{"startup_usb_wait", "等待已授权 USB 分区挂载就绪", true, nil}
		}
		vol, mount, e = guardVolume(s, id)
		if e != nil {
			return &startupError{"startup_mount_invalid", "USB 挂载身份或权限不符，拒绝启动", false, e}
		}
		if rw && vol.ReadOnly {
			return &startupError{"startup_write_not_authorized", "USB 授权为只读，不能启用写入", false, nil}
		}
		b, e := os.ReadFile("/proc/meminfo")
		if e != nil {
			return &startupError{"startup_memory_unavailable", "无法检查可用内存，拒绝启动", false, e}
		}
		mem, e := readMemAvailable(string(b))
		if e != nil {
			return &startupError{"startup_memory_unavailable", "无法检查可用内存，拒绝启动", false, e}
		}
		if mem < 128*1024 {
			return &startupError{"startup_memory_wait", "等待可用内存达到启动要求", true, nil}
		}
		return nil
	}
	err = waitForStartup(ctx, 2*time.Second, probe, func(attempt int, code, reason string) {
		r.Attempts, r.Code, r.Reason = attempt, code, reason
		if e := update(); e != nil {
			cancel()
		}
	})
	if err != nil {
		return err
	}
	if ctx.Err() != nil {
		return &startupError{"startup_cancelled", "启动等待已取消", false, ctx.Err()}
	}
	r.Stage, r.Code, r.Reason = "launching", "startup_ready", "启动条件已就绪，正在初始化用户"
	if e = update(); e != nil {
		return e
	}
	// Only this initial launch may wait. Runtime guard failures still stop once.
	return runServiceContext(signalCtx, base, vol, mount, port, rw)
}
