#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Check that MGLRU generation and reference bits survive page migration.

Fails without folio_migrate_refs(): a migrated page silently loses its
LRU_REFS_MASK field even though the rest of its flags were copied.
"""
from pathlib import Path
import resource
import subprocess
import tempfile

repo = Path(__file__).resolve().parent.parent
bitops = (repo / 'include/linux/bitops.h').read_text()


def function(signature, path='include/linux/mm_inline.h'):
    text = (repo / path).read_text()
    start = text.index(signature)
    return text[start:text.index('\n}', start) + 2]


code = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>

#define BIT(n) (1UL << (n))
#define LRU_REFS_WIDTH 2
#define LRU_REFS_PGOFF 8
#define LRU_REFS_MASK ((BIT(LRU_REFS_WIDTH) - 1) << LRU_REFS_PGOFF)
#define LRU_GEN_WIDTH 3
#define LRU_GEN_PGOFF 11
#define LRU_GEN_MASK ((BIT(LRU_GEN_WIDTH) - 1) << LRU_GEN_PGOFF)
#define LRU_REFS_FLAGS (LRU_REFS_MASK | BIT(PG_referenced))
#define PG_referenced 0
#define PG_active 1
#define READ_ONCE(x) (x)
#define WRITE_ONCE(x, v) ((x) = (v))
struct page { unsigned long flags; };

static unsigned long cmpxchg(unsigned long *ptr, unsigned long old, unsigned long new)
{
    unsigned long observed = *ptr;
    if (observed == old)
        *ptr = new;
    return observed;
}


/*
 * The tree's own migrate_page_states() equivalent: every flag except the
 * MGLRU refcount field is copied, exactly as in mm/migrate.c.
 */
static void migrate_flags(struct page *newpage, struct page *page)
{
    unsigned long keep = ~(LRU_REFS_MASK | BIT(PG_active));

    WRITE_ONCE(newpage->flags, READ_ONCE(page->flags) & keep);
    if (READ_ONCE(page->flags) & BIT(PG_active)) {
        WRITE_ONCE(newpage->flags, READ_ONCE(newpage->flags) | BIT(PG_active));
        WRITE_ONCE(page->flags, READ_ONCE(page->flags) & ~BIT(PG_active));
    }
}
'''
start = bitops.index('#define set_mask_bits(')
code += '\n' + bitops[start:bitops.index('\n#endif', start)] + '\n'
code += '\n' + function('static inline void folio_migrate_refs(')
code += r'''
static unsigned long migrate_page_flags(struct page *dst, struct page *src)
{
    migrate_flags(dst, src);
    folio_migrate_refs(dst, src);
    return READ_ONCE(dst->flags);
}

int main(void)
{
    struct page src, dst;

    /* A tracked page keeps both its generation and its reference bits. */
    src.flags = (3UL << LRU_REFS_PGOFF) | BIT(PG_referenced) | BIT(PG_active) |
                (2UL << LRU_GEN_PGOFF);
    dst.flags = 0;
    unsigned long flags = migrate_page_flags(&dst, &src);
    assert((flags & LRU_REFS_MASK) == (3UL << LRU_REFS_PGOFF));
    assert((flags & LRU_GEN_MASK) == (2UL << LRU_GEN_PGOFF));
    assert((flags & BIT(PG_referenced)) != 0);
    /* PG_active is test-and-cleared on the source and set on the destination. */
    assert((READ_ONCE(src.flags) & BIT(PG_active)) == 0);
    assert((READ_ONCE(dst.flags) & BIT(PG_active)) != 0);

    /* An untracked page is left alone. */
    src.flags = 0;
    dst.flags = 0;
    flags = migrate_page_flags(&dst, &src);
    assert(flags == 0 && dst.flags == 0);

    /* A page whose refs saturate keep every bit. */
    src.flags = BIT(PG_referenced) | LRU_REFS_MASK;
    dst.flags = 0;
    flags = migrate_page_flags(&dst, &src);
    assert(flags == (BIT(PG_referenced) | LRU_REFS_MASK));

    puts("PASS: MGLRU generation and reference bits survive page migration");
}
'''

resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
with tempfile.TemporaryDirectory(prefix='mglru-migrate-refs-') as directory:
    source = Path(directory) / 'check.c'
    binary = Path(directory) / 'check'
    source.write_text(code)
    subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror', '-O2',
                    str(source), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)