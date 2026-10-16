//go:build !linux

package main

import (
	"crypto/rand"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strconv"
)

func multiFixture() error {
	if len(os.Args) != 7 {
		return fmt.Errorf("invalid fixture arguments")
	}
	state := os.Args[3]
	os.MkdirAll(state, 0700)
	keyPath := filepath.Join(state, "test-users.key")
	key, e := os.ReadFile(keyPath)
	if os.IsNotExist(e) {
		key = make([]byte, 32)
		rand.Read(key)
		e = os.WriteFile(keyPath, key, 0600)
	}
	if e != nil {
		return e
	}
	var registry managedRegistry
	input, e := io.ReadAll(io.LimitReader(os.Stdin, 65537))
	if e != nil || len(input) > 65536 {
		return fmt.Errorf("invalid fixture input")
	}
	storePath := filepath.Join(state, "test-users.enc")
	if len(input) > 0 {
		if e = json.Unmarshal(input, &registry); e != nil {
			return e
		}
		if e = validateRegistry(registry); e != nil {
			return e
		}
		b, _ := json.Marshal(registry)
		b, e = sealManaged(key, "accounts", b)
		if e != nil {
			return e
		}
		if e = os.WriteFile(storePath, b, 0600); e != nil {
			return e
		}
	} else {
		b, e := os.ReadFile(storePath)
		if e != nil {
			return e
		}
		b, e = openManaged(key, "accounts", b)
		if e != nil {
			return e
		}
		if e = json.Unmarshal(b, &registry); e != nil {
			return e
		}
		if e = validateRegistry(registry); e != nil {
			return e
		}
	}
	port, _ := strconv.Atoi(os.Args[5])
	rw := os.Args[6] == "rw"
	a := primaryAccount(registry)
	config, e := makeConfig(Volume{}, "127.0.0.1", port, rw, os.Args[2], state, os.Args[4], a.Password)
	if e != nil {
		return e
	}
	config, e = managedQuantumConfig(config, a)
	if e != nil {
		return e
	}
	caPath := filepath.Join(state, "ca.crt")
	if _, e = os.Stat(caPath); os.IsNotExist(e) {
		files, e := makeTLS("127.0.0.1")
		if e != nil {
			return e
		}
		for n, b := range files {
			if e = os.WriteFile(filepath.Join(state, n), b, 0600); e != nil {
				return e
			}
		}
	}
	payloads := []json.RawMessage{}
	for _, u := range registry.Users {
		if !u.Admin {
			payloads = append(payloads, quantumUserPayload(u, !rw))
		}
	}
	return json.NewEncoder(os.Stdout).Encode(map[string]any{"config": json.RawMessage(config), "primary": a, "user_payloads": payloads, "public_users": publicManagedUsers(registry)})
}
