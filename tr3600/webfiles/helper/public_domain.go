package main

import (
	"net"
	"regexp"
	"strings"
)

func canonicalPublicAddress(s string) string {
	return strings.TrimSuffix(strings.ToLower(strings.TrimSpace(s)), ".")
}
func usablePublicDomain(s string) bool {
	if s != canonicalPublicAddress(s) || len(s) > 253 || net.ParseIP(s) != nil {
		return false
	}
	labels := strings.Split(s, ".")
	if len(labels) < 2 {
		return false
	}
	for _, suffix := range []string{"local", "localhost", "lan", "home", "internal", "invalid", "test", "arpa"} {
		if labels[len(labels)-1] == suffix {
			return false
		}
	}
	label := regexp.MustCompile(`^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$`)
	for _, v := range labels {
		if !label.MatchString(v) {
			return false
		}
	}
	return regexp.MustCompile(`[a-z]`).MatchString(labels[len(labels)-1])
}
func usablePublicAddress(s string) bool { return usablePublicIPv4(s) || usablePublicDomain(s) }

// Preserve the original public-IP CA when trying a domain or switching back.
// The single domain slot is encrypted with a different AEAD purpose.
func publicTLSStorage(host string) (name, purpose string) {
	if usablePublicDomain(host) {
		return "public-domain-tls.enc", "public-domain-tls"
	}
	return "public-tls.enc", "public-tls"
}
