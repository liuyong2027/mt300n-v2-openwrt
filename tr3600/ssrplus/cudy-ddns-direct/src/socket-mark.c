/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include <errno.h>
#include <stdint.h>
#include <sys/socket.h>
#include <sys/syscall.h>
#include <unistd.h>

/* This is SSR Plus+'s existing OUTPUT bypass mark, not a new route mark.
 * No environment variable or command argument can change it. */
#define CUDY_DDNS_DIRECT_MARK UINT32_C(255)

static int marked_socket(int domain, int type, int protocol)
{
    int fd = (int)syscall(SYS_socket, domain, type, protocol);
    if (fd < 0 || (domain != AF_INET && domain != AF_INET6))
        return fd;
    uint32_t mark = CUDY_DDNS_DIRECT_MARK;
    uint32_t actual = 0;
    socklen_t length = sizeof(actual);
    if (setsockopt(fd, SOL_SOCKET, SO_MARK, &mark, sizeof(mark)) != 0 ||
        getsockopt(fd, SOL_SOCKET, SO_MARK, &actual, &length) != 0 ||
        length != sizeof(actual) || actual != mark) {
        int saved = errno ? errno : EPERM;
        close(fd);
        errno = saved;
        return -1;
    }
    return fd;
}

int socket(int domain, int type, int protocol)
{
    return marked_socket(domain, type, protocol);
}

/* The launcher calls this before curl starts. A missing/invalid preload or
 * unavailable SO_MARK must stop DDNS instead of silently sending unmarked. */
int cudy_ddns_direct_check(void)
{
    int fd = marked_socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0);
    if (fd < 0)
        return -1;
    close(fd);
    return 0;
}
