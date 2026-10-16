package main

import (
	"errors"
	"time"
)

type serviceStopError struct {
	Code, Reason string
	Cause        error
}

func (e *serviceStopError) Error() string { return e.Reason }
func (e *serviceStopError) Unwrap() error { return e.Cause }

type serviceStopRecord struct {
	Version              string `json:"version"`
	StoppedAt            string `json:"stoppedAt"`
	BootID               string `json:"bootID"`
	PID                  int    `json:"pid"`
	ProcessStart         string `json:"processStart"`
	Code                 string `json:"code"`
	Reason               string `json:"reason"`
	LastMemAvailableKiB  any    `json:"lastMemAvailableKiB,omitempty"`
	MinMemAvailableKiB   any    `json:"minMemAvailableKiB,omitempty"`
	LastWorkerTreeRssKiB any    `json:"lastWorkerTreeRssKiB,omitempty"`
}

func stopSummary(err error) (string, string) {
	if err == nil {
		return "requested", "收到关闭或终止信号，服务已停止"
	}
	var stop *serviceStopError
	if errors.As(err, &stop) {
		return stop.Code, stop.Reason
	}
	// Unknown error text can include paths or upstream input; never publish it.
	return "service_error", "服务启动或运行失败，具体原因未分类"
}

func mergeRuntimeStatus(result, previous map[string]any, running bool, availableKiB int64, sampledAt time.Time) {
	for _, k := range []string{"url", "memAvailableKiB", "minMemAvailableKiB", "workerTreeRssKiB", "resourceWarning", "readOnly", "volume", "usersReady"} {
		if x, ok := previous[k]; ok {
			result[k] = x
		}
	}
	result["memorySampleIsLive"] = availableKiB >= 0
	if availableKiB >= 0 {
		result["memAvailableKiB"] = availableKiB
		result["resourceWarning"] = availableKiB < 96*1024
		result["memorySampledAt"] = sampledAt.UTC().Format(time.RFC3339Nano)
	}
	if !running {
		result["lastRunMemAvailableKiB"] = previous["memAvailableKiB"]
		result["lastWorkerTreeRssKiB"] = previous["workerTreeRssKiB"]
		result["workerTreeRssKiB"] = int64(0)
		result["usersReady"] = false
	}
}
