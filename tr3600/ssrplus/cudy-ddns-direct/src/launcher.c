/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <elf.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

/* Compile-time paths are overridden only by the isolated native tests. */
#ifndef CUDY_DDNS_LIBRARY
#define CUDY_DDNS_LIBRARY "/usr/lib/cudy-ddns-direct/socket-mark.so"
#endif
#ifndef CUDY_DDNS_CURL
#define CUDY_DDNS_CURL "/usr/bin/curl"
#endif

static int dynamic_curl(void)
{
    struct stat st;
    Elf64_Ehdr header;
    int fd = open(CUDY_DDNS_CURL, O_RDONLY | O_CLOEXEC);
    if (fd < 0)
        return -1;
    if (fstat(fd, &st) != 0 || !S_ISREG(st.st_mode) ||
        (st.st_mode & (S_ISUID | S_ISGID)) ||
        read(fd, &header, sizeof(header)) != (ssize_t)sizeof(header) ||
        memcmp(header.e_ident, ELFMAG, SELFMAG) != 0 ||
        header.e_ident[EI_CLASS] != ELFCLASS64 ||
        header.e_ident[EI_DATA] != ELFDATA2LSB ||
        header.e_phentsize != sizeof(Elf64_Phdr) ||
        header.e_phnum == 0 || header.e_phnum > 256) {
        close(fd);
        return -1;
    }
    for (uint16_t i = 0; i < header.e_phnum; ++i) {
        Elf64_Phdr entry;
        off_t offset = (off_t)header.e_phoff + (off_t)i * sizeof(entry);
        if (pread(fd, &entry, sizeof(entry), offset) != (ssize_t)sizeof(entry))
            break;
        if (entry.p_type == PT_INTERP) {
            close(fd);
            return 0;
        }
    }
    close(fd);
    return -1;
}

int main(int argc, char **argv)
{
    void *library = dlopen(CUDY_DDNS_LIBRARY, RTLD_NOW | RTLD_LOCAL);
    int (*check)(void) = library ? dlsym(library, "cudy_ddns_direct_check") : NULL;
    if (!check || check() != 0 || dynamic_curl() != 0) {
        fputs("DDNS direct socket preflight failed; no request sent\n", stderr);
        return 125;
    }
    /* Replace, never append an inherited preload. --disable must be the first
     * curl argument so a curlrc cannot change this tightly scoped transfer. */
    if (setenv("LD_PRELOAD", CUDY_DDNS_LIBRARY, 1) != 0)
        return 125;
    char **arguments = calloc((size_t)argc + 4, sizeof(*arguments));
    if (!arguments)
        return 125;
    arguments[0] = CUDY_DDNS_CURL;
    arguments[1] = "--disable";
    for (int i = 1; i < argc; ++i)
        arguments[i + 1] = argv[i];
    /* Last-value precedence also defeats inherited ALL_PROXY/http_proxy and
     * any earlier --noproxy in the framework command. */
    arguments[argc + 1] = "--noproxy";
    arguments[argc + 2] = "*";
    execv(CUDY_DDNS_CURL, arguments);
    fputs("DDNS direct curl unavailable; no request sent\n", stderr);
    return 125;
}
