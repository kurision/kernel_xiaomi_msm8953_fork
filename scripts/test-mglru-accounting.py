#!/usr/bin/env python3
"""Run actual MGLRU accounting/removal functions with modeled kernel primitives."""
from pathlib import Path
import resource
import subprocess
import tempfile

repo = Path(__file__).resolve().parent.parent
source = (repo / 'include/linux/mm_inline.h').read_text()
bitops = (repo / 'include/linux/bitops.h').read_text()


def function(name):
    start = source.index('static inline ', source.rfind('\n}', 0, source.index(name + '(')))
    return source[start:source.index('\n}', start) + 2]


code = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#define BIT(n) (1UL << (n))
#define MAX_NR_GENS 4
#define MIN_NR_GENS 2
#define ANON_AND_FILE 2
#define LRU_GEN_PGOFF 8
#define LRU_GEN_MASK (7UL << LRU_GEN_PGOFF)
#define PG_active 0
#define PG_unevictable 1
#define PG_referenced 2
#define READ_ONCE(x) (*(volatile __typeof__(x) *)&(x))
#define WRITE_ONCE(x, value) (*(volatile __typeof__(x) *)&(x) = (value))
static int warnings;
#define max(a, b) ((a) > (b) ? (a) : (b))
#define VM_WARN_ON_ONCE(x) do { if (x) warnings++; } while (0)
#define VM_WARN_ON_ONCE_PAGE(x, page) VM_WARN_ON_ONCE(x)
enum lru_list { LRU_INACTIVE_ANON, LRU_ACTIVE_ANON,
                LRU_INACTIVE_FILE, LRU_ACTIVE_FILE };
#define LRU_ACTIVE 1
struct list_head { bool linked; };
struct page { unsigned long flags; int type, zone, count; struct list_head lru; };
struct lru_gen_folio {
    unsigned long max_seq;
    unsigned long min_seq[2];
    struct list_head folios[4][2][2];
    long nr_pages[4][2][2];
    bool enabled;
};
struct lruvec { struct lru_gen_folio lrugen; long node[4], zone[2][4]; };
#define PageActive(p) (!!((p)->flags & BIT(PG_active)))
#define PageUnevictable(p) (!!((p)->flags & BIT(PG_unevictable)))
#define PageDirty(p) 0
#define PageWriteback(p) 0
#define PageReclaim(p) 0
#define PageSwapCache(p) 0
#define PageWorkingset(p) 0
#define folio_test_workingset(p) PageWorkingset(p)
#define folio_test_swapcache(p) PageSwapCache(p)
#define folio_test_reclaim(p) PageReclaim(p)
#define folio_test_dirty(p) PageDirty(p)
#define folio_test_writeback(p) PageWriteback(p)
#define folio_test_active(p) PageActive(p)

#define folio_is_file_lru(p) ((p)->type)
#define page_zonenum(p) ((p)->zone)
#define folio_zonenum(p) ((p)->zone)
#define folio_nr_pages(p) ((p)->count)
static void list_add(struct list_head *list, struct list_head *head)
{
    assert(!list->linked && !head->linked);
    list->linked = true;
    head->linked = false;
}
static void list_add_tail(struct list_head *list, struct list_head *head)
{
    list_add(list, head);
}
static void list_del(struct list_head *list)
{
    assert(list->linked);
    list->linked = false;
}
static void __update_lru_size(struct lruvec *lv, enum lru_list lru, int zone, int n)
{
    lv->node[lru] += n;
    lv->zone[zone][lru] += n;
}
static bool inject_retry;
static int exchanges;
static struct page *racing_page;
static struct lruvec *racing_lruvec;
static void promote_during_exchange(void);
#define PageCompound(p) 0
#define folio_test_unevictable(p) PageUnevictable(p)
#define list_entry(head, type, member) ((type *)0)
static unsigned long cmpxchg(unsigned long *ptr, unsigned long old, unsigned long new)
{
    unsigned long observed;
    exchanges++;
    if (inject_retry) {
        inject_retry = false;
        promote_during_exchange();
    }
    observed = *ptr;
    if (observed == old)
        *ptr = new;
    return observed;
}
'''
# Preserve this tree's actual set_mask_bits return contract in the regression.
start = bitops.index('#define set_mask_bits(')
code += '\n' + bitops[start:bitops.index('\n#endif', start)] + '\n'
for name in ('lru_gen_try_cmpxchg', 'lru_gen_from_seq', 'folio_lru_gen',
             'lru_gen_is_active', 'lru_gen_update_size',
             'lru_gen_folio_seq', 'lru_gen_add_folio', 'lru_gen_del_folio'):
    code += '\n' + function(name) + '\n'
code += r'''
static void promote_during_exchange(void)
{
    /* Model a completed aging promotion before the first exchange succeeds. */
    int old_gen = folio_lru_gen(racing_page);
    racing_page->flags = (racing_page->flags & ~LRU_GEN_MASK) |
                        (3UL << LRU_GEN_PGOFF) | BIT(PG_referenced);
    lru_gen_update_size(racing_lruvec, racing_page, old_gen, 2);
}
static void assert_empty(struct lruvec *lv)
{
    for (int gen = 0; gen < 4; gen++)
        for (int type = 0; type < 2; type++)
            for (int zone = 0; zone < 2; zone++)
                assert(lv->lrugen.nr_pages[gen][type][zone] == 0);
    for (int lru = 0; lru < 4; lru++) {
        assert(lv->node[lru] == 0);
        for (int zone = 0; zone < 2; zone++)
            assert(lv->zone[zone][lru] == 0);
    }
    assert(!warnings);
}
int main(void)
{
    int cases = 0;
    for (int seq = 3; seq <= 6; seq += 3)
    for (int gen = 0; gen < 4; gen++)
    for (int type = 0; type < 2; type++)
    for (int zone = 0; zone < 2; zone++)
    for (int huge = 0; huge < 2; huge++)
    for (int reclaim = 0; reclaim < 2; reclaim++) {
        struct lruvec lv = {.lrugen.max_seq = seq};
        struct page page = {.type = type, .zone = zone, .count = huge ? 512 : 1};
        bool active = seq == 3 ? (gen == 2 || gen == 3) : (gen == 1 || gen == 2);
        for (int cycle = 0; cycle < 3; cycle++) {
            page.flags = ((gen + 1UL) << LRU_GEN_PGOFF) | BIT(PG_referenced);
            page.lru.linked = true;
            lru_gen_update_size(&lv, &page, -1, gen);
            assert(lru_gen_del_folio(&lv, &page, reclaim));
            assert_empty(&lv);
            assert(!page.lru.linked && folio_lru_gen(&page) == -1);
            assert(page.flags == (BIT(PG_referenced) |
                   (!reclaim && active ? BIT(PG_active) : 0)));
        }
        /* A second removal must leave flags and accounting untouched. */
        unsigned long flags = page.flags;
        assert(!lru_gen_del_folio(&lv, &page, reclaim));
        assert(page.flags == flags);
        assert_empty(&lv);
        cases++;
    }
    /* Promotion from inactive gen 0 to active gen 2 forces an exchange retry. */
    for (int type = 0; type < 2; type++) {
        struct lruvec lv = {.lrugen.max_seq = 3};
        struct page page = {.flags = 1UL << LRU_GEN_PGOFF,
                            .type = type, .count = 1, .lru.linked = true};
        lru_gen_update_size(&lv, &page, -1, 0);
        racing_page = &page;
        racing_lruvec = &lv;
        inject_retry = true;
        exchanges = 0;
        assert(lru_gen_del_folio(&lv, &page, true));
        assert(exchanges == 2 && !inject_retry);
        assert_empty(&lv);
        assert(!page.lru.linked && page.flags == BIT(PG_referenced));
    }
    printf("PASS: %d accounting cases (three cycles each), non-member removal, "
           "and two promotion/retry cases\n", cases);
}
'''

resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
with tempfile.TemporaryDirectory(prefix='mglru-accounting-') as directory:
    source_path = Path(directory) / 'check.c'
    binary = Path(directory) / 'check'
    source_path.write_text(code)
    subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror', '-O2',
                    str(source_path), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
