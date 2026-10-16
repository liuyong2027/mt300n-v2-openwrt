package main

import (
	"crypto/x509"
	"encoding/json"
	"encoding/pem"
	"net"
	"testing"
	"time"
)

func fixture() (Snapshot, Volume, MountInfo) {
	v := Volume{ID: "usb_abcd_1234", UUID: "abcd-1234", Device: "/dev/sda1", Target: "/mnt/cudy-usb/usb_abcd_1234", FSType: "vfat", Share: "USB", Ready: true}
	s := Snapshot{Board: "cudy,tr3600-v1", LAN: "192.168.8.1", Interface: "br-lan", Volumes: []Volume{v}}
	m := MountInfo{ID: "41:8:1:/", Device: v.Device, Target: v.Target, FSType: v.FSType, RW: true}
	return s, v, m
}
func TestAuthorizedVolume(t *testing.T) {
	s, v, m := fixture()
	got, e := selectVolume(s, v.ID)
	if e != nil || got != v {
		t.Fatal(got, e)
	}
	if e = mountMatches(v, m); e != nil {
		t.Fatal(e)
	}
}
func TestClonedMountIdentity(t *testing.T) {
	_, _, original := fixture()
	cloned := original
	cloned.ID = "99:8:1:/"
	if !sameClonedMount(original, cloned) {
		t.Fatal("namespace clone rejected")
	}
	for _, mutate := range []func(*MountInfo){
		func(m *MountInfo) { m.ID = "99:8:2:/" },
		func(m *MountInfo) { m.ID = "99:8:1:/subdir" },
		func(m *MountInfo) { m.ID = "invalid" },
		func(m *MountInfo) { m.Device = "/dev/sdb1" },
		func(m *MountInfo) { m.Target = "/other" },
		func(m *MountInfo) { m.FSType = "ext4" },
		func(m *MountInfo) { m.RW = false },
	} {
		changed := cloned
		mutate(&changed)
		if sameClonedMount(original, changed) {
			t.Fatal("changed mount accepted", changed)
		}
	}
}
func TestRejectUnsafeSnapshots(t *testing.T) {
	for _, test := range []struct {
		name   string
		mutate func(*Snapshot)
	}{
		{"wrong board", func(s *Snapshot) { s.Board = "other" }},
		{"WAN address", func(s *Snapshot) { s.LAN = "8.8.8.8" }},
		{"listen all", func(s *Snapshot) { s.LAN = "0.0.0.0" }},
		{"IPv6", func(s *Snapshot) { s.LAN = "fd00::1" }},
		{"interface injection", func(s *Snapshot) { s.Interface = "br-lan\"; accept" }},
		{"duplicate UUID", func(s *Snapshot) { s.Volumes = append(s.Volumes, s.Volumes[0]) }},
		{"invalid UUID", func(s *Snapshot) { s.Volumes[0].UUID = "../../root" }},
		{"unapproved root", func(s *Snapshot) { s.Volumes[0].Target = "/" }},
		{"mismatched id", func(s *Snapshot) { s.Volumes[0].ID = "usb_other" }},
		{"non USB device", func(s *Snapshot) { s.Volumes[0].Device = "/dev/mmcblk0p1" }},
		{"unready", func(s *Snapshot) { s.Volumes[0].Ready = false }},
	} {
		t.Run(test.name, func(t *testing.T) {
			s, _, _ := fixture()
			test.mutate(&s)
			if validateSnapshot(s) == nil {
				t.Fatal("unsafe snapshot accepted")
			}
		})
	}
}
func TestGuardChanges(t *testing.T) {
	s, v, m := fixture()
	base := signature(s, v, m)
	m.ID = "42:8:1:/"
	if signature(s, v, m) == base {
		t.Fatal("remount not detected")
	}
	_, _, m = fixture()
	m.Device = "/dev/sdb1"
	if mountMatches(v, m) == nil {
		t.Fatal("replacement disk accepted")
	}
	m.Device = v.Device
	m.RW = false
	if mountMatches(v, m) == nil {
		t.Fatal("writable mismatch accepted")
	}
	v.ReadOnly = true
	if mountMatches(v, m) != nil {
		t.Fatal("valid read-only rejected")
	}
}
func TestMountParser(t *testing.T) {
	_, v, _ := fixture()
	line := "41 20 8:1 / " + v.Target + " rw,nosuid,nodev - vfat /dev/sda1 rw\n"
	m, e := parseMount(line, v.Target)
	if e != nil || m.Device != v.Device || !m.RW {
		t.Fatal(m, e)
	}
	if _, e = parseMount(line+line, v.Target); e == nil {
		t.Fatal("stacked mount accepted")
	}
	if _, e = parseMount("", v.Target); e == nil {
		t.Fatal("unmounted folder accepted")
	}
	m, e = parseMount("41 20 8:1 / "+v.Target+" rw - vfat /dev/sda1 ro", v.Target)
	if e != nil || m.RW {
		t.Fatal("superblock readonly ignored")
	}
}
func TestConfigEnforcesReadOnly(t *testing.T) {
	_, v, _ := fixture()
	for _, tc := range []struct{ volRO, rw, wantRO bool }{{false, false, true}, {false, true, false}, {true, true, true}} {
		v.ReadOnly = tc.volRO
		b, e := makeConfig(v, "192.168.8.1", 8443, tc.rw, "/usb", "/state", "/cache", "testpassword1234")
		if e != nil {
			t.Fatal(e)
		}
		var c map[string]any
		json.Unmarshal(b, &c)
		http := c["http"].(map[string]any)
		if http["disableWebDAV"] != true || http["listen"] != "192.168.8.1" {
			t.Fatal(http)
		}
		server := c["server"].(map[string]any)
		source := server["sources"].([]any)[0].(map[string]any)["config"].(map[string]any)
		if source["readOnly"] != tc.wantRO {
			t.Fatal(source)
		}
		if server["disablePreviews"] != true {
			t.Fatal("previews enabled")
		}
		rules := source["rules"].([]any)[0].(map[string]any)
		if rules["viewable"] != true || rules["ignoreSymlinks"] != true {
			t.Fatal("unsafe rules")
		}
	}
}
func TestCertificateSANAndTrust(t *testing.T) {
	files, e := makeTLS("192.168.8.1")
	if e != nil {
		t.Fatal(e)
	}
	ca, _ := pem.Decode(files["ca.crt"])
	cert, _ := pem.Decode(files["tls.crt"])
	root, e := x509.ParseCertificate(ca.Bytes)
	if e != nil {
		t.Fatal(e)
	}
	leaf, e := x509.ParseCertificate(cert.Bytes)
	if e != nil {
		t.Fatal(e)
	}
	pool := x509.NewCertPool()
	pool.AddCert(root)
	if _, e = leaf.Verify(x509.VerifyOptions{Roots: pool, DNSName: "192.168.8.1", CurrentTime: time.Now()}); e != nil {
		t.Fatal(e)
	}
	if !leaf.IPAddresses[0].Equal(net.ParseIP("192.168.8.1")) {
		t.Fatal("wrong IP")
	}
	if _, e = leaf.Verify(x509.VerifyOptions{Roots: pool, DNSName: "192.168.8.2"}); e == nil {
		t.Fatal("wrong host accepted")
	}
}
func TestMemoryParser(t *testing.T) {
	n, e := readMemAvailable("MemTotal: 512000 kB\nMemAvailable: 100000 kB\n")
	if e != nil || n != 100000 {
		t.Fatal(n, e)
	}
	if _, e = readMemAvailable("MemFree: 123"); e == nil {
		t.Fatal("missing availability accepted")
	}
}
