package main

import (
	"crypto/tls"
	"crypto/x509"
	"encoding/pem"
	"testing"
	"time"
)

func TestCertificateOneYearForIPAndDomain(t *testing.T) {
	for _, identity := range []string{"192.168.9.1", "files.example.net"} {
		t.Run(identity, func(t *testing.T) {
			before := time.Now()
			files, err := makeTLS(identity)
			if err != nil {
				t.Fatal(err)
			}
			after := time.Now()
			parse := func(name string) *x509.Certificate {
				t.Helper()
				block, _ := pem.Decode(files[name])
				if block == nil {
					t.Fatalf("%s is not a certificate", name)
				}
				cert, err := x509.ParseCertificate(block.Bytes)
				if err != nil {
					t.Fatal(err)
				}
				return cert
			}
			root, leaf := parse("ca.crt"), parse("tls.crt")
			if root.Subject.CommonName != "Cudy webpage CA" || leaf.Subject.CommonName != "Cudy webpage" {
				t.Fatal("certificate display names still contain a test label")
			}
			for _, cert := range []*x509.Certificate{root, leaf} {
				if cert.NotAfter.Before(before.AddDate(0, 0, 365).Add(-time.Second)) || cert.NotAfter.After(after.AddDate(0, 0, 365)) {
					t.Fatalf("certificate expires at %v, expected 365 days after issuance", cert.NotAfter)
				}
			}
			if !root.NotAfter.Equal(leaf.NotAfter) {
				t.Fatal("CA and server certificate must have matching expiry dates")
			}
			if _, err := tls.X509KeyPair(files["tls.crt"], files["tls.key"]); err != nil {
				t.Fatalf("server private key does not match: %v", err)
			}
			pool := x509.NewCertPool()
			pool.AddCert(root)
			for _, when := range []time.Time{after, before.AddDate(0, 0, 364), leaf.NotAfter.Add(-time.Second)} {
				if _, err := leaf.Verify(x509.VerifyOptions{Roots: pool, DNSName: identity, CurrentTime: when}); err != nil {
					t.Fatalf("certificate must verify at %v: %v", when, err)
				}
			}
			if _, err := leaf.Verify(x509.VerifyOptions{Roots: pool, DNSName: identity, CurrentTime: leaf.NotAfter.Add(time.Second)}); err == nil {
				t.Fatal("expired certificate accepted")
			}
			if _, err := leaf.Verify(x509.VerifyOptions{Roots: pool, DNSName: "wrong.example.org", CurrentTime: after}); err == nil {
				t.Fatal("wrong host accepted")
			}
		})
	}
}
