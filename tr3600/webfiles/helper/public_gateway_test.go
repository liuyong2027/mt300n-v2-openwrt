package main

import (
	"crypto/tls"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"
	"time"
)

func publicFixture() publicAccessConfig {
	return publicAccessConfig{true, "8.8.4.4", 8080, "192.168.0.101", 8080, "eth0"}
}
func TestPublicAccessRejectsWildcardPrivateAndUnpinnedTargets(t *testing.T) {
	c := publicFixture()
	if e := validatePublicAccess(c, "192.168.9.1", 8080); e != nil {
		t.Fatal("same port on distinct IPs must work", e)
	}
	for _, ip := range []string{"0.0.0.0", "127.0.0.1", "192.168.0.1", "100.64.1.1", "169.254.1.1", "198.18.1.1", "203.0.113.1", "224.0.0.1", "255.255.255.255", "::1", "8.8.4.4;flush ruleset"} {
		x := c
		x.PublicIP = ip
		if validatePublicAccess(x, "192.168.9.1", 8080) == nil {
			t.Fatal("unsafe public address accepted", ip)
		}
	}
	for _, modify := range []func(*publicAccessConfig){func(c *publicAccessConfig) { c.ListenIP = "0.0.0.0" }, func(c *publicAccessConfig) { c.ListenIP = "192.168.9.1" }, func(c *publicAccessConfig) { c.ListenIP = "8.8.8.8" }, func(c *publicAccessConfig) { c.Interface = "zt*" }, func(c *publicAccessConfig) { c.Interface = `eth0";flush ruleset` }, func(c *publicAccessConfig) { c.Interface = "lo" }, func(c *publicAccessConfig) { c.ListenPort = 22 }, func(c *publicAccessConfig) { c.ExternalPort = 0 }} {
		x := c
		modify(&x)
		if validatePublicAccess(x, "192.168.9.1", 8080) == nil {
			t.Fatal("unsafe gateway configuration accepted", x)
		}
	}
	r, e := publicRule(c, "192.168.9.1", 8080, "cudy-webfiles-public-123-456")
	if e != nil || !strings.Contains(r, `iifname "eth0" ip daddr 192.168.0.101 tcp dport 8080`) {
		t.Fatal("WAN rule not scoped to exact interface/address/port", r, e)
	}
	if _, e = publicRule(c, "192.168.9.1", 8080, `other";flush ruleset`); e == nil {
		t.Fatal("foreign rule identity accepted")
	}
}
func TestPublicGatewayVerifiesBackendTLSAndStripsSpoofedHeaders(t *testing.T) {
	files, e := makeTLS("127.0.0.1")
	if e != nil {
		t.Fatal(e)
	}
	pair, e := tls.X509KeyPair(files["tls.crt"], files["tls.key"])
	if e != nil {
		t.Fatal(e)
	}
	backend := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Host != "8.8.4.4:8080" || r.Header.Get("Authorization") != "Bearer fixture-only" || r.URL.Path != "/api/resources" {
			t.Error("request identity was changed", r.Host, r.URL.Path)
		}
		for _, h := range []string{"Forwarded", "X-Forwarded-For", "X-Forwarded-Host", "X-Forwarded-Proto", "X-Real-IP", "X-Forwarded-User", "Proxy-Authorization"} {
			if r.Header.Get(h) != "" {
				t.Error("spoofed header forwarded", h)
			}
		}
		io.Copy(w, r.Body)
	}))
	backend.TLS = &tls.Config{Certificates: []tls.Certificate{pair}}
	backend.StartTLS()
	defer backend.Close()
	u, _ := url.Parse(backend.URL)
	h, e := publicHandler(publicFixture(), u, files["ca.crt"])
	if e != nil {
		t.Fatal(e)
	}
	r := httptest.NewRequest("PUT", "https://8.8.4.4:8080/api/resources", strings.NewReader("disposable-fixture"))
	r.Header.Set("Authorization", "Bearer fixture-only")
	for _, k := range []string{"Forwarded", "X-Forwarded-For", "X-Forwarded-Host", "X-Forwarded-Proto", "X-Real-IP", "X-Forwarded-User", "Proxy-Authorization"} {
		r.Header.Set(k, "forged")
	}
	w := httptest.NewRecorder()
	h.ServeHTTP(w, r)
	if w.Code != 200 || w.Body.String() != "disposable-fixture" {
		t.Fatal("TLS proxy failed", w.Code, w.Body.String())
	}
	wrong, _ := makeTLS("127.0.0.1")
	bad, _ := publicHandler(publicFixture(), u, wrong["ca.crt"])
	w = httptest.NewRecorder()
	bad.ServeHTTP(w, r)
	if w.Code != http.StatusBadGateway {
		t.Fatal("backend certificate validation bypassed", w.Code)
	}
	r.Host = "192.168.0.1"
	w = httptest.NewRecorder()
	h.ServeHTTP(w, r)
	if w.Code != http.StatusMisdirectedRequest {
		t.Fatal("unexpected host accepted", w.Code)
	}
}
func TestPublicConnectionLimiterIsBoundedAndRecovers(t *testing.T) {
	l := &limitedGatewayListener{clients: map[string]gatewayClientBucket{}}
	now := time.Now()
	for i := 0; i < 16; i++ {
		if !l.allow("198.51.100.1", now) {
			t.Fatal("initial burst rejected")
		}
	}
	if l.allow("198.51.100.1", now) {
		t.Fatal("unlimited connection burst")
	}
	if !l.allow("198.51.100.1", now.Add(time.Second)) {
		t.Fatal("connection bucket did not refill")
	}
	for i := 0; i < 1023; i++ {
		l.clients[string(rune(i))+"-fixture"] = gatewayClientBucket{0, now}
	}
	if l.allow("new-client", now) {
		t.Fatal("unbounded client map growth")
	}
	if !l.allow("new-client", now.Add(2*time.Minute)) {
		t.Fatal("expired client entries not reclaimed")
	}
}
