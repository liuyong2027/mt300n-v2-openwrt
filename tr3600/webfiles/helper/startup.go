package main

import (
	"context"
	"errors"
	"time"
)

// Retry only conditions that can settle during this one startup attempt.
// A launched worker is never restarted by this mechanism.
type startupError struct {
	Code, Reason string
	Retryable    bool
	Cause        error
}

func (e *startupError) Error() string { return e.Reason }
func (e *startupError) Unwrap() error { return e.Cause }

func startupSummary(err error) (string, string, bool) {
	var e *startupError
	if errors.As(err, &e) {
		return e.Code, e.Reason, e.Retryable
	}
	return "startup_check_failed", "启动检查失败，服务保持停止", false
}

func waitForStartup(ctx context.Context, interval time.Duration, probe func(context.Context) error, report func(int, string, string)) error {
	var last error
	for attempt := 1; ; attempt++ {
		if err := ctx.Err(); err != nil {
			if errors.Is(err, context.Canceled) {
				return &startupError{"startup_cancelled", "启动等待已取消", false, err}
			}
			return &startupError{"startup_timeout", "启动等待超时；请检查 USB、局域网和可用内存", false, last}
		}
		err := probe(ctx)
		if ctx.Err() != nil {
			continue
		}
		if err == nil {
			// A stop or deadline racing the final probe must not launch a worker.
			if ctx.Err() != nil {
				continue
			}
			report(attempt, "startup_ready", "启动条件已就绪")
			return nil
		}
		code, reason, retry := startupSummary(err)
		report(attempt, code, reason)
		if !retry {
			return err
		}
		last = err
		timer := time.NewTimer(interval)
		select {
		case <-ctx.Done():
			if !timer.Stop() {
				<-timer.C
			}
		case <-timer.C:
		}
	}
}
