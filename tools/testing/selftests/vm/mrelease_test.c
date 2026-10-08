// SPDX-License-Identifier: GPL-2.0
/* Copyright 2022 Google LLC. Adapted from Linux v6.6 mm/mrelease_test.c. */
#define _GNU_SOURCE
#include <errno.h>
#include <stdbool.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/mman.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <unistd.h>
#include "../kselftest.h"

#ifndef __NR_process_mrelease
#define __NR_process_mrelease 448
#endif
#ifndef __NR_pidfd_open
#define __NR_pidfd_open 434
#endif
#define MB(x) ((x) << 20)
#define MAX_SIZE_MB 64

static long psize(void)
{
	return sysconf(_SC_PAGESIZE);
}

static int alloc_noexit(unsigned long nr_pages, int pipefd)
{
	int ppid = getppid(), timeout = 10;
	unsigned long i;
	char *buf = mmap(NULL, nr_pages * psize(), PROT_READ | PROT_WRITE,
			 MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);

	if (buf == MAP_FAILED) {
		perror("mmap");
		return KSFT_FAIL;
	}
	for (i = 0; i < nr_pages; i++)
		*((unsigned long *)(buf + i * psize())) = i;
	if (write(pipefd, "", 1) != 1) {
		perror("write");
		munmap(buf, nr_pages * psize());
		return KSFT_FAIL;
	}
	while (getppid() == ppid && timeout > 0) {
		sleep(1);
		timeout--;
	}
	munmap(buf, nr_pages * psize());
	return timeout > 0 ? KSFT_PASS : KSFT_FAIL;
}

static int run_negative_tests(int pidfd)
{
	if (syscall(__NR_process_mrelease, pidfd, (unsigned int)-1) != -1 ||
	    errno != EINVAL) {
		int res = errno == ENOSYS ? KSFT_SKIP : KSFT_FAIL;

		perror("process_mrelease with wrong flags");
		return res;
	}
	if (syscall(__NR_process_mrelease, pidfd, 0) != -1 || errno != EINVAL) {
		int res = errno == ENOSYS ? KSFT_SKIP : KSFT_FAIL;

		perror("process_mrelease on a live process");
		return res;
	}
	return KSFT_PASS;
}

int main(void)
{
	size_t size = 1;

	if (syscall(__NR_process_mrelease, -1, 0) != -1 || errno != EBADF) {
		int res = errno == ENOSYS ? KSFT_SKIP : KSFT_FAIL;

		perror("process_mrelease with wrong pidfd");
		return res;
	}
	if (psize() <= 0)
		return KSFT_FAIL;
	for (;;) {
		int pipefd[2], pidfd = -1, res = KSFT_FAIL;
		bool success = false, retry = false;
		pid_t pid;
		char byte;
		ssize_t n;

		if (pipe(pipefd)) {
			perror("pipe");
			return KSFT_FAIL;
		}
		pid = fork();
		if (pid < 0) {
			perror("fork");
			close(pipefd[0]);
			close(pipefd[1]);
			return KSFT_FAIL;
		}
		if (!pid) {
			close(pipefd[0]);
			res = alloc_noexit(MB(size) / psize(), pipefd[1]);
			close(pipefd[1]);
			_exit(res);
		}
		close(pipefd[1]);
		do {
			n = read(pipefd[0], &byte, 1);
		} while (n < 0 && errno == EINTR);
		close(pipefd[0]);
		if (n != 1) {
			perror("child readiness");
			goto cleanup;
		}
		pidfd = syscall(__NR_pidfd_open, pid, 0);
		if (pidfd < 0) {
			res = errno == ENOSYS ? KSFT_SKIP : KSFT_FAIL;
			perror("pidfd_open");
			goto cleanup;
		}
		res = run_negative_tests(pidfd);
		if (res != KSFT_PASS)
			goto cleanup;
		res = KSFT_FAIL;
		if (kill(pid, SIGKILL)) {
			perror("kill");
			goto cleanup;
		}
		success = syscall(__NR_process_mrelease, pidfd, 0) == 0;
		if (success)
			res = KSFT_PASS;
		else if (errno == ESRCH)
			retry = size < MAX_SIZE_MB;
		else {
			res = errno == ENOSYS ? KSFT_SKIP : KSFT_FAIL;
			perror("process_mrelease");
		}
cleanup:
		/* All parent paths after fork terminate and reap the owned child. */
		kill(pid, SIGKILL);
		do {
			n = waitpid(pid, NULL, 0);
		} while (n < 0 && errno == EINTR);
		if (n < 0) {
			perror("waitpid");
			res = KSFT_FAIL;
			retry = false;
		}
		if (pidfd >= 0)
			close(pidfd);
		if (retry) {
			size *= 2;
			continue;
		}
		if (success && res == KSFT_PASS)
			printf("Success reaping a child with %zuMB of memory allocations\n", size);
		else if (res == KSFT_FAIL)
			printf("All process_mrelease attempts failed!\n");
		return res;
	}
}
