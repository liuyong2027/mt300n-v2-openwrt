package main

import (
	"encoding/json"
	"fmt"
	"strings"
)

const maxManagedUsers = 16

type managedUser struct {
	Username  string `json:"username"`
	Password  string `json:"password"`
	ReadWrite bool   `json:"read_write"`
	Admin     bool   `json:"admin"`
}
type managedRegistry struct {
	Schema  int           `json:"schema"`
	Primary string        `json:"primary"`
	Users   []managedUser `json:"users"`
}
type managedUserEdit struct {
	Original  string `json:"original_username"`
	Username  string `json:"username"`
	Password  string `json:"password"`
	ReadWrite bool   `json:"read_write"`
}

func registryFromLegacy(a managedAccount) managedRegistry {
	return managedRegistry{1, a.Username, []managedUser{{a.Username, a.Password, true, true}}}
}
func validateRegistry(r managedRegistry) error {
	if r.Schema != 1 || len(r.Users) < 1 || len(r.Users) > maxManagedUsers {
		return fmt.Errorf("需设置 1–16 个网页用户")
	}
	names := map[string]bool{}
	admins := 0
	for _, u := range r.Users {
		if e := validateManagedAccount(managedAccount{u.Username, u.Password}); e != nil {
			return e
		}
		if strings.EqualFold(u.Username, "anonymous") {
			return fmt.Errorf("不能使用保留用户名 anonymous")
		}
		if names[u.Username] {
			return fmt.Errorf("用户名重复")
		}
		names[u.Username] = true
		if u.Admin {
			admins++
			if u.Username != r.Primary || !u.ReadWrite {
				return fmt.Errorf("管理员设置无效")
			}
		}
	}
	if admins != 1 || !names[r.Primary] {
		return fmt.Errorf("必须保留原网页管理员")
	}
	return nil
}
func primaryAccount(r managedRegistry) managedAccount {
	for _, u := range r.Users {
		if u.Username == r.Primary {
			return managedAccount{u.Username, u.Password}
		}
	}
	return managedAccount{}
}
func editManagedUser(r managedRegistry, e managedUserEdit) (managedRegistry, error) {
	next := r
	next.Users = append([]managedUser(nil), r.Users...)
	if e.Original == "" {
		if len(next.Users) >= maxManagedUsers {
			return r, fmt.Errorf("本测试版最多管理 16 个网页用户")
		}
		u := managedUser{e.Username, e.Password, e.ReadWrite, false}
		if len(next.Users) == 0 {
			next.Schema = 1
			next.Primary = e.Username
			u.Admin = true
			u.ReadWrite = true
		}
		next.Users = append(next.Users, u)
	} else {
		found := false
		for i, u := range next.Users {
			if u.Username != e.Original {
				continue
			}
			found = true
			if u.Admin && !e.ReadWrite {
				return r, fmt.Errorf("管理员不能设置为只读；全局只读设置仍生效")
			}
			if e.Password != "" {
				u.Password = e.Password
			}
			u.Username = e.Username
			u.ReadWrite = e.ReadWrite
			next.Users[i] = u
			if u.Admin {
				next.Primary = e.Username
			}
			break
		}
		if !found {
			return r, fmt.Errorf("要编辑的用户已不存在")
		}
	}
	if err := validateRegistry(next); err != nil {
		return r, err
	}
	return next, nil
}
func deleteManagedUser(r managedRegistry, name string) (managedRegistry, error) {
	if name == r.Primary {
		return r, fmt.Errorf("请保留网页管理员，不能删除")
	}
	next := r
	next.Users = nil
	found := false
	for _, u := range r.Users {
		if u.Username == name {
			found = true
		} else {
			next.Users = append(next.Users, u)
		}
	}
	if !found {
		return r, fmt.Errorf("要删除的用户已不存在")
	}
	return next, validateRegistry(next)
}
func publicManagedUsers(r managedRegistry) []map[string]any {
	out := make([]map[string]any, 0, len(r.Users))
	for _, u := range r.Users {
		out = append(out, map[string]any{"username": u.Username, "read_write": u.ReadWrite, "admin": u.Admin})
	}
	return out
}
func quantumUserPayload(u managedUser, sourceReadOnly bool) []byte {
	rw := u.ReadWrite && !sourceReadOnly
	p := map[string]any{"which": []string{}, "data": map[string]any{"username": u.Username, "password": u.Password, "loginMethod": "password", "permissions": map[string]bool{"admin": false, "api": false, "share": false, "realtime": false}, "scopes": []any{map[string]any{"name": "USB", "scope": "/", "permissions": map[string]bool{"view": true, "download": true, "modify": rw, "create": rw, "delete": rw}}}}}
	b, _ := json.Marshal(p)
	return b
}
