package main

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"
)

func TestStartupWaitsForTransientReadinessThenLaunchesOnce(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	attempts := 0
	var codes []string
	err := waitForStartup(ctx, time.Millisecond, func(context.Context) error {
		attempts++
		if attempts == 1 {
			return &startupError{"startup_lan_wait", "等待局域网", true, nil}
		}
		if attempts == 2 {
			return &startupError{"startup_usb_wait", "等待已授权分区", true, nil}
		}
		if attempts == 3 {
			return &startupError{"startup_memory_wait", "等待可用内存", true, nil}
		}
		return nil
	}, func(_ int, code, _ string) { codes = append(codes, code) })
	if err != nil || attempts != 4 || strings.Join(codes, ",") != "startup_lan_wait,startup_usb_wait,startup_memory_wait,startup_ready" {
		t.Fatalf("readiness transition: %v %d %v", err, attempts, codes)
	}
}

func TestStartupPermanentGuardFailureNeverRetries(t *testing.T) {
	for _, code := range []string{"startup_binary_invalid", "startup_mount_invalid", "startup_write_not_authorized", "startup_snapshot_invalid", "startup_settings_changed"} {
		t.Run(code, func(t *testing.T) {
			calls := 0
			err := waitForStartup(context.Background(), time.Millisecond, func(context.Context) error { calls++; return &startupError{code, "拒绝启动", false, nil} }, func(int, string, string) {})
			got, _, _ := startupSummary(err)
			if calls != 1 || got != code {
				t.Fatalf("permanent failure retried: %d %s", calls, got)
			}
		})
	}
}

func TestStartupDeadlineLeavesServiceStopped(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 8*time.Millisecond)
	defer cancel()
	calls := 0
	err := waitForStartup(ctx, 2*time.Millisecond, func(context.Context) error {
		calls++
		return &startupError{"startup_usb_wait", "等待分区", true, nil}
	}, func(int, string, string) {})
	code, _, _ := startupSummary(err)
	if code != "startup_timeout" || calls < 1 || calls > 8 {
		t.Fatalf("unbounded or wrong timeout: %s %d", code, calls)
	}
}

func TestStartupCancellationPreventsLaunch(t *testing.T) {
	for _, duringProbe := range []bool{false, true} {
		ctx, cancel := context.WithCancel(context.Background())
		calls := 0
		if !duringProbe {
			cancel()
		}
		err := waitForStartup(ctx, time.Millisecond, func(context.Context) error { calls++; cancel(); return nil }, func(int, string, string) { t.Error("cancelled probe reported ready") })
		code, _, _ := startupSummary(err)
		if code != "startup_cancelled" || (!duringProbe && calls != 0) || (duringProbe && calls != 1) {
			t.Fatalf("cancel raced launch: %s %d", code, calls)
		}
	}
}

func TestStartupCancellationInterruptsLongWait(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	start := time.Now()
	err := waitForStartup(ctx, time.Hour, func(context.Context) error {
		cancel()
		return &startupError{"startup_usb_wait", "等待分区", true, nil}
	}, func(int, string, string) {})
	code, _, _ := startupSummary(err)
	if code != "startup_cancelled" || time.Since(start) > time.Second {
		t.Fatalf("stop did not cancel wait: %s", code)
	}
}

func TestStartupDiagnosticNeverCopiesUnknownErrorInput(t *testing.T) {
	for _, err := range []error{errors.New("password=synthetic-secret"), &startupError{"startup_snapshot_invalid", "状态身份无效", false, errors.New("token=synthetic-secret")}} {
		code, reason, retry := startupSummary(err)
		if strings.Contains(code+reason, "synthetic-secret") || retry {
			t.Fatal("raw error input exposed or retried")
		}
	}
}
