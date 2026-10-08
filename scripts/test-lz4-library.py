#!/usr/bin/env python3
"""Compile and exercise this tree's complete LZ4 codecs (host-only, not kernel proof)."""
from pathlib import Path
import os
import shlex
import shutil
import subprocess
import tempfile

repo = Path(__file__).resolve().parent.parent
code = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <linux/lz4.h>

static uint32_t step(uint32_t *state)
{
    *state ^= *state << 13;
    *state ^= *state >> 17;
    *state ^= *state << 5;
    return *state;
}
static void fixture(char *buf, int n, int pattern)
{
    uint32_t state = 1;
    const char text[] = "kernel LZ4 caller owned workspace dictionary ";
    for (int i = 0; i < n; i++)
        buf[i] = pattern ? text[i % (sizeof(text) - 1)] : (char)step(&state);
}
static void roundtrip(void *fast, void *hc, int n, int pattern)
{
    int bound = LZ4_compressBound(n);
    char *src = malloc(n ? (size_t)n : 1);
    char *dst = malloc(bound);
    char *out = malloc(n ? (size_t)n : 1);
    assert(src && dst && out);
    fixture(src, n, pattern);
    for (int codec = 0; codec < 4; codec++) {
        int level = codec == 1 ? 9 : codec == 2 ? 10 : 12;
        int len = codec ? LZ4_compress_HC(src, dst, n, bound, level, hc) :
                          LZ4_compress_default(src, dst, n, bound, fast);
        assert(len > 0 && len <= bound);
        assert(LZ4_decompress_safe(dst, out, len, n) == n);
        assert(memcmp(src, out, n) == 0);
    }
    free(out); free(dst); free(src);
}
static void streaming(void *fast, void *hc)
{
    const int n = 32768, bound = LZ4_compressBound(n);
    char *src = malloc(2 * n), *packed = malloc(2 * bound), *out = malloc(2 * n);
    LZ4_streamDecode_t *decoder = calloc(1, sizeof(*decoder));
    assert(src && packed && out && decoder);
    fixture(src, n, 1);
    memcpy(src + n, src, n);
    for (int codec = 0; codec < 2; codec++) {
        if (codec) LZ4_resetStreamHC(hc, 12); else LZ4_resetStream(fast);
        assert(LZ4_setStreamDecode(decoder, NULL, 0) == 1);
        for (int block = 0; block < 2; block++) {
            int len = codec ?
                LZ4_compress_HC_continue(hc, src + block * n, packed + block * bound, n, bound) :
                LZ4_compress_fast_continue(fast, src + block * n, packed + block * bound, n, bound, 1);
            assert(len > 0);
            assert(LZ4_decompress_safe_continue(decoder, packed + block * bound,
                                              out + block * n, len, n) == n);
            assert(memcmp(src + block * n, out + block * n, n) == 0);
        }
    }
    free(decoder); free(out); free(packed); free(src);
}
static void boundaries(void *fast)
{
    const char valid[] = {0x30, 'a', 'b', 'c'};
    const char truncated[] = {0x30, 'a', 'b'};
    char *tiny = malloc(3);
    char *src = malloc(4096), *dst = malloc(LZ4_compressBound(4096));
    char *partial = malloc(47), *one = malloc(1);
    assert(tiny && src && dst && partial && one);
    assert(LZ4_decompress_safe(valid, tiny, sizeof(valid), 3) == 3);
    assert(memcmp(tiny, "abc", 3) == 0);
    assert(LZ4_decompress_safe(truncated, tiny, sizeof(truncated), 3) < 0);
    fixture(src, 4096, 1);
    int len = LZ4_compress_default(src, dst, 4096, LZ4_compressBound(4096), fast);
    assert(len > 0 && len < 4096);
    assert(LZ4_decompress_safe_partial(dst, partial, len, 47, 47) == 47);
    assert(memcmp(src, partial, 47) == 0);
    size_t inplace_size = LZ4_DECOMPRESS_INPLACE_BUFFER_SIZE(4096);
    char *inplace = malloc(inplace_size);
    assert(inplace);
    memcpy(inplace + inplace_size - len, dst, len);
    assert(LZ4_decompress_safe(inplace + inplace_size - len, inplace, len, 4096) == 4096);
    assert(memcmp(src, inplace, 4096) == 0);
    assert(LZ4_compress_default(src, one, 4096, 1, fast) == 0);
    free(inplace); free(one); free(partial); free(dst); free(src); free(tiny);
}
int main(void)
{
    const int lengths[] = {0, 1, 4, 15, 16, 4096, 65536, 65537};
    void *fast = malloc(LZ4_MEM_COMPRESS), *hc = malloc(LZ4HC_MEM_COMPRESS);
    assert(fast && hc);
    for (size_t i = 0; i < sizeof(lengths) / sizeof(lengths[0]); i++)
        for (int pattern = 0; pattern < 2; pattern++)
            roundtrip(fast, hc, lengths[i], pattern);
    streaming(fast, hc);
    boundaries(fast);
    free(hc); free(fast);
    puts("PASS: exact byte roundtrips, HC9/10/12 workspace reuse, streaming dictionaries, bounded/partial/in-place decode and compression failure");
    return 0;
}
'''
shims = {
    'linux/types.h': '''#pragma once
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
typedef uint8_t u8; typedef int8_t s8;
typedef uint16_t u16; typedef uint32_t u32; typedef int32_t s32; typedef uint64_t u64;
''',
    'linux/string.h': '#pragma once\n#include <string.h>\n',
    'linux/limits.h': '#pragma once\n#include <limits.h>\n',
    'linux/kernel.h': '''#pragma once
#include <stddef.h>
#include <stdint.h>
#define likely(x) __builtin_expect(!!(x), 1)
#define unlikely(x) __builtin_expect(!!(x), 0)
#define __maybe_unused __attribute__((unused))
#define BUILD_BUG_ON(x) _Static_assert(!(x), "BUILD_BUG_ON")
''',
    'linux/module.h': '''#pragma once
#define EXPORT_SYMBOL(x)
#define MODULE_LICENSE(x)
#define MODULE_DESCRIPTION(x)
''',
    'asm/unaligned.h': '''#pragma once
#include <stdint.h>
#include <string.h>
static inline uint16_t get_unaligned_le16(const void *p) {
    const uint8_t *s = p; return (uint16_t)(s[0] | (uint16_t)s[1] << 8);
}
static inline void put_unaligned_le16(uint16_t v, void *p) {
    uint8_t *d = p; d[0] = v; d[1] = v >> 8;
}
#define get_unaligned(p) ({ union { __typeof__(*(p)) value; unsigned char raw[sizeof(*(p))]; } u; memcpy(u.raw, (p), sizeof(u.raw)); u.value; })
#define put_unaligned(v,p) do { __typeof__(*(p)) value = (v); memcpy((p), &value, sizeof(value)); } while (0)
''',
}
cc = shlex.split(os.environ.get('CC', 'cc'))
if not cc or shutil.which(cc[0]) is None:
    raise SystemExit('PREREQUISITE FAILURE: CC compiler is unavailable')
with tempfile.TemporaryDirectory(prefix='lz4-library-') as directory:
    tmp = Path(directory)
    for name, content in shims.items():
        path = tmp / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    source = tmp / 'check.c'
    binary = tmp / 'check'
    source.write_text(code)
    try:
        subprocess.run(cc + ['-std=gnu11', '-O2', '-g', '-fsanitize=address,undefined',
                            '-fno-sanitize-recover=all', '-fno-omit-frame-pointer',
                            '-Wframe-larger-than=2048', '-Werror=frame-larger-than',
                            '-I' + str(tmp), '-I' + str(repo / 'include'),
                            str(source)] + [str(repo / 'lib/lz4' / name) for name in
                            ('lz4_compress.c', 'lz4_decompress.c', 'lz4hc_compress.c')] +
                            ['-o', str(binary)], check=True)
    except subprocess.CalledProcessError as error:
        raise SystemExit('Compile gate failed: compiler/sanitizer support is required; codec compile errors are failures') from error
    subprocess.run([str(binary)], check=True)
