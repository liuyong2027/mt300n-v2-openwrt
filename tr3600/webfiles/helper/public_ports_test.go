package main

import (
	"crypto/tls"
	"net/http"
	"net/http/httptest"
	"net/url"
	"testing"
)

func TestExternalPrivilegedPortsKeepInternalListenerHigh(t *testing.T) {
	c := publicFixture()
	c.PublicIP = "files.example.net"
	for _, port := range []int{1, 80, 443, 8443, 65535} {
		c.ExternalPort = port
		if e := validatePublicAccess(c, "192.168.9.1", 8080); e != nil {
			t.Fatal(port, e)
		}
	}
	for _, port := range []int{-1, 0, 65536} {
		c.ExternalPort = port
		if validatePublicAccess(c, "192.168.9.1", 8080) == nil {
			t.Fatal("invalid external port accepted", port)
		}
	}
	c.ExternalPort = 443
	c.ListenPort = 443
	if validatePublicAccess(c, "192.168.9.1", 8080) == nil {
		t.Fatal("internal privileged listener accepted")
	}
	c.ListenPort = 8080
	if validatePublicAccess(c, "192.168.9.1", 443) == nil {
		t.Fatal("privileged LAN backend accepted")
	}
	if publicURL(c) != "https://files.example.net" {
		t.Fatal(publicURL(c))
	}
	c.PublicIP = "8.8.4.4"
	if publicURL(c) != "https://8.8.4.4" {
		t.Fatal(publicURL(c))
	}
	c.ExternalPort = 8443
	if publicURL(c) != "https://8.8.4.4:8443" {
		t.Fatal(publicURL(c))
	}
}

func TestDefaultHTTPSAuthorityForwardsLoginAndRejectsOtherPorts(t *testing.T) {
	files, e := makeTLS("127.0.0.1")
	if e != nil {
		t.Fatal(e)
	}
	pair, e := tls.X509KeyPair(files["tls.crt"], files["tls.key"])
	if e != nil {
		t.Fatal(e)
	}
	c := publicFixture()
	c.PublicIP = "files.example.net"
	c.ExternalPort = 443
	backend := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if !publicAuthorityMatches(c, r.Host) || r.URL.Path != "/api/auth/login" || r.Header.Get("X-Password") != "fixture-only" {
			t.Error("login request changed")
		}
		w.WriteHeader(http.StatusUnauthorized)
	}))
	backend.TLS = &tls.Config{Certificates: []tls.Certificate{pair}}
	backend.StartTLS()
	defer backend.Close()
	u, _ := url.Parse(backend.URL)
	h, e := publicHandler(c, u, files["ca.crt"])
	if e != nil {
		t.Fatal(e)
	}
	for _, host := range []string{"files.example.net", "files.example.net:443", "Files.Example.Net", "FILES.EXAMPLE.NET:443"} {
		r := httptest.NewRequest("POST", "https://files.example.net/api/auth/login", nil)
		r.Host = host
		r.Header.Set("X-Password", "fixture-only")
		w := httptest.NewRecorder()
		h.ServeHTTP(w, r)
		if w.Code != 401 {
			t.Fatal(host, w.Code)
		}
	}
	for _, host := range []string{"files.example.net:8443", "files.example.net:8080", "files.example.net:", "files.example.net:0443", "files.example.net.", "files.example.net.attacker.net", "other.dynu.net", "8.8.4.4", "user@files.example.net"} {
		r := httptest.NewRequest("GET", "https://files.example.net/login", nil)
		r.Host = host
		w := httptest.NewRecorder()
		h.ServeHTTP(w, r)
		if w.Code != 421 {
			t.Fatal("unexpected authority accepted", host, w.Code)
		}
	}
	c.ExternalPort = 8443
	if publicAuthorityMatches(c, "files.example.net") || publicAuthorityMatches(c, "files.example.net:443") || !publicAuthorityMatches(c, "files.example.net:8443") {
		t.Fatal("default port allowance leaked to a high-port configuration")
	}
}
