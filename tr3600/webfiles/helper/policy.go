package main

import (
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/sha256"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/hex"
	"encoding/json"
	"encoding/pem"
	"fmt"
	"math/big"
	"net"
	"regexp"
	"strconv"
	"strings"
	"time"
)

const version = "0.6.2-test"
const quantumHash = "dcca65dc898fd86bb8cc6cbd1a43b94dadd1cf2355ab6c2e07ec6dcff4c527b7"

type Volume struct {
	ID       string `json:"id"`
	UUID     string `json:"uuid"`
	Target   string `json:"target"`
	Device   string `json:"device"`
	FSType   string `json:"fstype"`
	ReadOnly bool   `json:"readOnly"`
	Share    string `json:"share"`
	Ready    bool   `json:"ready"`
}
type Snapshot struct {
	Board     string   `json:"board"`
	LAN       string   `json:"lan"`
	Interface string   `json:"iface"`
	Volumes   []Volume `json:"volumes"`
}
type MountInfo struct {
	ID, Device, Target, FSType string
	RW                         bool
}

var volumeID = regexp.MustCompile(`^usb_[a-z0-9_]+$`)
var deviceName = regexp.MustCompile(`^/dev/sd[a-z]+[0-9]*$`)
var ifaceName = regexp.MustCompile(`^[a-zA-Z0-9_.:-]{1,32}$`)
var uuidName = regexp.MustCompile(`^[a-z0-9-]{4,64}$`)

func validateSnapshot(s Snapshot) error {
	if s.Board != "cudy,tr3600-v1" {
		return fmt.Errorf("wrong board: %q", s.Board)
	}
	ip := net.ParseIP(s.LAN)
	if ip == nil || ip.To4() == nil || !ip.IsPrivate() {
		return fmt.Errorf("LAN must have an RFC1918 IPv4 address")
	}
	if !ifaceName.MatchString(s.Interface) {
		return fmt.Errorf("invalid LAN interface")
	}
	seen := map[string]bool{}
	for _, v := range s.Volumes {
		if !volumeID.MatchString(v.ID) || !uuidName.MatchString(v.UUID) || v.ID != "usb_"+strings.ReplaceAll(v.UUID, "-", "_") {
			return fmt.Errorf("invalid volume identity")
		}
		if seen[v.UUID] {
			return fmt.Errorf("duplicate UUID")
		}
		seen[v.UUID] = true
		if !deviceName.MatchString(v.Device) || !(v.Target == "/mnt/usb" || v.Target == "/mnt/cudy-usb/"+v.ID) {
			return fmt.Errorf("invalid volume path or device")
		}
		switch v.FSType {
		case "ext4", "vfat", "exfat", "ntfs3":
		default:
			return fmt.Errorf("unsupported filesystem")
		}
		if !v.Ready {
			return fmt.Errorf("unready volume")
		}
	}
	return nil
}
func selectVolume(s Snapshot, id string) (Volume, error) {
	if err := validateSnapshot(s); err != nil {
		return Volume{}, err
	}
	for _, v := range s.Volumes {
		if v.ID == id {
			return v, nil
		}
	}
	return Volume{}, fmt.Errorf("volume %q is not authorized, mounted and ready", id)
}
func unescapeMount(s string) string {
	return strings.NewReplacer(`\040`, " ", `\011`, "\t", `\012`, "\n", `\134`, `\`).Replace(s)
}
func parseMount(data, target string) (MountInfo, error) {
	var found *MountInfo
	for _, line := range strings.Split(data, "\n") {
		f := strings.Fields(line)
		if len(f) < 10 {
			continue
		}
		if unescapeMount(f[4]) != target {
			continue
		}
		sep := -1
		for i := 6; i < len(f); i++ {
			if f[i] == "-" {
				sep = i
				break
			}
		}
		if sep < 0 || sep+3 >= len(f) {
			return MountInfo{}, fmt.Errorf("invalid mountinfo")
		}
		if found != nil {
			return MountInfo{}, fmt.Errorf("overlapping mounts at target")
		}
		rw := strings.Contains(","+f[5]+",", ",rw,")
		if strings.Contains(","+f[sep+3]+",", ",ro,") {
			rw = false
		}
		m := MountInfo{ID: f[0] + ":" + f[2] + ":" + f[3], Device: unescapeMount(f[sep+2]), Target: unescapeMount(f[4]), FSType: f[sep+1], RW: rw}
		found = &m
	}
	if found == nil {
		return MountInfo{}, fmt.Errorf("authorized target is not a mount point")
	}
	return *found, nil
}
func mountMatches(v Volume, m MountInfo) error {
	if m.Device != v.Device || m.Target != v.Target || m.FSType != v.FSType {
		return fmt.Errorf("mount identity does not match USB authorization")
	}
	if !v.ReadOnly && !m.RW {
		return fmt.Errorf("read-write authorization has a read-only mount")
	}
	return nil
}

// Linux gives cloned mounts new IDs when creating a mount namespace. The
// supervisor still checks the original mount ID; the worker compares the
// filesystem device/root and access mode inherited across the clone.
func sameClonedMount(original, cloned MountInfo) bool {
	_, a, aok := strings.Cut(original.ID, ":")
	_, b, bok := strings.Cut(cloned.ID, ":")
	return aok && bok && a == b && original.Device == cloned.Device &&
		original.Target == cloned.Target && original.FSType == cloned.FSType && original.RW == cloned.RW
}
func signature(s Snapshot, v Volume, m MountInfo) string {
	b, _ := json.Marshal(struct {
		LAN, Interface string
		V              Volume
		M              MountInfo
	}{s.LAN, s.Interface, v, m})
	h := sha256.Sum256(b)
	return hex.EncodeToString(h[:])
}
func makeConfig(v Volume, lan string, port int, readWrite bool, source, state, cache, password string) ([]byte, error) {
	if port < 1024 || port > 65535 {
		return nil, fmt.Errorf("port must be 1024..65535")
	}
	ro := v.ReadOnly || !readWrite
	c := map[string]any{
		"http": map[string]any{"listen": lan, "port": port, "baseURL": "/", "tlsCert": state + "/tls.crt", "tlsKey": state + "/tls.key", "disableWebDAV": true, "trustProxyHeaders": false, "disableRateLimit": false},
		"server": map[string]any{
			"database": map[string]any{"path": state + "/data.sqlite", "activity": map[string]any{"disabled": true}},
			"cacheDir": cache, "disableUpdateCheck": true, "disablePreviews": true, "numImageProcessors": 1, "maxArchiveSize": 1,
			"indexSqlConfig": map[string]any{"cacheSizeMB": 4, "batchSize": 100, "walMode": false},
			"filesystem":     map[string]any{"createFilePermission": "664", "createDirectoryPermission": "775"},
			"logging":        []any{map[string]any{"levels": "info|error|warning", "output": "stdout", "noColors": true, "apiFilter": "disabled"}},
			"sources": []any{map[string]any{"name": "USB", "path": source, "config": map[string]any{
				"readOnly": ro, "private": true, "defaultEnabled": true,
				"defaultPermissions": map[string]any{"view": true, "download": true, "create": false, "modify": false, "delete": false},
				"rules":              []any{map[string]any{"folderPath": "/", "viewable": true, "ignoreSymlinks": true}, map[string]any{"folderName": ".samba-metadata", "viewable": false}},
			}}},
		},
		"auth":     map[string]any{"adminUsername": "admin", "adminPassword": password, "tokenExpirationHours": 2, "methods": map[string]any{"noauth": false, "password": map[string]any{"enabled": true, "minLength": 6, "signup": false}, "passkey": map[string]any{"enabled": false}}},
		"frontend": map[string]any{"name": "Cudy webpage", "description": "TR3600 HTTPS USB test", "disableDefaultLinks": true},
		"userDefaults": map[string]any{
			"fileLoading": map[string]any{"maxConcurrentUpload": 1, "uploadChunkSizeMb": 4, "downloadChunkSizeMb": 4},
			"preview":     map[string]any{"image": false, "video": false, "audio": false, "office": false, "folder": false, "models": false, "popup": false, "motionVideoPreview": false},
			"account":     map[string]any{"permissions": map[string]any{"share": false, "api": false, "admin": false, "realtime": false}},
		},
		"integrations": map[string]any{"media": map[string]any{"ffmpegPath": "/disabled-ffmpeg", "extractEmbeddedSubtitles": false}},
	}
	return json.MarshalIndent(c, "", "  ")
}
func makeTLS(ip string) (map[string][]byte, error) {
	if net.ParseIP(ip) == nil && !usablePublicDomain(ip) {
		return nil, fmt.Errorf("invalid certificate identity")
	}
	serial := func() *big.Int { n, _ := rand.Int(rand.Reader, new(big.Int).Lsh(big.NewInt(1), 128)); return n }
	caKey, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		return nil, err
	}
	now := time.Now()
	ca := &x509.Certificate{SerialNumber: serial(), Subject: pkix.Name{CommonName: "Cudy WebFiles TEST CA"}, NotBefore: now.Add(-time.Hour), NotAfter: now.AddDate(0, 0, 30), IsCA: true, BasicConstraintsValid: true, KeyUsage: x509.KeyUsageCertSign | x509.KeyUsageCRLSign}
	caDER, err := x509.CreateCertificate(rand.Reader, ca, ca, &caKey.PublicKey, caKey)
	if err != nil {
		return nil, err
	}
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		return nil, err
	}
	cert := &x509.Certificate{SerialNumber: serial(), Subject: pkix.Name{CommonName: "Cudy webpage Test"}, NotBefore: now.Add(-time.Hour), NotAfter: now.AddDate(0, 0, 30), IPAddresses: []net.IP{net.ParseIP(ip)}, KeyUsage: x509.KeyUsageDigitalSignature, ExtKeyUsage: []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth}}
	if net.ParseIP(ip) == nil {
		cert.IPAddresses = nil
		cert.DNSNames = []string{ip}
	}
	der, err := x509.CreateCertificate(rand.Reader, cert, ca, &key.PublicKey, caKey)
	if err != nil {
		return nil, err
	}
	kb, err := x509.MarshalECPrivateKey(key)
	if err != nil {
		return nil, err
	}
	return map[string][]byte{"ca.crt": pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: caDER}), "tls.crt": pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der}), "tls.key": pem.EncodeToMemory(&pem.Block{Type: "EC PRIVATE KEY", Bytes: kb})}, nil
}
func readMemAvailable(data string) (int64, error) {
	for _, line := range strings.Split(data, "\n") {
		f := strings.Fields(line)
		if len(f) >= 2 && f[0] == "MemAvailable:" {
			return strconv.ParseInt(f[1], 10, 64)
		}
	}
	return 0, fmt.Errorf("MemAvailable missing")
}
