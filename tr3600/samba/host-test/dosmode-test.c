#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <sys/stat.h>

#define FILE_ATTRIBUTE_READONLY 0x01U
#define FILE_ATTRIBUTE_HIDDEN 0x02U
#define FILE_ATTRIBUTE_SYSTEM 0x04U
#define FILE_ATTRIBUTE_DIRECTORY 0x10U
#define FILE_ATTRIBUTE_ARCHIVE 0x20U
#define FILE_ATTRIBUTE_NORMAL 0x80U
#define FILE_ATTRIBUTE_SPARSE 0x200U
#define FILE_ATTRIBUTE_REPARSE_POINT 0x400U
#define FILE_ATTRIBUTE_COMPRESSED 0x800U
#define FILE_FILE_COMPRESSION 0x10U
#define SMB_ASSERT assert
#define NTSTATUS int
#define NT_STATUS_IS_OK(status) ((status) == 0)

struct smb_filename {
    struct { unsigned int st_ex_mode; } st;
    const char *base_name;
};

struct connection_struct {
    uint32_t fs_capabilities;
    void *sconn;
};

struct files_struct {
    struct smb_filename *fsp_name;
    struct connection_struct *conn;
    bool named_stream;
    bool compressed;
};

static bool is_named_stream(const struct smb_filename *name)
{
    return name->base_name[0] == ':';
}

static int dos_mode_check_compressed(struct files_struct *fsp, bool *compressed)
{
    *compressed = fsp->compressed;
    return 0;
}

static uint32_t dos_mode_from_name(struct connection_struct *conn,
                                  const char *name, uint32_t dosmode)
{
    (void)conn;
    (void)name;
    (void)dosmode;
    return 0;
}

static int conn_protocol(void *sconn)
{
    (void)sconn;
    return 0;
}

static uint32_t filter_mode_by_protocol(int protocol, uint32_t dosmode)
{
    (void)protocol;
    return dosmode;
}

static void dos_mode_debug_print(const char *function, uint32_t dosmode)
{
    (void)function;
    (void)dosmode;
}

/* Insert the unmodified function extracted from Samba at this point. */
/* DOS_MODE_FUNCTION */

struct test_case {
    const char *name;
    unsigned int type;
    uint32_t stored;
    uint32_t expected;
    bool named_stream;
    bool compressed;
};

int main(void)
{
    const struct test_case cases[] = {
        {"regular file with stale directory bit", S_IFREG, 0x10, 0x80, false, false},
        {"regular file retains archive", S_IFREG, 0x30, 0x20, false, false},
        {"regular file retains readonly hidden system", S_IFREG, 0x17, 0x07, false, false},
        {"regular file with no attributes", S_IFREG, 0, 0x80, false, false},
        {"normal file", S_IFREG, 0x80, 0x80, false, false},
        {"actual directory", S_IFDIR, 0, 0x10, false, false},
        {"actual directory retains archive", S_IFDIR, 0x20, 0x30, false, false},
        {"named stream", S_IFREG, 0x30, 0x20, true, false},
        {"regular reparse sparse file", S_IFREG, 0x610, 0x600, false, false},
        {"compressed regular file", S_IFREG, 0x10, 0x800, false, true},
    };
    unsigned int failures = 0;
    for (unsigned int i = 0; i < sizeof(cases) / sizeof(cases[0]); i++) {
        const struct test_case *test = &cases[i];
        struct smb_filename name = {
            .st = { .st_ex_mode = test->type },
            .base_name = test->named_stream ? ":stream" : "sample.pptx",
        };
        struct connection_struct conn = { .fs_capabilities = FILE_FILE_COMPRESSION };
        struct files_struct fsp = {
            .fsp_name = &name,
            .conn = &conn,
            .compressed = test->compressed,
        };
        uint32_t actual = dos_mode_post(test->stored, &fsp, "host-test");
        if (actual != test->expected) {
            fprintf(stderr, "%s: got 0x%x, expected 0x%x\n",
                    test->name, actual, test->expected);
            failures++;
        }
    }
    printf("%u cases, %u failures\n",
           (unsigned int)(sizeof(cases) / sizeof(cases[0])), failures);
    return failures ? 1 : 0;
}
