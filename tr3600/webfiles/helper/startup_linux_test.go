//go:build linux

package main

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestStartupCancelledHandoffNeverCreatesRuntime(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	err := runServiceContext(ctx, "unused", Volume{}, MountInfo{}, 8080, false)
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("cancelled startup handoff proceeded: %v", err)
	}
}

func TestStartupAdapterSeparatesTransientLANFromPermanentFailures(t *testing.T) {
	if _, err := os.Stat("/usr/bin/lua"); err != nil {
		t.Skip("native OpenWrt Lua test")
	}
	for _, fixture := range []struct {
		name, body, code string
		retry            bool
	}{
		{"LAN delayed", `io.stderr:write('LAN is not ready\n');os.exit(1)`, "startup_lan_wait", true},
		{"wrong board", `io.stderr:write('Only Cudy TR3600 v1 is supported\n');os.exit(1)`, "startup_adapter_failed", false},
		{"invalid JSON", `print('invalid')`, "startup_snapshot_invalid", false},
		{"invalid identity", `print('{"board":"other","lan":"192.168.9.1","iface":"br-lan","volumes":[]}')`, "startup_snapshot_invalid", false},
	} {
		t.Run(fixture.name, func(t *testing.T) {
			dir := t.TempDir()
			if err := os.WriteFile(filepath.Join(dir, "adapter.lua"), []byte(fixture.body), 0600); err != nil {
				t.Fatal(err)
			}
			_, err := getSnapshotContext(context.Background(), dir, time.Second)
			code, _, retry := startupSummary(err)
			if code != fixture.code || retry != fixture.retry {
				t.Fatalf("unexpected adapter result: %s %t %v", code, retry, err)
			}
		})
	}
}

func TestStartupAdapterTimeoutIsBoundedAndRetryable(t *testing.T) {
	if _, err := os.Stat("/usr/bin/lua"); err != nil {
		t.Skip("native OpenWrt Lua test")
	}
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "adapter.lua"), []byte(`while true do end`), 0600); err != nil {
		t.Fatal(err)
	}
	start := time.Now()
	_, err := getSnapshotContext(context.Background(), dir, 20*time.Millisecond)
	code, _, retry := startupSummary(err)
	if code != "startup_adapter_timeout" || !retry || time.Since(start) > time.Second {
		t.Fatalf("unbounded adapter: %s %t", code, retry)
	}
}

func TestStartupRecordAtomicPrivateAndBootScoped(t *testing.T) {
	if os.Geteuid() != 0 {
		t.Skip("root metadata test")
	}
	path := filepath.Join(t.TempDir(), "startup.json")
	r := startupRecord{Version: version, BootID: "fixture-boot", PID: 99, Stage: "waiting", Code: "startup_usb_wait", Reason: "等待已授权分区"}
	if err := writeStartupRecord(path, r); err != nil {
		t.Fatal(err)
	}
	if st, err := os.Stat(path); err != nil || st.Mode().Perm() != 0600 {
		t.Fatal("state not private")
	}
	if got, ok := readStartupRecord(path, version, "fixture-boot"); !ok || got.Code != r.Code {
		t.Fatal("state unavailable")
	}
	if _, ok := readStartupRecord(path, version, "other-boot"); ok {
		t.Fatal("stale boot accepted")
	}
	if err := os.Chmod(path, 0644); err != nil {
		t.Fatal(err)
	}
	if _, ok := readStartupRecord(path, version, "fixture-boot"); ok {
		t.Fatal("publicly writable/visible state accepted")
	}
	if err := writeStartupRecord(path, r); err == nil {
		t.Fatal("foreign mode overwritten")
	}
}

func TestStartupRecordRejectsSymlinkAndHardlink(t *testing.T) {
	if os.Geteuid() != 0 {
		t.Skip("root metadata test")
	}
	dir := t.TempDir()
	target := filepath.Join(dir, "target")
	const contents = "synthetic-private-marker"
	if err := os.WriteFile(target, []byte(contents), 0600); err != nil {
		t.Fatal(err)
	}
	for _, link := range []string{"symbolic", "hard"} {
		path := filepath.Join(dir, link)
		var err error
		if link == "symbolic" {
			err = os.Symlink(target, path)
		} else {
			err = os.Link(target, path)
		}
		if err != nil {
			t.Fatal(err)
		}
		if err = writeStartupRecord(path, startupRecord{}); err == nil {
			t.Fatal("linked state overwritten")
		}
		if b, _ := os.ReadFile(target); string(b) != contents {
			t.Fatal("link target changed")
		}
		if _, ok := readStartupRecord(path, version, "fixture-boot"); ok {
			t.Fatal("linked state accepted")
		}
		if err = os.Remove(path); err != nil {
			t.Fatal(err)
		}
	}
}

func TestStartupRecordContainsNoRawFailureCause(t *testing.T) {
	code, reason, _ := startupSummary(&startupError{"startup_binary_invalid", "程序校验失败", false, os.ErrPermission})
	b, err := json.Marshal(startupRecord{Code: code, Reason: reason})
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(b), "permission denied") {
		t.Fatal("raw cause serialized")
	}
}
