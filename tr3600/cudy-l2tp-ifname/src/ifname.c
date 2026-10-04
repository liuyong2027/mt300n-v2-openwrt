// SPDX-License-Identifier: MIT
#include <stdbool.h>
#include <stdint.h>
#include <sys/time.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <pppd/pppd.h>
#include <pppd/options.h>

char pppd_version[] = PPPD_VERSION;

void plugin_init(void)
{
    char path[] = "/tmp/cudy-l2tp-ifname.XXXXXX";
    int fd = mkstemp(path);
    FILE *file;
    int ok;
    if (fd < 0) {
        ppp_option_error("Cannot allocate VPN interface configuration");
        exit(EXIT_FAILURE);
    }
    file = fdopen(fd, "w");
    if (!file) {
        close(fd);
        unlink(path);
        exit(EXIT_FAILURE);
    }
    // Each concurrent pppd process has a unique PID. Names fit IFNAMSIZ and
    // match only this VPN's firewall zone, leaving other PPP interfaces alone.
    ok = fprintf(file, "ifname l2tp%lu\n", (unsigned long)getpid()) > 0;
    if (fclose(file) != 0) ok = 0;
    if (ok) ok = ppp_options_from_file(path, 1, 0, 1);
    unlink(path);
    if (!ok) {
        ppp_option_error("Cannot assign a separate VPN interface");
        exit(EXIT_FAILURE);
    }
}
