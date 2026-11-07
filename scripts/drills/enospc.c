/* Fault injection: return ENOSPC once the target file has taken ENOSPC_AFTER
 * bytes. Only writes to a file whose path contains ENOSPC_TARGET are affected,
 * so logging and the rest of the process keep working.
 *
 * Why a shim: a container refuses mount(2) and has no loop devices, so a device
 * cannot literally be filled. The storage engine sees the same errno the kernel
 * returns on a full filesystem, which is the condition under test.
 *
 * Build:  gcc -shared -fPIC -O2 -o enospc.so enospc.c -ldl
 * Use:    ENOSPC_AFTER=72000 ENOSPC_TARGET=audit.sqlite LD_PRELOAD=./enospc.so \
 *           python3 scripts/drills/phase9_disk_full.py
 *
 * write, pwrite, pwrite64 and writev are all intercepted. Intercepting only
 * write was the first version and it never tripped, because SQLite issues
 * positional writes; the injection has to reach the call the engine makes, not
 * the one the caller makes.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/uio.h>

static ssize_t (*real_write)(int, const void *, size_t);
static ssize_t (*real_pwrite)(int, const void *, size_t, off_t);
static ssize_t (*real_pwrite64)(int, const void *, size_t, off64_t);
static ssize_t (*real_writev)(int, const struct iovec *, int);
static unsigned long long written = 0, limit = 0;
static const char *target = NULL;
static int tripped = 0;

static void init(void) {
    if (real_write) return;
    real_write    = dlsym(RTLD_NEXT, "write");
    real_pwrite   = dlsym(RTLD_NEXT, "pwrite");
    real_pwrite64 = dlsym(RTLD_NEXT, "pwrite64");
    real_writev   = dlsym(RTLD_NEXT, "writev");
    const char *l = getenv("ENOSPC_AFTER");
    const char *t = getenv("ENOSPC_TARGET");
    limit = l ? strtoull(l, NULL, 10) : 0;
    target = t ? t : NULL;
    if (limit) fprintf(stderr, "[enospc] armed: %llu bytes, target=%s\n", limit, target ? target : "(all)");
}

static int is_target(int fd) {
    if (!target) return 1;
    char link[64], path[512];
    snprintf(link, sizeof link, "/proc/self/fd/%d", fd);
    ssize_t n = readlink(link, path, sizeof path - 1);
    if (n <= 0) return 0;
    path[n] = 0;
    return strstr(path, target) != NULL;
}

static int full(int fd, size_t count) {
    init();
    if (!limit || !is_target(fd)) return 0;
    if (written + count > limit) {
        if (!tripped) {
            tripped = 1;
            fprintf(stderr, "[enospc] refusing a %zu byte write: %llu+%zu > %llu\n",
                    count, written, count, limit);
        }
        errno = ENOSPC;
        return 1;
    }
    written += count;
    return 0;
}

ssize_t write(int fd, const void *buf, size_t count) {
    if (full(fd, count)) return -1;
    return real_write(fd, buf, count);
}

ssize_t pwrite(int fd, const void *buf, size_t count, off_t off) {
    if (full(fd, count)) return -1;
    return real_pwrite(fd, buf, count, off);
}

ssize_t pwrite64(int fd, const void *buf, size_t count, off64_t off) {
    if (full(fd, count)) return -1;
    return real_pwrite64(fd, buf, count, off);
}

ssize_t writev(int fd, const struct iovec *iov, int iovcnt) {
    size_t total = 0;
    for (int i = 0; i < iovcnt; i++) total += iov[i].iov_len;
    if (full(fd, total)) return -1;
    return real_writev(fd, iov, iovcnt);
}
