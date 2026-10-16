package main

import (
	"crypto/tls"
	"crypto/x509"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"net/http/httputil"
	"net/url"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"time"
)

type publicAccessConfig struct {
	Enabled      bool   `json:"enabled"`
	PublicIP     string `json:"public_ip"`
	ExternalPort int    `json:"external_port"`
	ListenIP     string `json:"listen_ip"`
	ListenPort   int    `json:"listen_port"`
	Interface    string `json:"interface"`
}
type publicAccessStatus struct {
	Config publicAccessConfig `json:"config"`
	Active bool               `json:"active"`
	URL    string             `json:"url,omitempty"`
	Error  string             `json:"error,omitempty"`
	PID    int                `json:"pid,omitempty"`
	RSSKiB int64              `json:"rss_kib,omitempty"`
}
type publicGatewayInput struct {
	Config    publicAccessConfig
	LAN       string
	Port      int
	BackendCA []byte
	Files     map[string][]byte
}

func usablePublicIPv4(s string) bool {
	ip := net.ParseIP(s)
	if ip == nil || ip.To4() == nil || ip.String() != s || !ip.IsGlobalUnicast() || ip.IsPrivate() {
		return false
	}
	for _, s := range []string{"0.0.0.0/8", "100.64.0.0/10", "192.0.0.0/24", "192.0.2.0/24", "198.18.0.0/15", "198.51.100.0/24", "203.0.113.0/24", "240.0.0.0/4"} {
		_, n, _ := net.ParseCIDR(s)
		if n.Contains(ip) {
			return false
		}
	}
	return true
}
func validatePublicAccess(c publicAccessConfig, lan string, port int) error {
	if !usablePublicAddress(c.PublicIP) {
		return fmt.Errorf("请填写有效的公网 IPv4 或 DDNS 域名，不含协议和端口")
	}
	ip := net.ParseIP(c.ListenIP)
	if ip == nil || ip.To4() == nil || !ip.IsPrivate() || ip.String() != c.ListenIP || c.ListenIP == lan {
		return fmt.Errorf("公网入口必须固定到当前上级私有 WAN 地址")
	}
	if !regexp.MustCompile(`^[A-Za-z0-9_.:-]{1,15}$`).MatchString(c.Interface) || c.Interface == "lo" || strings.HasPrefix(c.Interface, "br-") || strings.HasPrefix(c.Interface, "zt") {
		return fmt.Errorf("WAN 接口身份无效")
	}
	if c.ListenPort < 1024 || c.ListenPort > 65535 {
		return fmt.Errorf("TR3600 入口端口需为 1024–65535")
	}
	if c.ExternalPort < 1 || c.ExternalPort > 65535 {
		return fmt.Errorf("上级外部端口需为 1–65535")
	}
	ip = net.ParseIP(lan)
	if ip == nil || ip.To4() == nil || !ip.IsPrivate() || port < 1024 || port > 65535 {
		return fmt.Errorf("LAN 后端无效")
	}
	return nil
}
func publicURL(c publicAccessConfig) string {
	if c.ExternalPort == 443 {
		return "https://" + c.PublicIP
	}
	return "https://" + net.JoinHostPort(c.PublicIP, strconv.Itoa(c.ExternalPort))
}
func publicAuthorityMatches(c publicAccessConfig, authority string) bool {
	return strings.EqualFold(authority, net.JoinHostPort(c.PublicIP, strconv.Itoa(c.ExternalPort))) ||
		(c.ExternalPort == 443 && strings.EqualFold(authority, c.PublicIP))
}
func publicRule(c publicAccessConfig, lan string, port int, comment string) (string, error) {
	if validatePublicAccess(c, lan, port) != nil || !regexp.MustCompile(`^cudy-webfiles-public-[0-9]+-[0-9]+$`).MatchString(comment) {
		return "", fmt.Errorf("invalid public rule identity")
	}
	return fmt.Sprintf("insert rule inet fw4 input iifname %q ip daddr %s tcp dport %d counter accept comment %q\n", c.Interface, c.ListenIP, c.ListenPort, comment), nil
}
func publicHandler(c publicAccessConfig, target *url.URL, ca []byte) (http.Handler, error) {
	roots := x509.NewCertPool()
	if !roots.AppendCertsFromPEM(ca) {
		return nil, fmt.Errorf("invalid backend CA")
	}
	transport := &http.Transport{Proxy: nil, TLSClientConfig: &tls.Config{RootCAs: roots, MinVersion: tls.VersionTLS12},
		MaxConnsPerHost: 16, MaxIdleConns: 8, MaxIdleConnsPerHost: 8, IdleConnTimeout: 15 * time.Second,
		TLSHandshakeTimeout: 5 * time.Second, ResponseHeaderTimeout: 15 * time.Second, MaxResponseHeaderBytes: 65536}
	proxy := &httputil.ReverseProxy{Transport: transport, FlushInterval: 100 * time.Millisecond,
		Rewrite: func(r *httputil.ProxyRequest) {
			r.SetURL(target)
			r.Out.Host = r.In.Host
			for _, h := range []string{"Forwarded", "X-Forwarded-For", "X-Forwarded-Host", "X-Forwarded-Proto", "X-Real-IP", "X-Forwarded-User", "Proxy-Authorization"} {
				r.Out.Header.Del(h)
			}
		},
		ErrorLog: log.New(io.Discard, "", 0), ErrorHandler: func(w http.ResponseWriter, r *http.Request, e error) {
			http.Error(w, "File service temporarily unavailable", http.StatusBadGateway)
		}}
	slots := make(chan struct{}, 32)
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if !publicAuthorityMatches(c, r.Host) {
			http.Error(w, "Unexpected host", http.StatusMisdirectedRequest)
			return
		}
		switch r.Method {
		case "GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS":
		default:
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
			return
		}
		if r.Header.Get("Upgrade") != "" {
			http.Error(w, "Upgrade unavailable", http.StatusBadRequest)
			return
		}
		select {
		case slots <- struct{}{}:
			defer func() { <-slots }()
		default:
			http.Error(w, "Busy", http.StatusServiceUnavailable)
			return
		}
		proxy.ServeHTTP(w, r)
	}), nil
}

type gatewayClientBucket struct {
	tokens float64
	last   time.Time
}
type limitedGatewayListener struct {
	net.Listener
	slots   chan struct{}
	mu      sync.Mutex
	clients map[string]gatewayClientBucket
}
type limitedGatewayConn struct {
	net.Conn
	once    sync.Once
	release func()
}

func (c *limitedGatewayConn) Close() error { e := c.Conn.Close(); c.once.Do(c.release); return e }
func limitGatewayListener(l net.Listener) net.Listener {
	return &limitedGatewayListener{Listener: l, slots: make(chan struct{}, 16), clients: map[string]gatewayClientBucket{}}
}
func (l *limitedGatewayListener) allow(ip string, now time.Time) bool {
	l.mu.Lock()
	defer l.mu.Unlock()
	if len(l.clients) >= 1024 {
		for k, v := range l.clients {
			if now.Sub(v.last) > time.Minute {
				delete(l.clients, k)
			}
		}
	}
	v, ok := l.clients[ip]
	if !ok {
		if len(l.clients) >= 1024 {
			return false
		}
		v = gatewayClientBucket{16, now}
	}
	v.tokens += now.Sub(v.last).Seconds()
	if v.tokens > 16 {
		v.tokens = 16
	}
	v.last = now
	allowed := v.tokens >= 1
	if allowed {
		v.tokens--
	}
	l.clients[ip] = v
	return allowed
}
func (l *limitedGatewayListener) Accept() (net.Conn, error) {
	for {
		c, e := l.Listener.Accept()
		if e != nil {
			return nil, e
		}
		ip, _, e := net.SplitHostPort(c.RemoteAddr().String())
		if e != nil || !l.allow(ip, time.Now()) {
			c.Close()
			continue
		}
		select {
		case l.slots <- struct{}{}:
			return &limitedGatewayConn{Conn: c, release: func() { <-l.slots }}, nil
		default:
			c.Close()
		}
	}
}
func servePublicGateway(in publicGatewayInput) error {
	if e := validatePublicAccess(in.Config, in.LAN, in.Port); e != nil {
		return e
	}
	pair, e := tls.X509KeyPair(in.Files["tls.crt"], in.Files["tls.key"])
	if e != nil {
		return fmt.Errorf("invalid public TLS material")
	}
	cert, e := x509.ParseCertificate(pair.Certificate[0])
	if e != nil || cert.VerifyHostname(in.Config.PublicIP) != nil || time.Now().After(cert.NotAfter) {
		return fmt.Errorf("public certificate invalid or expired")
	}
	target, _ := url.Parse("https://" + net.JoinHostPort(in.LAN, strconv.Itoa(in.Port)))
	h, e := publicHandler(in.Config, target, in.BackendCA)
	if e != nil {
		return e
	}
	l, e := net.Listen("tcp4", net.JoinHostPort(in.Config.ListenIP, strconv.Itoa(in.Config.ListenPort)))
	if e != nil {
		return e
	}
	defer l.Close()
	s := &http.Server{Handler: h, ReadHeaderTimeout: 5 * time.Second, IdleTimeout: 30 * time.Second, MaxHeaderBytes: 32768,
		TLSConfig:    &tls.Config{MinVersion: tls.VersionTLS12, Certificates: []tls.Certificate{pair}, NextProtos: []string{"http/1.1"}},
		TLSNextProto: map[string]func(*http.Server, *tls.Conn, http.Handler){}, ErrorLog: log.New(io.Discard, "", 0)}
	return s.ServeTLS(limitGatewayListener(l), "", "")
}
