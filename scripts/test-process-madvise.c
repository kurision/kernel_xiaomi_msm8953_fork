// SPDX-License-Identifier: GPL-2.0
/*
 * On-device check for the process_madvise(MADV_COLD/MADV_PAGEOUT) backport.
 *
 * Build: $NDK/toolchains/llvm/prebuilt/<host>/bin/aarch64-linux-android29-clang \
 *            -O2 -static -o test-process-madvise scripts/test-process-madvise.c
 * Run as root (needs CAP_SYS_NICE): adb push it to /data/local/tmp and run.
 */
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/syscall.h>
#include <sys/uio.h>
#include <unistd.h>

#ifndef MADV_COLD
#define MADV_COLD 20
#endif
#ifndef MADV_PAGEOUT
#define MADV_PAGEOUT 21
#endif
#define NR_pidfd_open 434
#define NR_process_madvise 440

static long rss_anon_kb(void)
{
	char line[128];
	long kb = -1;
	FILE *f = fopen("/proc/self/status", "r");

	while (f && fgets(line, sizeof(line), f))
		if (sscanf(line, "RssAnon: %ld", &kb) == 1)
			break;
	if (f)
		fclose(f);
	return kb;
}

static long pmadvise(int pidfd, void *addr, size_t len, int advice, unsigned int flags)
{
	struct iovec iov = { .iov_base = addr, .iov_len = len };

	return syscall(NR_process_madvise, pidfd, &iov, 1, advice, flags);
}

#define CHECK(cond, ...) do { if (!(cond)) { printf("FAIL: " __VA_ARGS__); puts(""); return 1; } } while (0)

int main(void)
{
	const size_t len = 64 << 20;
	int pidfd = syscall(NR_pidfd_open, getpid(), 0);
	char *buf;
	long before, after, ret;

	CHECK(pidfd >= 0, "pidfd_open: %s", strerror(errno));
	buf = mmap(NULL, len, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
	CHECK(buf != MAP_FAILED, "mmap: %s", strerror(errno));
	for (size_t i = 0; i < len; i += 4096)
		buf[i] = (char)i | 1;	/* non-zero so zram cannot drop the page as same-filled */

	CHECK(pmadvise(pidfd, buf, len, MADV_PAGEOUT, 1) == -1 && errno == EINVAL, "flags != 0 must be EINVAL");
	CHECK(pmadvise(pidfd, buf, len, MADV_DONTNEED, 0) == -1 && errno == EINVAL, "MADV_DONTNEED must be EINVAL");

	ret = pmadvise(pidfd, buf, len, MADV_COLD, 0);
	CHECK(ret == (long)len, "MADV_COLD returned %ld (%s)", ret, strerror(errno));
	CHECK(madvise(buf, len, MADV_COLD) == 0, "madvise(MADV_COLD): %s", strerror(errno));

	before = rss_anon_kb();
	ret = pmadvise(pidfd, buf, len, MADV_PAGEOUT, 0);
	after = rss_anon_kb();
	CHECK(ret == (long)len, "MADV_PAGEOUT returned %ld (%s)", ret, strerror(errno));
	printf("RssAnon %ld kB -> %ld kB\n", before, after);
	CHECK(before - after >= 48 << 10, "MADV_PAGEOUT reclaimed under 48 MB of 64 MB");

	for (size_t i = 0; i < len; i += 4096)
		CHECK(buf[i] == ((char)i | 1), "data corrupted at %zu after swap-in", i);

	puts("PASS: process_madvise MADV_COLD/MADV_PAGEOUT, flag/behavior checks, data intact");
	return 0;
}
