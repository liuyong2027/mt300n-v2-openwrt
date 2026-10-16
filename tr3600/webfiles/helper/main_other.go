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

// The non-Linux build exists only for local configuration verification.
func main() {
	if len(os.Args) > 1 && os.Args[1] == "multi-fixture" {
		if e := multiFixture(); e != nil {
			panic(e)
		}
		return
	}
	if len(os.Args) == 7 && (os.Args[1] == "fixture" || os.Args[1] == "managed-fixture") {
		port, _ := strconv.Atoi(os.Args[5])
		v := Volume{ReadOnly: os.Args[6] == "ro"}
		p, e := makeConfig(v, "127.0.0.1", port, true, os.Args[2], os.Args[3], os.Args[4], "Test-only-password-7359")
		if e != nil {
			panic(e)
		}
		files, e := makeTLS("127.0.0.1")
		if e != nil {
			panic(e)
		}
		os.MkdirAll(os.Args[3], 0700)
		if os.Args[1] == "managed-fixture" {
			state := os.Args[3]
			keyPath := filepath.Join(state, "test-account.key")
			accountPath := filepath.Join(state, "test-account.enc")
			key, e := os.ReadFile(keyPath)
			if os.IsNotExist(e) {
				key = make([]byte, 32)
				if _, e = rand.Read(key); e != nil {
					panic(e)
				}
				if e = os.WriteFile(keyPath, key, 0600); e != nil {
					panic(e)
				}
			} else if e != nil {
				panic(e)
			}
			var account managedAccount
			input, e := io.ReadAll(io.LimitReader(os.Stdin, 8193))
			if e != nil || len(input) > 8192 {
				panic("invalid fixture input")
			}
			if len(input) > 0 {
				if e = json.Unmarshal(input, &account); e != nil {
					panic(e)
				}
				if e = validateManagedAccount(account); e != nil {
					panic(e)
				}
				plain, _ := json.Marshal(account)
				sealed, e := sealManaged(key, "account", plain)
				if e != nil {
					panic(e)
				}
				if e = os.WriteFile(accountPath, sealed, 0600); e != nil {
					panic(e)
				}
			} else {
				sealed, e := os.ReadFile(accountPath)
				if e != nil {
					panic(e)
				}
				plain, e := openManaged(key, "account", sealed)
				if e != nil {
					panic(e)
				}
				if e = json.Unmarshal(plain, &account); e != nil {
					panic(e)
				}
			}
			p, e = managedQuantumConfig(p, account)
			if e != nil {
				panic(e)
			}
			if ca, e := os.ReadFile(filepath.Join(state, "ca.crt")); e == nil {
				crt, e := os.ReadFile(filepath.Join(state, "tls.crt"))
				if e != nil {
					panic(e)
				}
				key, e := os.ReadFile(filepath.Join(state, "tls.key"))
				if e != nil {
					panic(e)
				}
				files = map[string][]byte{"ca.crt": ca, "tls.crt": crt, "tls.key": key}
			}
		}
		for n, b := range files {
			if e := os.WriteFile(filepath.Join(os.Args[3], n), b, 0600); e != nil {
				panic(e)
			}
		}
		os.Stdout.Write(p)
		return
	}
	fmt.Fprintln(os.Stderr, "This application requires Linux/OpenWrt ARM64.")
	os.Exit(1)
}
