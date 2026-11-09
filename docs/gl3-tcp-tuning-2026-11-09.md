# GL3 TCP tuning changelog — 2026-11-09

Router: **GL3** (Cudy TR3600 v1)  
Firmware: OpenWrt 25.12.6, `tr3600-ssrplus-ikev2-1.3.0` (kernel 6.12.112)  
Path tested: IKEv2 tunnel (`xfrm-mango`), round-trip latency about **200–202 ms**  
Session time: 10:44 AM–11:00 AM PST (America/Los_Angeles) on 2026-11-09  
These sysctl changes were applied **live on the router**. They are not baked into the firmware image unless they are added to a later build.

## What changed

Settings were written to `/etc/sysctl.d/99-tcp-bdp.conf` and applied immediately with `sysctl -p`. OpenWrt’s sysctl init loads `/etc/sysctl.d/*.conf` then `/etc/sysctl.conf` at boot, so the file survives reboot. The router was **not** rebooted.

### Before

| Setting | Value |
| --- | --- |
| `net.ipv4.tcp_rmem` | `4096 131072 3949760` |
| `net.ipv4.tcp_wmem` | `4096 16384 3949760` |
| `net.core.rmem_max` | `212992` (~208 KB) |
| `net.core.wmem_max` | `212992` (~208 KB) |
| `net.ipv4.tcp_window_scaling` | `1` (already on) |
| `net.ipv4.tcp_timestamps` | `1` (already on) |
| `net.ipv4.tcp_sack` | `1` (already on) |
| `net.ipv4.tcp_congestion_control` | `cubic` |
| Available algorithms | `reno cubic` |

### After (current)

| Setting | Value |
| --- | --- |
| `net.ipv4.tcp_rmem` | `4096 87380 16777216` (16 MB max) |
| `net.ipv4.tcp_wmem` | `4096 87380 16777216` (16 MB max) |
| `net.core.rmem_max` | `16777216` |
| `net.core.wmem_max` | `16777216` |
| Window scaling / timestamps / SACK | unchanged (already enabled) |
| `net.ipv4.tcp_congestion_control` | still `cubic` |

### BBR

BBR is **not available** on this firmware kernel. `modprobe tcp_bbr` failed, no `*bbr*` module was present under `/lib/modules`, and `tcp_available_congestion_control` listed only `reno cubic`. Congestion control was left on cubic. Enabling BBR would require a firmware rebuild that includes it. It was not forced.

### Send-buffer trial during this session

`tcp_wmem` was briefly lowered to `4096 87380 1048576` (1 MB max) to see if the large send buffer was hurting upload. Single-thread tunnel upload went to **18.7 Mbps**. The 16 MB send-buffer maximum was then restored. `tcp_rmem` stayed at 16 MB max throughout that trial.

## Speed test results

All tests were run on GL3 itself against Cloudflare (`speed.cloudflare.com`). Single-thread tests used a 2 MB warmup, then 30 MB download and 15 MB upload. Eight-connection tests used eight parallel 12 MB downloads (browser User-Agent and Referer) and eight parallel 8 MB uploads.

### Single-thread, IKEv2 tunnel

| When | Download | Upload | Latency |
| --- | ---: | ---: | ---: |
| Before any TCP tuning (10:44 AM PST) | 27.7 Mbps | 36.1 Mbps | ~202 ms |
| After raising both buffers to 16 MB (10:55 AM PST) | 62.1 Mbps | 21.6 Mbps | ~201 ms |
| After lowering send buffer to 1 MB (10:58 AM PST) | 62.3 Mbps | 18.7 Mbps | ~202 ms |
| After restoring send buffer to 16 MB (10:59 AM PST) | **62.2 Mbps** | **20.3 Mbps** | ~201 ms |

Headline before/after: **27.7 down / 36.1 up** → **62.2 down / 20.3 up**.

### Eight connections

| Path | Download | Upload |
| --- | ---: | ---: |
| IKEv2 tunnel | 138.6 Mbps | 26.9 Mbps |
| WAN direct | 183.3 Mbps | 27.9 Mbps |

### Other measurements from the same session (before TCP tuning)

- Single-thread WAN direct: 37.6 Mbps down / 37.9 Mbps up
- WAN gateway ping: about 0.4 ms

## Key findings

1. **Single-thread download was window-limited.** At about 200 ms RTT, a path around 37 Mbps has a bandwidth-delay product of about **925 KB**. A small default window (often discussed as ~64 KB, and here the previous core memory caps were only ~208 KB) cannot fill that pipe on one TCP connection. Raising the receive buffer almost doubled single-thread download (27.7 → 62.2 Mbps). Eight connections filled the pipe much further (138.6 Mbps on the tunnel, 183.3 Mbps on WAN).

2. **Multi-connection download uses the path far better than one stream.** That matches a high-latency, high-BDP link.

3. **Upload does not appear to be limited by an undersized send buffer.** Raising `tcp_wmem` to 16 MB dropped single-thread tunnel upload from 36.1 to about 20–22 Mbps; lowering it to 1 MB made upload 18.7 Mbps and did not recover the original 36.1. Eight-connection upload is similar on the tunnel and on WAN (26.9 vs 27.9 Mbps). The remaining upload ceiling is more consistent with IKEv2 encryption overhead, peer-side limiting, path asymmetry, or extra buffering interacting badly with cubic on a ~200 ms path — not with “the send window is too small.”

4. **BBR would require a firmware rebuild.** This kernel only offers reno and cubic.

## Persistence

Current live file: `/etc/sysctl.d/99-tcp-bdp.conf`

```
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 87380 16777216
net.ipv4.tcp_window_scaling = 1
net.ipv4.tcp_timestamps = 1
net.ipv4.tcp_sack = 1
```

These values persist across reboots. They live on the router until changed or until a firmware flash overwrites `/etc/sysctl.d` without keeping this file.
