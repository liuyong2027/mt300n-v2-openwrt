//go:build linux

package main

import (
	"encoding/json"
	"os"
	"strings"
	"time"
)

func bootID() string {
	b, _ := os.ReadFile("/proc/sys/kernel/random/boot_id")
	return strings.TrimSpace(string(b))
}

func recordManagedStop(err error, o owner) {
	previous := map[string]any{}
	if b, e := os.ReadFile(runtimeDir + "/status.json"); e == nil {
		_ = json.Unmarshal(b, &previous)
	}
	code, reason := stopSummary(err)
	r := serviceStopRecord{Version: version, StoppedAt: time.Now().UTC().Format(time.RFC3339Nano), BootID: bootID(), PID: o.PID, ProcessStart: o.Start, Code: code, Reason: reason, LastMemAvailableKiB: previous["memAvailableKiB"], MinMemAvailableKiB: previous["minMemAvailableKiB"], LastWorkerTreeRssKiB: previous["workerTreeRssKiB"]}
	b, _ := json.MarshalIndent(r, "", "  ")
	// Write once per exit, never on every sampling tick. This contains no account or TLS data.
	_ = writePrivate("last-stop.json", append(b, '\n'))
	previous["version"], previous["running"], previous["usersReady"] = version, false, false
	previous["stopCode"], previous["stopReason"], previous["stoppedAt"] = code, reason, r.StoppedAt
	previous["runPID"], previous["runStart"] = o.PID, o.Start
	b, _ = json.MarshalIndent(previous, "", "  ")
	if os.WriteFile(runtimeDir+"/status.json.tmp", append(b, '\n'), 0600) == nil {
		_ = os.Rename(runtimeDir+"/status.json.tmp", runtimeDir+"/status.json")
	}
}

func publicStopRecord(previous map[string]any) (serviceStopRecord, bool) {
	var r serviceStopRecord
	if privateDir(false) != nil {
		return r, false
	}
	b, e := readPrivate("last-stop.json", 16384)
	if e != nil || json.Unmarshal(b, &r) != nil || r.BootID != bootID() {
		return r, false
	}
	pid, ok := previous["runPID"].(float64)
	start, _ := previous["runStart"].(string)
	return r, ok && int(pid) == r.PID && start == r.ProcessStart
}
