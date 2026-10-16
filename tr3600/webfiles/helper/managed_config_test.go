package main

import (
	"bytes"
	"encoding/json"
	"strings"
	"testing"
)

func TestManagedCredentialValidation(t *testing.T) {
	good := managedAccount{"alice", "aB3!x7"}
	if e := validateManagedAccount(good); e != nil {
		t.Fatal(e)
	}
	if e := validateManagedAccount(managedAccount{"alice", "六个字符中文"}); e != nil {
		t.Fatal(e)
	}
	for _, a := range []managedAccount{{"../root", good.Password}, {"a", good.Password}, {"alice", "short"}, {"alice", strings.Repeat("x", 73)}, {"alice", " Leading-password-123"}, {"alice", "password-with\nnewline"}} {
		if validateManagedAccount(a) == nil {
			t.Fatalf("accepted invalid credential for %q", a.Username)
		}
	}
}
func TestManagedEncryptedPersistenceAndTamper(t *testing.T) {
	key := bytes.Repeat([]byte{7}, 32)
	plain, _ := json.Marshal(managedAccount{"alice", "Testing-only-Password-8173"})
	stored, e := sealManaged(key, "account", plain)
	if e != nil {
		t.Fatal(e)
	}
	if bytes.Contains(stored, []byte("Testing-only-Password")) {
		t.Fatal("plaintext credential in stored data")
	}
	recovered, e := openManaged(key, "account", stored)
	if e != nil || !bytes.Equal(recovered, plain) {
		t.Fatal("persistent credential did not survive reload")
	}
	if _, e = openManaged(key, "tls", stored); e == nil {
		t.Fatal("cross-purpose ciphertext accepted")
	}
	stored[len(stored)-1] ^= 1
	if _, e = openManaged(key, "account", stored); e == nil {
		t.Fatal("tampering was not detected")
	}
}
func TestManagedQuantumIdentityAndPolicy(t *testing.T) {
	v := Volume{ID: "usb_abcd_1234", Device: "/dev/sda1", Target: "/mnt/cudy-usb/usb_abcd_1234"}
	raw, e := makeConfig(v, "192.168.9.1", 8443, false, "/usb", "/state", "/cache", "bootstrap-testing-123")
	if e != nil {
		t.Fatal(e)
	}
	a := managedAccount{"alice", "Testing-only-Password-8173"}
	raw, e = managedQuantumConfig(raw, a)
	if e != nil {
		t.Fatal(e)
	}
	var c map[string]any
	json.Unmarshal(raw, &c)
	auth := c["auth"].(map[string]any)
	if auth["adminUsername"] != a.Username || auth["adminPassword"] != a.Password {
		t.Fatal("managed identity not applied")
	}
	password := auth["methods"].(map[string]any)["password"].(map[string]any)
	if password["minLength"] != float64(6) {
		t.Fatal("Quantum minimum password length must match managed validation")
	}
	http := c["http"].(map[string]any)
	if http["disableWebDAV"] != true || http["listen"] != "192.168.9.1" {
		t.Fatal("security policy changed")
	}
	source := c["server"].(map[string]any)["sources"].([]any)[0].(map[string]any)["config"].(map[string]any)
	if source["readOnly"] != true {
		t.Fatal("read-only policy lost")
	}
}
func TestManagedSettingValidation(t *testing.T) {
	for _, s := range []managedSettings{{"", 8080, false}, {"../../etc", 8443, true}, {"usb_abcd_1234", 443, true}, {"usb_abcd_1234", 65536, true}} {
		if validateManagedSettings(s) == nil {
			t.Fatal("invalid managed settings accepted")
		}
	}
	if e := validateManagedSettings(managedSettings{"usb_abcd_1234", 8443, true}); e != nil {
		t.Fatal(e)
	}
}
