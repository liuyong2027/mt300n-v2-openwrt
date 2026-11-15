/* Stubs so squashfs.c links in the host probe. The regression does not read squashfs. */
#ifndef _LIBUBOX_MD5_H
#define _LIBUBOX_MD5_H

#include <stddef.h>

typedef struct md5_ctx {
	unsigned char dummy[128];
} md5_ctx_t;

static inline void md5_begin(md5_ctx_t *ctx)
{
	(void)ctx;
}

static inline void md5_hash(const void *data, size_t length, md5_ctx_t *ctx)
{
	(void)data;
	(void)length;
	(void)ctx;
}

static inline void md5_end(void *resbuf, md5_ctx_t *ctx)
{
	unsigned char *out = resbuf;
	size_t i;

	(void)ctx;
	for (i = 0; i < 16; i++)
		out[i] = 0;
}

#endif
