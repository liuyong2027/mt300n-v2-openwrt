//go:build linux

package main

import (
	"bytes"
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"strings"
	"time"
)

func loadManagedRegistry() (managedRegistry, error) {
	var r managedRegistry
	key, e := managedKey(false)
	if e != nil {
		return r, e
	}
	b, e := readPrivate("accounts.enc", 65536)
	if errors.Is(e, os.ErrNotExist) {
		a, e := loadLegacyManagedAccount()
		if e != nil {
			return r, e
		}
		r = registryFromLegacy(a)
		return r, validateRegistry(r)
	}
	if e != nil {
		return r, e
	}
	b, e = openManaged(key, "accounts", b)
	if e != nil {
		return r, fmt.Errorf("多用户设置校验失败")
	}
	if json.Unmarshal(b, &r) != nil {
		return r, fmt.Errorf("多用户设置格式错误")
	}
	return r, validateRegistry(r)
}
func saveManagedRegistry(r managedRegistry) error {
	if e := validateRegistry(r); e != nil {
		return e
	}
	key, e := managedKey(true)
	if e != nil {
		return e
	}
	b, _ := json.Marshal(r)
	b, e = sealManaged(key, "accounts", b)
	if e != nil {
		return e
	}
	return writePrivate("accounts.enc", b)
}
func ensureManagedRegistry() (managedRegistry, error) {
	r, e := loadManagedRegistry()
	if e != nil {
		return r, e
	}
	if _, e = readPrivate("accounts.enc", 65536); errors.Is(e, os.ErrNotExist) {
		e = saveManagedRegistry(r)
	}
	return r, e
}
func loadManagedAccount() (managedAccount, error) {
	r, e := loadManagedRegistry()
	return primaryAccount(r), e
}
func saveManagedAccount(a managedAccount) error {
	r, e := loadManagedRegistry()
	if errors.Is(e, os.ErrNotExist) {
		return saveManagedRegistry(registryFromLegacy(a))
	}
	if e != nil {
		return e
	}
	r, e = editManagedUser(r, managedUserEdit{r.Primary, a.Username, a.Password, true})
	if e != nil {
		return e
	}
	return saveManagedRegistry(r)
}
func mutateRegistry(fn func(managedRegistry) (managedRegistry, error)) error {
	r, e := loadManagedRegistry()
	if errors.Is(e, os.ErrNotExist) {
		r = managedRegistry{Schema: 1}
	} else if e != nil {
		return e
	}
	next, e := fn(r)
	if e != nil {
		return e
	}
	was := managedRunning()
	if was {
		if e = stopManagedService(); e != nil {
			return e
		}
	}
	if e = saveManagedRegistry(next); e != nil {
		return fmt.Errorf("用户保存失败，服务已停止，请保留诊断")
	}
	if was {
		return startManagedService()
	}
	return nil
}
func initializeManagedUsers(ctx context.Context, endpoint string, ca []byte, r managedRegistry, sourceRO bool) error {
	roots := x509.NewCertPool()
	if !roots.AppendCertsFromPEM(ca) {
		return fmt.Errorf("多用户初始化 CA 无效")
	}
	transport := &http.Transport{TLSClientConfig: &tls.Config{RootCAs: roots, MinVersion: tls.VersionTLS12}}
	defer transport.CloseIdleConnections()
	client := &http.Client{Transport: transport, Timeout: 2 * time.Second, CheckRedirect: func(_ *http.Request, _ []*http.Request) error { return http.ErrUseLastResponse }}
	primary := primaryAccount(r)
	token := ""
	for token == "" {
		if ctx.Err() != nil {
			return fmt.Errorf("多用户初始化等待超时")
		}
		req, _ := http.NewRequestWithContext(ctx, "POST", endpoint+"/api/auth/login?username="+url.QueryEscape(primary.Username), nil)
		req.Header.Set("X-Password", url.QueryEscape(primary.Password))
		res, e := client.Do(req)
		if e == nil {
			b, _ := io.ReadAll(io.LimitReader(res.Body, 8192))
			res.Body.Close()
			if res.StatusCode == 200 && len(strings.Split(string(b), ".")) == 3 {
				token = string(b)
			}
		}
		if token == "" {
			select {
			case <-ctx.Done():
				return fmt.Errorf("多用户初始化等待超时")
			case <-time.After(200 * time.Millisecond):
			}
		}
	}
	for _, u := range r.Users {
		if u.Admin {
			continue
		}
		req, _ := http.NewRequestWithContext(ctx, "POST", endpoint+"/api/users", bytes.NewReader(quantumUserPayload(u, sourceRO)))
		req.Header.Set("Authorization", "Bearer "+token)
		req.Header.Set("X-Password", url.QueryEscape(primary.Password))
		req.Header.Set("Content-Type", "application/json")
		res, e := client.Do(req)
		if e != nil {
			return fmt.Errorf("多用户初始化请求失败")
		}
		io.Copy(io.Discard, io.LimitReader(res.Body, 8192))
		res.Body.Close()
		if res.StatusCode != http.StatusCreated {
			return fmt.Errorf("多用户初始化被拒绝：HTTP %d", res.StatusCode)
		}
		// Quantum's create defaults can override explicit scopes. Users are
		// initially created with read-only source defaults, then granted their
		// chosen permissions through PATCH before readiness is announced.
		var create map[string]json.RawMessage
		json.Unmarshal(quantumUserPayload(u, sourceRO), &create)
		var data map[string]json.RawMessage
		json.Unmarshal(create["data"], &data)
		patch, _ := json.Marshal(map[string]any{"which": []string{"scopes"}, "data": map[string]json.RawMessage{"scopes": data["scopes"]}})
		req, _ = http.NewRequestWithContext(ctx, "PATCH", endpoint+"/api/users?username="+url.QueryEscape(u.Username), bytes.NewReader(patch))
		req.Header.Set("Authorization", "Bearer "+token)
		req.Header.Set("X-Password", url.QueryEscape(primary.Password))
		req.Header.Set("Content-Type", "application/json")
		res, e = client.Do(req)
		if e != nil {
			return fmt.Errorf("用户权限应用失败")
		}
		io.Copy(io.Discard, io.LimitReader(res.Body, 8192))
		res.Body.Close()
		if res.StatusCode != http.StatusOK && res.StatusCode != http.StatusNoContent {
			return fmt.Errorf("用户权限应用被拒绝：HTTP %d", res.StatusCode)
		}
		req, _ = http.NewRequestWithContext(ctx, "GET", endpoint+"/api/users?username="+url.QueryEscape(u.Username), nil)
		req.Header.Set("Authorization", "Bearer "+token)
		res, e = client.Do(req)
		if e != nil {
			return fmt.Errorf("用户权限核验请求失败")
		}
		var profile struct {
			Username    string
			Permissions struct{ Admin, Api, Share bool }
			Scopes      []struct {
				Name        string
				Scope       string
				Permissions struct{ View, Download, Modify, Create, Delete bool }
			}
		}
		decodeErr := json.NewDecoder(io.LimitReader(res.Body, 16384)).Decode(&profile)
		res.Body.Close()
		wantRW := u.ReadWrite && !sourceRO
		if decodeErr != nil || res.StatusCode != 200 || profile.Username != u.Username || profile.Permissions.Admin || profile.Permissions.Api || profile.Permissions.Share || len(profile.Scopes) != 1 {
			return fmt.Errorf("用户身份或权限核验未通过")
		}
		p := profile.Scopes[0]
		if p.Name != "USB" || p.Scope != "/" || !p.Permissions.View || !p.Permissions.Download || p.Permissions.Modify != wantRW || p.Permissions.Create != wantRW || p.Permissions.Delete != wantRW {
			return fmt.Errorf("用户文件权限核验未通过")
		}
	}
	// Revoke the bootstrap login JWT; configured admin account remains available to its owner.
	req, _ := http.NewRequestWithContext(ctx, "POST", endpoint+"/api/auth/logout", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	if res, e := client.Do(req); e == nil {
		io.Copy(io.Discard, res.Body)
		res.Body.Close()
	}
	return nil
}
