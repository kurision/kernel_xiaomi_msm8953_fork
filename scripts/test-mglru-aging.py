#!/usr/bin/env python3
"""Run the real MGLRU aging promotion path against modeled kernel primitives.

Covers folio_update_gen(), folio_inc_gen() and lru_gen_folio_seq(): the code
that decides whether a page-table walk promotes a page, and the page-table
walk batching that depends on their return values.
"""
from pathlib import Path
import resource
import subprocess
import tempfile

repo = Path(__file__).resolve().parent.parent
bitops = (repo / 'include/linux/bitops.h').read_text()
inline = (repo / 'include/linux/mm_inline.h').read_text()
vmscan = (repo / 'mm/vmscan.c').read_text()


def function(signature, text):
    start = text.index(signature)
    return text[start:text.index('\n}', start) + 2]


code = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>

#define BIT(n) (1UL << (n))
#define BIT_I(n) (1 << (n))
#define MAX_NR_GENS 4
#define MIN_NR_GENS 2
#define ANON_AND_FILE 2
#define MAX_NR_ZONES 2
#define MAX_LRU_TIERS 4
#define NR_HIST_GENS 1
#define LRU_GEN_WIDTH 3
#define LRU_GEN_PGOFF 11
#define LRU_GEN_MASK ((BIT(LRU_GEN_WIDTH) - 1) << LRU_GEN_PGOFF)
#define LRU_REFS_WIDTH 2
#define LRU_REFS_PGOFF 8
#define LRU_REFS_MASK ((BIT(LRU_REFS_WIDTH) - 1) << LRU_REFS_PGOFF)
#define LRU_REFS_FLAGS (LRU_REFS_MASK | BIT(PG_referenced))
#define PG_referenced 0
#define PG_active 1
#define PG_workingset 2
#define PG_reclaim 3
#define PG_unevictable 4
#define LRU_GEN_ANON 0
#define LRU_GEN_FILE 1
#define READ_ONCE(x) (x)
#define WRITE_ONCE(x, v) ((x) = (v))
#define VM_WARN_ON_ONCE(x) assert(!((long)(x)))
#define max(a, b) ((a) > (b) ? (a) : (b))
#define VM_WARN(x) VM_WARN_ON_ONCE(x)
#define VM_WARN_ON_ONCE_PAGE(x, page) VM_WARN_ON_ONCE(x)
#define LRU_INACTIVE_ANON 0
#define LRU_ACTIVE_ANON 1
#define LRU_INACTIVE_FILE 2
#define LRU_ACTIVE_FILE 3
#define LRU_ACTIVE 1
enum lru_list { lru_list_unused };

struct page {
    unsigned long flags;
    int type;
    int zone;
    bool swapcache;
    bool swapbacked;
    bool anon;
    bool dirty;
    bool writeback;
};
struct lru_gen_mm_walk {
    struct lruvec *lruvec;
    unsigned long max_seq;
    int nr_pages[MAX_NR_GENS][ANON_AND_FILE][MAX_NR_ZONES];
    int batched;
};
enum lru_list_unused_tag { lru_gen_mm_walk_tag };
struct lru_gen_folio;
struct lru_gen_folio {
    unsigned long max_seq;
    unsigned long min_seq[ANON_AND_FILE];
    long nr_pages[MAX_NR_GENS][ANON_AND_FILE][MAX_NR_ZONES];
};
struct lruvec {
    struct lru_gen_folio lrugen;
    long node[4], zone[MAX_NR_ZONES][4];
};

#define folio_test_referenced(p) (!!((p)->flags & BIT(PG_referenced)))
#define folio_test_active(p) (!!((p)->flags & BIT(PG_active)))
#define folio_test_workingset(p) (!!((p)->flags & BIT(PG_workingset)))
#define folio_test_reclaim(p) (!!((p)->flags & BIT(PG_reclaim)))
#define folio_test_unevictable(p) (!!((p)->flags & BIT(PG_unevictable)))
#define folio_test_swapcache(p) ((p)->swapcache)
#define folio_test_swapbacked(p) ((p)->swapbacked)
#define folio_test_anon(p) ((p)->anon)
#define folio_test_dirty(p) ((p)->dirty)
#define folio_test_writeback(p) ((p)->writeback)
#define folio_is_file_lru(p) ((p)->type)
#define folio_nr_pages(p) 1
#define folio_zonenum(p) ((p)->zone)
#define folio_test_lru(p) 1
#define MAX_LRU_BATCH 128
static int activate_calls;
static void folio_activate(struct page *p) { (void)p; activate_calls++; }
static void folio_mark_dirty(struct page *p) { p->dirty = true; }
#define lru_to_folio(head) ((struct page *)0)
#define list_add(list, head) do { } while (0)
#define list_add_tail(list, head) do { } while (0)
#define list_del(list) do { } while (0)

static int rcu_depth;
static bool rcu_held(void) { return rcu_depth == 1; }
static void rcu_read_lock(void) { rcu_depth++; }
static void rcu_read_unlock(void) { rcu_depth--; }
#define rcu_read_lock_held() rcu_held()

static void __update_lru_size(struct lruvec *lv, enum lru_list lru, int zone, int n)
{
    lv->node[lru] += n;
    lv->zone[zone][lru] += n;
}
static int order_base_2(unsigned long n) { int o = 0; for (n--; n; n >>= 1) o++; return o; }

/* Injected cmpxchg contention, mirroring a concurrent aging promotion. */
static bool inject_retry;
static int exchanges;
static struct page *racing_page;
static struct lruvec *racing_lruvec;
static int racing_old_gen;
static void promote_during_exchange(void);

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
macro = vmscan[vmscan.index('#define for_each_gen_type_zone('):]
macro = macro[:macro.index('\n\n')]
code += '\n' + macro + '\n'
start = bitops.index('#define set_mask_bits(')
code += '\n' + bitops[start:bitops.index('\n#endif', start)] + '\n'
for name, sig in (('lru_gen_try_cmpxchg', 'static inline bool lru_gen_try_cmpxchg('),                  ('lru_gen_from_seq', 'static inline int lru_gen_from_seq('),
                  ('lru_hist_from_seq', 'static inline int lru_hist_from_seq('),
                  ('lru_tier_from_refs', 'static inline int lru_tier_from_refs('),
                  ('folio_lru_refs', 'static inline int folio_lru_refs('),
                  ('folio_lru_gen', 'static inline int folio_lru_gen('),
                  ('lru_gen_is_active', 'static inline bool lru_gen_is_active('),
                  ('lru_gen_update_size', 'static inline void lru_gen_update_size(')):
    code += '\n' + function(sig, inline) + '\n'
code += '\n' + function('static inline unsigned long lru_gen_folio_seq(', inline) + '\n'
code += '\n' + function('static int folio_update_gen(', vmscan) + '\n'
code += '\n' + function('static int folio_inc_gen(', vmscan) + '\n'
code += '\n' + function('static bool lru_gen_set_refs(', vmscan) + '\n'
code += '\n' + function('static void update_batch_size(', vmscan) + '\n'
code += '\n' + function('static void reset_batch_size(', vmscan) + '\n'
code += '\n' + function('static void walk_update_folio(', vmscan) + '\n'
code += r'''
static void promote_during_exchange(void)
{
    /*
     * Model a concurrent page-table touch that sets PG_workingset without
     * moving the generation, between folio_inc_gen()'s load and its cmpxchg.
     * The cmpxchg must fail once and be retried with the refreshed flags.
     */
    (void)racing_lruvec;
    (void)racing_old_gen;
    racing_page->flags |= BIT(PG_workingset);
}

static long total(const struct lruvec *lv, int gen, int type)
{
    return lv->lrugen.nr_pages[gen][type][0] + lv->lrugen.nr_pages[gen][type][1];
}

int main(void)
{
    struct lruvec lv = { .lrugen = { .max_seq = 5 } };
    struct page page = { .type = LRU_GEN_ANON, .anon = true };

    lv.lrugen.min_seq[LRU_GEN_ANON] = 4;
    lv.lrugen.min_seq[LRU_GEN_FILE] = 4;

    /* A page on lru_gen_from_seq(4) == 0 in the middle of the window. */
    page.flags = (1UL << LRU_GEN_PGOFF);
    lru_gen_update_size(&lv, &page, -1, 0);

    /*
     * First touch records the reference and deliberately does not promote.
     * set_mask_bits() writes BIT(PG_referenced) into the LRU_REFS field,
     * which sets PG_referenced and zeroes the field.
     */
    rcu_read_lock();
    assert(folio_update_gen(&page, 3) == -1);
    rcu_read_unlock();
    assert(page.flags == (BIT(PG_referenced) | (1UL << LRU_GEN_PGOFF)));
    assert(folio_lru_refs(&page) == 1);
    assert(folio_lru_gen(&page) == 0);
    assert(total(&lv, 0, LRU_GEN_ANON) == 1);

    /* Second touch promotes to the requested generation and records it. */
    rcu_read_lock();
    assert(folio_update_gen(&page, 3) == 0);
    rcu_read_unlock();
    assert(folio_lru_gen(&page) == 3);
    assert(folio_test_workingset(&page));
    assert(!folio_test_referenced(&page));
    assert(folio_lru_refs(&page) == 0);
    assert(total(&lv, 0, LRU_GEN_ANON) == 1);

    /* An isolated page (no generation) is left alone. */
    page.flags &= ~LRU_GEN_MASK;
    rcu_read_lock();
    assert(folio_update_gen(&page, 3) == -1);
    rcu_read_unlock();
    page.flags = BIT(PG_referenced) | (1UL << LRU_GEN_PGOFF);
    assert(total(&lv, 0, LRU_GEN_ANON) == 1);

    /*
     * lru_gen_folio_seq(): PG_active wins, then reclaiming, then the
     * anon-not-in-swapcache case, then the workingset-adjusted default, and
     * the result never falls below min_seq[type]. max_seq is 9 here so the
     * min_seq clamp cannot hide the differences.
     */
    struct lruvec seq_lv = { .lrugen = { .max_seq = 9 } };
    seq_lv.lrugen.min_seq[LRU_GEN_ANON] = 4;
    seq_lv.lrugen.min_seq[LRU_GEN_FILE] = 4;
    struct page sp = { .type = LRU_GEN_FILE };

    /* MAX_NR_GENS - workingset(0) == 4 -> 9 - 4 + 1 == 6 */
    assert(lru_gen_folio_seq(&seq_lv, &sp, false) == 6);
    sp.flags = BIT(PG_workingset);
    assert(lru_gen_folio_seq(&seq_lv, &sp, false) == 7);
    /* PG_active -> MIN_NR_GENS - workingset */
    sp.flags = BIT(PG_active);
    assert(lru_gen_folio_seq(&seq_lv, &sp, false) == 8);
    sp.flags = BIT(PG_active) | BIT(PG_workingset);
    assert(lru_gen_folio_seq(&seq_lv, &sp, false) == 9);

    /* reclaiming -> MAX_NR_GENS */
    sp.flags = 0;
    assert(lru_gen_folio_seq(&seq_lv, &sp, true) == 6);

    /* anon not in swap cache -> MIN_NR_GENS */
    struct page ap = { .type = LRU_GEN_ANON, .anon = true };
    assert(lru_gen_folio_seq(&seq_lv, &ap, false) == 8);
    ap.swapcache = true;
    assert(lru_gen_folio_seq(&seq_lv, &ap, false) == 6);
    ap.flags = BIT(PG_workingset);
    assert(lru_gen_folio_seq(&seq_lv, &ap, false) == 7);

    /* reclaiming alone is not enough: dirty or writeback forces MIN_NR_GENS */
    ap.flags = BIT(PG_reclaim);
    assert(lru_gen_folio_seq(&seq_lv, &ap, false) == 6);
    ap.dirty = true;
    assert(lru_gen_folio_seq(&seq_lv, &ap, false) == 8);
    ap.dirty = false;
    ap.writeback = true;
    assert(lru_gen_folio_seq(&seq_lv, &ap, false) == 8);
    ap.flags = 0;

    /* The clamp keeps the sequence at or above min_seq[type]. */
    seq_lv.lrugen.max_seq = 4;
    assert(lru_gen_folio_seq(&seq_lv, &ap, false) == 4);

    /*
     * folio_inc_gen(): one generation forward from min_seq, accounting moved
     * with it, and PG_reclaim only set on the reclaiming call.
     */
    struct lruvec inc = { .lrugen = { .max_seq = 5 } };
    inc.lrugen.min_seq[LRU_GEN_ANON] = 4;
    inc.lrugen.min_seq[LRU_GEN_FILE] = 4;
    struct page p2 = { .type = LRU_GEN_ANON, .anon = true,
                       .flags = BIT(PG_referenced) | (1UL << LRU_GEN_PGOFF) };
    lru_gen_update_size(&inc, &p2, -1, 0);
    assert(folio_inc_gen(&inc, &p2, false) == 1);
    assert(folio_lru_gen(&p2) == 1);
    assert(!folio_test_reclaim(&p2));
    assert(total(&inc, 0, LRU_GEN_ANON) == 0 && total(&inc, 1, LRU_GEN_ANON) == 1);

    /*
     * A page already past min_seq is reported, not moved again: this is the
     * case folio_inc_gen() shares with folio_update_gen()'s promotion.
     */
    assert(folio_inc_gen(&inc, &p2, true) == 1);
    assert(!folio_test_reclaim(&p2));
    assert(total(&inc, 1, LRU_GEN_ANON) == 1);

    /* The reclaiming call moves a fresh page and sets PG_reclaim. */
    struct page p2r = { .type = LRU_GEN_ANON, .anon = true,
                        .flags = BIT(PG_referenced) | (1UL << LRU_GEN_PGOFF) };
    lru_gen_update_size(&inc, &p2r, -1, 0);
    assert(folio_inc_gen(&inc, &p2r, true) == 1);
    assert(folio_test_reclaim(&p2r));
    assert(total(&inc, 0, LRU_GEN_ANON) == 0 && total(&inc, 1, LRU_GEN_ANON) == 2);

    /* A page already promoted past min_seq is reported, not moved twice. */
    /* The generation field stores gen + 1. */
    struct page p3 = { .type = LRU_GEN_ANON, .anon = true,
                       .flags = BIT(PG_referenced) | BIT(PG_workingset) |
                                ((3UL + 1) << LRU_GEN_PGOFF) };
    lru_gen_update_size(&inc, &p3, -1, 3);
    assert(folio_inc_gen(&inc, &p3, false) == 3);
    assert(total(&inc, 3, LRU_GEN_ANON) == 1);

    /* A racing promotion during the cmpxchg is observed and retried. */
    struct page p4 = { .type = LRU_GEN_ANON, .anon = true,
                       .flags = BIT(PG_referenced) | (1UL << LRU_GEN_PGOFF) };
    struct lruvec race = { .lrugen = { .max_seq = 5 } };
    race.lrugen.min_seq[LRU_GEN_ANON] = 4;
    race.lrugen.min_seq[LRU_GEN_FILE] = 4;
    lru_gen_update_size(&race, &p4, -1, 0);
    racing_page = &p4;
    racing_lruvec = &race;
    racing_old_gen = 0;
    inject_retry = true;
    exchanges = 0;
    assert(folio_inc_gen(&race, &p4, false) == 1);
    assert(exchanges == 2 && !inject_retry);
    assert(folio_lru_gen(&p4) == 1);
    /* The retry dropped the reference bits, the racing workingset bit stayed. */
    assert(folio_test_workingset(&p4));
    assert(folio_lru_refs(&p4) == 0);
    assert(total(&race, 0, LRU_GEN_ANON) == 0);
    assert(total(&race, 1, LRU_GEN_ANON) == 1);

    /* lru_gen_set_refs() is the rmap-walk counterpart of folio_update_gen(). */
    struct page p5 = { .flags = (1UL << LRU_GEN_PGOFF) };
    assert(!lru_gen_set_refs(&p5));
    assert(folio_test_referenced(&p5));
    assert(((p5.flags >> LRU_REFS_PGOFF) & (BIT(LRU_REFS_WIDTH) - 1)) == 0);
    assert(lru_gen_set_refs(&p5));
    assert(folio_test_workingset(&p5) && !folio_test_referenced(&p5));

    /*
     * walk_update_folio(): the page-table walk batches one promotion per
     * distinct page and accumulates dirtiness across a run of them, so
     * nr_pages is only touched when the batch is flushed. It runs under
     * rcu_read_lock(), which folio_update_gen() requires.
     */
    struct lruvec wv = { .lrugen = { .max_seq = 5 } };
    wv.lrugen.min_seq[LRU_GEN_ANON] = 3;
    wv.lrugen.min_seq[LRU_GEN_FILE] = 3;
    struct lru_gen_mm_walk walk = { .lruvec = &wv, .max_seq = 5 };
    activate_calls = 0;

    rcu_read_lock();
    /* A NULL page is a no-op. */
    walk_update_folio(&walk, NULL, 1, true);
    rcu_read_unlock();
    assert(walk.batched == 0);

    /* Not referenced yet: the reference is recorded, nothing is batched. */
    struct page w1 = { .type = LRU_GEN_ANON, .anon = true, .swapbacked = true,
                       .zone = 1, .flags = ((3UL + 1) << LRU_GEN_PGOFF) };
    lru_gen_update_size(&wv, &w1, -1, 3);
    rcu_read_lock();
    walk_update_folio(&walk, &w1, 1, false);
    rcu_read_unlock();
    assert(walk.batched == 0);
    assert(folio_test_referenced(&w1));

    /* Now referenced: the promotion is batched, nr_pages is still untouched. */
    rcu_read_lock();
    walk_update_folio(&walk, &w1, 1, false);
    rcu_read_unlock();
    assert(walk.batched == 1);
    assert(walk.nr_pages[3][LRU_GEN_ANON][1] == -1);
    assert(walk.nr_pages[1][LRU_GEN_ANON][1] == 1);
    assert(total(&wv, 3, LRU_GEN_ANON) == 1);
    assert(total(&wv, 1, LRU_GEN_ANON) == 0);

    /* Dirtiness is applied at the flush, and skipped for anon not in swap. */
    struct page w2 = { .type = LRU_GEN_FILE, .anon = false, .swapbacked = true,
                       .zone = 0,
                       .flags = BIT(PG_referenced) | ((3UL + 1) << LRU_GEN_PGOFF) };
    lru_gen_update_size(&wv, &w2, -1, 3);
    rcu_read_lock();
    walk_update_folio(&walk, &w2, 1, true);
    rcu_read_unlock();
    assert(w2.dirty && walk.batched == 2);

    struct page w3 = { .type = LRU_GEN_ANON, .anon = true, .swapbacked = true,
                       .swapcache = false, .zone = 0,
                       .flags = BIT(PG_referenced) | ((3UL + 1) << LRU_GEN_PGOFF) };
    lru_gen_update_size(&wv, &w3, -1, 3);
    rcu_read_lock();
    walk_update_folio(&walk, &w3, 1, true);
    rcu_read_unlock();
    assert(!w3.dirty && walk.batched == 3);

    /* Without a walk (rmap path) nothing is batched and activation is used. */
    activate_calls = 0;
    struct page w4 = { .type = LRU_GEN_ANON, .anon = true, .swapbacked = true,
                       .zone = 1, .flags = ((3UL + 1) << LRU_GEN_PGOFF) };
    lru_gen_update_size(&wv, &w4, -1, 3);
    rcu_read_lock();
    walk_update_folio(NULL, &w4, 1, false);
    walk_update_folio(NULL, &w4, 1, false);
    rcu_read_unlock();
    assert(activate_calls == 1 && walk.batched == 3);

    /* reset_batch_size() applies the batch exactly once. */
    reset_batch_size(&walk);
    assert(walk.batched == 0);
    for (int g = 0; g < MAX_NR_GENS; g++)
        for (int t = 0; t < ANON_AND_FILE; t++)
            for (int z = 0; z < MAX_NR_ZONES; z++)
                assert(walk.nr_pages[g][t][z] == 0);
    assert(total(&wv, 3, LRU_GEN_ANON) == 1);   /* w4 stays behind */
    assert(total(&wv, 1, LRU_GEN_ANON) == 2);
    assert(total(&wv, 3, LRU_GEN_FILE) == 0);
    assert(total(&wv, 1, LRU_GEN_FILE) == 1);

    /* Running it again must not move anything. */
    long after = total(&wv, 1, LRU_GEN_ANON);
    reset_batch_size(&walk);
    assert(total(&wv, 1, LRU_GEN_ANON) == after);

    puts("PASS: aging promotion, isolation, generation sequence, cmpxchg retry, walk batching");
}
'''

resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
with tempfile.TemporaryDirectory(prefix='mglru-aging-') as directory:
    source = Path(directory) / 'check.c'
    binary = Path(directory) / 'check'
    source.write_text(code)
    # -Wno-sign-compare: the extracted kernel sources rely on the kernel's
    # own flags, which do not enable it.
    subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                    '-Wno-sign-compare', '-O2',
                    str(source), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)