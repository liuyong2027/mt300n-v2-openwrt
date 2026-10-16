package main

import (
	"errors"
	"fmt"
	"strings"
	"testing"
	"time"
)

func TestStopReasonDoesNotPublishErrorInput(t *testing.T) {
	cause := errors.New("sensitive-test-value")
	for _, err := range []error{cause, fmt.Errorf("wrapped: %w", &serviceStopError{"memory_low", "可用内存低于 64 MiB，已停止保护路由器", cause})} {
		_, reason := stopSummary(err)
		if strings.Contains(reason, cause.Error()) {
			t.Fatal("upstream error leaked into public stop reason")
		}
	}
	code, _ := stopSummary(nil)
	if code != "requested" {
		t.Fatal("normal stop was reported as a failure")
	}
	code, _ = stopSummary(&serviceStopError{"status_check_timeout", "USB/LAN 状态检查超过 2 秒，已保护性停止", cause})
	if code != "status_check_timeout" {
		t.Fatal("timeout cause lost")
	}
}

func TestStoppedMemoryUsesLiveReading(t *testing.T) {
	previous := map[string]any{"memAvailableKiB": int64(90000), "workerTreeRssKiB": int64(60000), "usersReady": true, "minMemAvailableKiB": int64(80000), "password": "sensitive-test-value"}
	r := map[string]any{}
	mergeRuntimeStatus(r, previous, false, 280000, time.Unix(1, 0))
	if r["memAvailableKiB"] != int64(280000) || r["lastRunMemAvailableKiB"] != int64(90000) || r["workerTreeRssKiB"] != int64(0) || r["usersReady"] != false || r["memorySampleIsLive"] != true || r["password"] != nil {
		t.Fatal("stopped status shows stale memory or private state")
	}
	r = map[string]any{}
	mergeRuntimeStatus(r, previous, true, 90000, time.Unix(2, 0))
	if r["resourceWarning"] != true || r["workerTreeRssKiB"] != int64(60000) || r["usersReady"] != true {
		t.Fatal("running metrics or warning lost")
	}
}

func TestUnavailableMemoryIsMarkedHistorical(t *testing.T) {
	r := map[string]any{}
	mergeRuntimeStatus(r, map[string]any{"memAvailableKiB": int64(90000)}, false, -1, time.Unix(1, 0))
	if r["memorySampleIsLive"] != false || r["memAvailableKiB"] != int64(90000) {
		t.Fatal("unverified reading shown as live")
	}
}
