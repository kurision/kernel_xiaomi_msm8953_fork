#!/bin/sh
""":"
command -v python3 >/dev/null 2>&1 || { echo 'SKIP: Python 3 is required'; exit 4; }
exec python3 "$0" "$@"
":"""
# SPDX-License-Identifier: GPL-2.0
"""Destructive only to a new hot-added device; never touches an existing zram."""
import errno
import fcntl
import mmap
import os
from pathlib import Path
import struct
import sys
import time

KSFT_SKIP = 4
PAGE = 4096
BLKDISCARD = 0x1277
CONTROL = Path('/sys/class/zram-control')


class Skip(Exception):
    pass


def report(message):
    print('PASS: ' + message, flush=True)


def fixture(size, seed):
    result = bytearray(size)
    state = seed
    for i in range(size):
        state ^= (state << 13) & 0xffffffff
        state ^= state >> 17
        state ^= (state << 5) & 0xffffffff
        state &= 0xffffffff
        result[i] = state & 15
    return bytes(result)


def write_attr(base, name, value):
    with (base / name).open('w') as stream:
        stream.write(value + '\n')


def expect_errno(base, name, value, expected):
    try:
        write_attr(base, name, value)
    except OSError as error:
        if error.errno != expected:
            raise AssertionError(f'{name} {value!r}: errno {error.errno}, expected {expected}') from error
        report(f'{name} {value!r} rejects with {errno.errorcode[expected]}')
    else:
        raise AssertionError(f'{name} {value!r}: unexpected success')


def raw_write(fd, data, offset=0):
    assert offset % PAGE == 0 and len(data) % PAGE == 0
    with mmap.mmap(-1, len(data)) as aligned:
        aligned[:] = data
        count = os.pwritev(fd, [aligned], offset)
        if count != len(data):
            raise AssertionError(f'short raw write: {count}/{len(data)}')


def raw_read(fd, length, offset=0):
    assert offset % PAGE == 0 and length % PAGE == 0
    with mmap.mmap(-1, length) as aligned:
        count = os.preadv(fd, [aligned], offset)
        if count != length:
            raise AssertionError(f'short raw read: {count}/{length}')
        return aligned[:]


def stats(base):
    fields = [int(x) for x in (base / 'mm_stat').read_text().split()]
    return fields[0], fields[1]


def configure(base, primary, secondary=False):
    write_attr(base, 'comp_algorithm', primary)
    if secondary:
        write_attr(base, 'recomp_algorithm', 'algo=zstd priority=1')
    write_attr(base, 'disksize', str(16 << 20))


def open_device(node):
    return os.open(node, os.O_RDWR | os.O_DIRECT | os.O_CLOEXEC)


def assert_equal(actual, expected, message):
    if actual != expected:
        raise AssertionError(message + ': data mismatch')
    report(message)


def run():
    if sys.version_info.major != 3:
        raise Skip('Python 3 is required')
    if os.geteuid() != 0:
        raise Skip('root is required')
    if not (CONTROL / 'hot_add').exists():
        raise Skip('zram hot-add is unavailable')
    index = None
    fd = None
    base = None
    try:
        index = int((CONTROL / 'hot_add').read_text().strip())
        base = Path(f'/sys/block/zram{index}')
        for _ in range(50):
            if base.exists():
                break
            time.sleep(0.1)
        if not (base / 'recomp_algorithm').exists() or not (base / 'recompress').exists():
            raise Skip('secondary compression is not compiled')
        algorithms = (base / 'comp_algorithm').read_text().replace('[', '').replace(']', '').split()
        if 'lz4' not in algorithms or 'zstd' not in algorithms:
            raise Skip('LZ4 and zstd compression algorithms are required')
        node = None
        for _ in range(50):
            node = next((p for p in (Path(f'/dev/zram{index}'), Path(f'/dev/block/zram{index}')) if p.exists()), None)
            if node is not None:
                break
            time.sleep(0.1)
        if node is None:
            raise AssertionError('new hot-added device node was not published')
        expect_errno(base, 'recomp_algorithm', 'algo=zstd priority=0', errno.EINVAL)
        expect_errno(base, 'recomp_algorithm', 'priority=1', errno.EINVAL)
        expect_errno(base, 'recomp_algorithm', 'algo', errno.EINVAL)
        expect_errno(base, 'recompress', 'algo', errno.EINVAL)
        configure(base, 'lz4', True)
        expect_errno(base, 'comp_algorithm', 'zstd', errno.EBUSY)
        expect_errno(base, 'recomp_algorithm', 'algo=zstd priority=1', errno.EBUSY)
        data = fixture(4 << 20, 1)
        fd = open_device(node)
        raw_write(fd, data)
        assert_equal(raw_read(fd, len(data)), data, 'full LZ4 readback before recompression')
        before = stats(base)
        write_attr(base, 'idle', 'all')
        write_attr(base, 'recompress', 'type=idle algo=zstd')
        after = stats(base)
        if after[0] != before[0] or not after[1] < before[1]:
            raise AssertionError(f'recompression accounting/storage reduction: {before} -> {after}')
        report('unchanged original-data size and lower compressed-data size')
        assert_equal(raw_read(fd, len(data)), data, 'secondary zstd full readback')
        mixed = bytearray(data)
        mixed[:65536] = fixture(65536, 2)
        raw_write(fd, mixed[:65536])
        assert_equal(raw_read(fd, len(mixed)), mixed, 'overwrite secondary slots with primary encoding')
        fcntl.ioctl(fd, BLKDISCARD, struct.pack('QQ', 65536, 65536))
        mixed[65536:131072] = bytes(65536)
        assert_equal(raw_read(fd, len(mixed)), mixed, 'discard clears secondary slots, other bytes unchanged')
        os.close(fd)
        fd = None
        write_attr(base, 'reset', '1')
        configure(base, 'zstd')
        fd = open_device(node)
        raw_write(fd, data)
        assert_equal(raw_read(fd, len(data)), data, 'zstd primary-only crypto integration')
        os.close(fd)
        fd = None
        write_attr(base, 'reset', '1')
        dedup = base / 'use_dedup'
        # CONFIG_ZRAM_DEDUP=n retains a read-only use_dedup ABI.
        # A writable attribute must still fail the test if its store fails.
        if dedup.exists() and dedup.stat().st_mode & 0o222:
            write_attr(base, 'use_dedup', '1')
            configure(base, 'lz4', True)
            fd = open_device(node)
            shared = fixture(PAGE, 1)
            raw_write(fd, shared * 2)
            write_attr(base, 'idle', 'all')
            assert_equal(raw_read(fd, PAGE), shared, 'activate only the first shared slot')
            before = stats(base)
            write_attr(base, 'recompress', 'type=idle algo=zstd')
            after = stats(base)
            if after[0] != before[0] or not after[1] < before[1]:
                raise AssertionError(f'shared-entry recompression did not reduce storage: {before} -> {after}')
            report('idle shared slot actually changes encoding without changing original-data accounting')
            assert_equal(raw_read(fd, 2 * PAGE), shared * 2, 'shared primary and secondary entries remain immutable')
            raw_write(fd, shared, 2 * PAGE)
            assert_equal(raw_read(fd, 3 * PAGE), shared * 3, 'new duplicate inherits its stored entry priority')
            os.close(fd)
            fd = None
            write_attr(base, 'reset', '1')
        else:
            print('SKIP variant: dedup is not compiled', flush=True)
        configure(base, 'lz4')
        fd = open_device(node)
        raw_write(fd, data)
        assert_equal(raw_read(fd, len(data)), data, 'reset/reconfigure compressor and name lifecycle')
    finally:
        if fd is not None:
            os.close(fd)
        if index is not None:
            try:
                if base is not None and (base / 'reset').exists():
                    write_attr(base, 'reset', '1')
            finally:
                write_attr(CONTROL, 'hot_remove', str(index))


if __name__ == '__main__':
    try:
        run()
    except Skip as error:
        print('SKIP: ' + str(error), flush=True)
        sys.exit(KSFT_SKIP)
    except (OSError, AssertionError, ValueError) as error:
        print('FAIL: ' + str(error), file=sys.stderr, flush=True)
        sys.exit(1)
