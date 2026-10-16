package main

import (
	"crypto/tls"
	"crypto/x509"
	"encoding/pem"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"
)

func TestPublicDomainValidationAndStrictHost(t *testing.T) {
	for _, host := range []string{"files.example.net", "files.example.net", "xn--bcher-kva.example.net"} {
		if !usablePublicDomain(host) {
			t.Fatal("valid domain rejected", host)
		}
	}
	for _, host := range []string{"localhost", "router.lan", "router.local", "files.invalid", "*.dynu.net", "https://files.example.net", "files.example.net:8443", "bad_label.dynu.net", "bad..dynu.net", "-bad.dynu.net", "bad-.dynu.net", "192.168.0.1", "100.64.0.1", "files.example.net';flush ruleset", "a." + strings.Repeat("x", 64) + ".net"} {
		if usablePublicAddress(host) {
			t.Fatal("invalid identity accepted", host)
		}
	}
	if canonicalPublicAddress(" Files.Example.Net. ") != "files.example.net" {
		t.Fatal("domain normalization failed")
	}
	c := publicFixture()
	c.PublicIP = "files.example.net"
	c.ExternalPort = 8443
	if e := validatePublicAccess(c, "192.168.9.1", 8080); e != nil {
		t.Fatal(e)
	}
	u, _ := url.Parse("https://127.0.0.1:1")
	files, _ := makeTLS("127.0.0.1")
	h, e := publicHandler(c, u, files["ca.crt"])
	if e != nil {
		t.Fatal(e)
	}
	for _, host := range []string{"files.example.net.attacker.net:8443", "8.8.4.4:8443", "files.example.net:8080", "other.dynu.net:8443"} {
		r := httptest.NewRequest("GET", "https://files.example.net:8443/login", nil)
		r.Host = host
		w := httptest.NewRecorder()
		h.ServeHTTP(w, r)
		if w.Code != 421 {
			t.Fatal("unrelated authority accepted", host, w.Code)
		}
	}
}
func TestDomainCertificateAndIndependentEncryptedStorage(t *testing.T) {
	files, e := makeTLS("files.example.net")
	if e != nil {
		t.Fatal(e)
	}
	block, _ := pem.Decode(files["tls.crt"])
	leaf, e := x509.ParseCertificate(block.Bytes)
	if e != nil {
		t.Fatal(e)
	}
	roots := x509.NewCertPool()
	roots.AppendCertsFromPEM(files["ca.crt"])
	if _, e = leaf.Verify(x509.VerifyOptions{Roots: roots, DNSName: "files.example.net"}); e != nil {
		t.Fatal(e)
	}
	if len(leaf.IPAddresses) != 0 || len(leaf.DNSNames) != 1 || leaf.DNSNames[0] != "files.example.net" {
		t.Fatal("domain SAN incorrectly depends on an IP address")
	}
	for _, host := range []string{"other.dynu.net", "8.8.4.4", "114.246.103.23"} {
		if leaf.VerifyHostname(host) == nil {
			t.Fatal("certificate accepted unrelated identity", host)
		}
	}
	ipName, ipPurpose := publicTLSStorage("8.8.4.4")
	domainName, domainPurpose := publicTLSStorage("files.example.net")
	if ipName != "public-tls.enc" || ipPurpose != "public-tls" || domainName == ipName || domainPurpose == ipPurpose {
		t.Fatal("domain certificate would replace original public-IP store")
	}
	key := make([]byte, 32)
	enc, e := sealManaged(key, domainPurpose, []byte("test-fixture"))
	if e != nil {
		t.Fatal(e)
	}
	if _, e = openManaged(key, ipPurpose, enc); e == nil {
		t.Fatal("domain ciphertext accepted in original IP store")
	}
}
func TestDomainGatewayForwardsLoginOnConfiguredExternalPort(t *testing.T) {
	files, _ := makeTLS("127.0.0.1")
	pair, e := tls.X509KeyPair(files["tls.crt"], files["tls.key"])
	if e != nil {
		t.Fatal(e)
	}
	backend := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if !strings.EqualFold(r.Host, "files.example.net:8443") || r.URL.Path != "/api/auth/login" || r.Header.Get("X-Password") != "fixture-only" {
			t.Error("login authority or payload changed")
		}
		w.WriteHeader(http.StatusUnauthorized)
	}))
	backend.TLS = &tls.Config{Certificates: []tls.Certificate{pair}}
	backend.StartTLS()
	defer backend.Close()
	c := publicFixture()
	c.PublicIP = "files.example.net"
	c.ExternalPort = 8443
	u, _ := url.Parse(backend.URL)
	h, e := publicHandler(c, u, files["ca.crt"])
	if e != nil {
		t.Fatal(e)
	}
	for _, host := range []string{"files.example.net:8443", "Files.Example.Net:8443"} {
		r := httptest.NewRequest("POST", "https://files.example.net:8443/api/auth/login", nil)
		r.Host = host
		r.Header.Set("X-Password", "fixture-only")
		w := httptest.NewRecorder()
		h.ServeHTTP(w, r)
		if w.Code != 401 {
			t.Fatal("domain login blocked before backend authentication", host, w.Code)
		}
	}
}
