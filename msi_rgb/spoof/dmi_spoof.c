/* dmi_spoof.c -- LD_PRELOAD shim
 *
 * OpenRGB's MSI motherboard drivers identify the board by an *exact* string
 * match against "MSI " + the DMI board_name. Boards missing from its compiled-in
 * table are skipped, with only this in the log:
 *
 *     Found Board <your board> but does not have valid config
 *
 * This shim rewrites *only what the preloaded process sees* when it opens
 * board_name. The system DMI table, the BIOS, and every other program are
 * untouched. Remove LD_PRELOAD to revert -- completely.
 *
 * The replacement board name comes from the environment, so one build of this
 * library works for any board:
 *
 *     MSI_SPOOF_BOARD_NAME="MAG Z890 TOMAHAWK WIFI (MS-7E32)" \
 *         LD_PRELOAD=./dmi_spoof.so openrgb --server
 *
 * Note the value must be the *board_name* only. OpenRGB prepends "MSI ".
 *
 * Build:  gcc -shared -fPIC -O2 -o dmi_spoof.so dmi_spoof.c -ldl
 */

#define _GNU_SOURCE
#include <dlfcn.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>

/* Used only when MSI_SPOOF_BOARD_NAME is unset. */
#ifndef SPOOFED_BOARD_NAME
#define SPOOFED_BOARD_NAME ""
#endif

static char redirect_path[256];
static char redirect_body[256];
static int prepared;

static void ensure_redirect(void)
{
    const char *env = getenv("MSI_SPOOF_BOARD_NAME");
    const char *body = (env && *env) ? env : SPOOFED_BOARD_NAME;
    size_t len;
    long fd;

    if (prepared)
        return;
    prepared = 1;

    if (!*body)
        return;                     /* nothing to do; pass everything through */

    len = strlen(body);
    if (len + 2 > sizeof(redirect_body))
        len = sizeof(redirect_body) - 2;
    memcpy(redirect_body, body, len);
    redirect_body[len] = '\n';
    redirect_body[len + 1] = '\0';
    body = redirect_body;

    /* Raw syscalls only -- calling fopen/open here would recurse. */
    snprintf(redirect_path, sizeof(redirect_path), "/tmp/.dmi_board_name.%d",
             (int)getpid());

    fd = syscall(SYS_open, redirect_path, O_WRONLY | O_CREAT | O_TRUNC, 0600);
    if (fd < 0) {
        redirect_path[0] = '\0';
        return;
    }
    if (write((int)fd, body, len + 1) != (ssize_t)(len + 1))
        redirect_path[0] = '\0';
    close((int)fd);
}

/* OpenRGB 1.0rc3 opens "/sys/devices/virtual/dmi/id//board_name"; other builds
 * use "/sys/class/dmi/id/board_name". Match either: the path must contain the
 * DMI id directory and end in "board_name". */
static int is_target(const char *path)
{
    const char *name;
    size_t plen;

    if (!path)
        return 0;

    plen = strlen(path);
    if (plen < 10 || strcmp(path + plen - 10, "board_name") != 0)
        return 0;

    /* Require the DMI id directory somewhere in the path. */
    for (name = path; (name = strstr(name, "dmi/id")) != NULL; name += 6) {
        if (name == path || name[-1] == '/')
            return 1;
    }
    return 0;
}

/* ------------------------------------------------------------------ */

FILE *fopen(const char *path, const char *mode)
{
    static FILE *(*real)(const char *, const char *);
    if (!real)
        real = dlsym(RTLD_NEXT, "fopen");
    if (is_target(path)) {
        ensure_redirect();
        if (redirect_path[0])
            return real(redirect_path, mode);
    }
    return real(path, mode);
}

FILE *fopen64(const char *path, const char *mode)
{
    static FILE *(*real)(const char *, const char *);
    if (!real)
        real = dlsym(RTLD_NEXT, "fopen64");
    if (!real)
        real = dlsym(RTLD_NEXT, "fopen");
    if (is_target(path)) {
        ensure_redirect();
        if (redirect_path[0])
            return real(redirect_path, mode);
    }
    return real(path, mode);
}

static mode_t mode_of(int flags)
{
    /* open()/openat() take an optional mode_t only when O_CREAT is set. */
    return (flags & O_CREAT) ? 0600 : 0;
}

int open(const char *path, int flags, ...)
{
    static int (*real)(const char *, int, ...);
    mode_t mode = 0;

    if (flags & O_CREAT) {
        va_list ap;
        va_start(ap, flags);
        mode = va_arg(ap, int);
        va_end(ap);
    }
    if (!real)
        real = dlsym(RTLD_NEXT, "open");
    if (is_target(path)) {
        ensure_redirect();
        if (redirect_path[0])
            return real(redirect_path, flags & ~O_CREAT, mode);
    }
    return real(path, flags, mode_of(flags), mode);
}

int open64(const char *path, int flags, ...)
{
    static int (*real)(const char *, int, ...);
    mode_t mode = 0;

    if (flags & O_CREAT) {
        va_list ap;
        va_start(ap, flags);
        mode = va_arg(ap, int);
        va_end(ap);
    }
    if (!real)
        real = dlsym(RTLD_NEXT, "open64");
    if (!real)
        real = dlsym(RTLD_NEXT, "open");
    if (is_target(path)) {
        ensure_redirect();
        if (redirect_path[0])
            return real(redirect_path, flags & ~O_CREAT, mode);
    }
    return real(path, flags, mode_of(flags), mode);
}

int openat(int dirfd, const char *path, int flags, ...)
{
    static int (*real)(int, const char *, int, ...);
    mode_t mode = 0;

    if (flags & O_CREAT) {
        va_list ap;
        va_start(ap, flags);
        mode = va_arg(ap, int);
        va_end(ap);
    }
    if (!real)
        real = dlsym(RTLD_NEXT, "openat");
    if (is_target(path)) {
        ensure_redirect();
        if (redirect_path[0])
            return real(AT_FDCWD, redirect_path, flags & ~O_CREAT, mode);
    }
    return real(dirfd, path, flags, mode_of(flags), mode);
}