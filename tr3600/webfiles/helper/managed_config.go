package main

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"encoding/json"
	"fmt"
	"regexp"
	"strings"
	"unicode/utf8"
)

type managedAccount struct {
	Username string `json:"username"`
	Password string `json:"password"`
}
type managedSettings struct {
	Volume    string `json:"volume"`
	Port      int    `json:"port"`
	ReadWrite bool   `json:"read_write"`
}

func validateManagedAccount(a managedAccount) error {
	if !regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9_.-]{2,31}$`).MatchString(a.Username) {
		return fmt.Errorf("用户名需为 3–32 位字母、数字、点、下划线或短横线")
	}
	if !utf8.ValidString(a.Password) || utf8.RuneCountInString(a.Password) < 6 || len(a.Password) > 72 || strings.TrimSpace(a.Password) != a.Password || strings.ContainsAny(a.Password, "\x00\r\n") {
		return fmt.Errorf("密码至少 6 个字符、最多 72 字节，不能有换行或首尾空格")
	}
	return nil
}
func validateManagedSettings(s managedSettings) error {
	if !regexp.MustCompile(`^usb_[a-z0-9][a-z0-9_-]{0,63}$`).MatchString(s.Volume) {
		return fmt.Errorf("请选择原系统已授权的 USB 存储设备")
	}
	if s.Port < 1024 || s.Port > 65535 {
		return fmt.Errorf("HTTPS 端口需为 1024–65535")
	}
	return nil
}
func sealManaged(key []byte, purpose string, plain []byte) ([]byte, error) {
	b, e := aes.NewCipher(key)
	if e != nil {
		return nil, e
	}
	g, e := cipher.NewGCM(b)
	if e != nil {
		return nil, e
	}
	n := make([]byte, g.NonceSize())
	if _, e = rand.Read(n); e != nil {
		return nil, e
	}
	return g.Seal(n, n, plain, []byte("Cudy WebFiles managed v0.2:"+purpose)), nil
}
func openManaged(key []byte, purpose string, data []byte) ([]byte, error) {
	b, e := aes.NewCipher(key)
	if e != nil {
		return nil, e
	}
	g, e := cipher.NewGCM(b)
	if e != nil {
		return nil, e
	}
	if len(data) < g.NonceSize()+g.Overhead() {
		return nil, fmt.Errorf("私有设置数据无效")
	}
	return g.Open(nil, data[:g.NonceSize()], data[g.NonceSize():], []byte("Cudy WebFiles managed v0.2:"+purpose))
}
func managedQuantumConfig(config []byte, a managedAccount) ([]byte, error) {
	if e := validateManagedAccount(a); e != nil {
		return nil, e
	}
	var c map[string]any
	if e := json.Unmarshal(config, &c); e != nil {
		return nil, e
	}
	auth, ok := c["auth"].(map[string]any)
	if !ok {
		return nil, fmt.Errorf("missing auth configuration")
	}
	auth["adminUsername"] = a.Username
	auth["adminPassword"] = a.Password
	return json.MarshalIndent(c, "", "  ")
}
