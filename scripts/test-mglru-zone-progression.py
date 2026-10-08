#!/usr/bin/env python3
"""Exercise actual generation advancement across all reclaim zones."""
from pathlib import Path
import resource
import subprocess
import tempfile

repo = Path(__file__).resolve().parent.parent
text = (repo / 'mm/vmscan.c').read_text()
signature = 'static bool inc_min_seq('
start = text.index(signature)
increment = text[start:text.index('\n}', start) + 2]
start = text.index('static bool inc_max_seq(')
bump = text[start:text.index('\n}', start) + 2]

code = r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>

#define MAX_NR_GENS 4
#define MAX_NR_ZONES 3
#define MIN_NR_GENS 2
#define ANON_AND_FILE 2
#define MAX_NR_TIERS 4
#define NR_HIST_GENS 1
#define LRU_REFS_WIDTH 2
#define BIT(n) (1UL << (n))
#define MAX_NR_ZONES 3
#define MAX_LRU_BATCH 2
#define LRU_GEN_ANON 0
#define LRU_GEN_FILE 1
#define READ_ONCE(x) (x)
#define WRITE_ONCE(x, v) ((x) = (v))
#define VM_WARN_ON_ONCE_PAGE(condition, page) assert(!(condition))
#define list_empty(head) ((head)->next == (head))
enum lru_list { LRU_INACTIVE_ANON, LRU_ACTIVE_ANON,
                LRU_INACTIVE_FILE, LRU_ACTIVE_FILE };
#define LRU_ACTIVE 1
#define VM_WARN_ON_ONCE(x) assert(!(x))
#define lru_to_folio(head) ((struct page *)((char *)(head)->prev - offsetof(struct page, lru)))

struct list_head { struct list_head *next, *prev; };
struct page { struct list_head lru; unsigned long flags; int zone, type, gen; bool unevictable, active; };
struct lru_gen_folio {
    unsigned long max_seq;
    unsigned long min_seq[2];
    unsigned long timestamps[MAX_NR_GENS];
    long nr_pages[MAX_NR_GENS][2][MAX_NR_ZONES];
    struct list_head folios[MAX_NR_GENS][2][MAX_NR_ZONES];
    unsigned long protected[NR_HIST_GENS][2][MAX_NR_TIERS];
};
struct pglist_data { int lru_lock; };
struct lruvec {
    struct lru_gen_folio lrugen;
    struct pglist_data pgdat;
    long node[4];
    long zone[MAX_NR_ZONES][4];
};
static int reset_calls;
static unsigned long jiffies;
static int locks;
static int lock_takes;
static int resched_calls;
#define spin_lock_irq(lock) do { assert(!*(lock)); *(lock) = 1; locks++; lock_takes++; } while (0)
#define spin_unlock_irq(lock) do { assert(*(lock)); *(lock) = 0; locks--; } while (0)
#define lruvec_pgdat(l) (&(l)->pgdat)
#define cond_resched() resched_calls++
#define smp_store_release(p, v) WRITE_ONCE(*(p), (v))
static void __update_lru_size(struct lruvec *lv, enum lru_list lru, int zone, int n)
{
    lv->node[lru] += n;
    lv->zone[zone][lru] += n;
}
static int get_nr_gens(struct lruvec *lruvec, int type)
{
    return lruvec->lrugen.max_seq - lruvec->lrugen.min_seq[type] + 1;
}
static bool seq_is_valid(struct lruvec *lruvec)
{
    for (int type = 0; type < 2; type++) {
        int n = get_nr_gens(lruvec, type);
        if (n < MIN_NR_GENS || n > MAX_NR_GENS) return false;
    }
    return true;
}

static void list_init(struct list_head *head)
{
    head->next = head->prev = head;
}
static void list_add_tail(struct list_head *item, struct list_head *head)
{
    item->prev = head->prev;
    item->next = head;
    head->prev->next = item;
    head->prev = item;
}
static void list_move_tail(struct list_head *item, struct list_head *head)
{
    item->prev->next = item->next;
    item->next->prev = item->prev;
    list_add_tail(item, head);
}
static int lru_gen_from_seq(unsigned long seq) { return seq % MAX_NR_GENS; }
static int lru_hist_from_seq(unsigned long seq) { return seq % NR_HIST_GENS; }
static int order_base_2(unsigned long n) { int o = 0; for (n--; n; n >>= 1) o++; return o; }
static int lru_tier_from_refs(int refs) { return order_base_2(refs + 1); }
static int folio_lru_refs(struct page *p) { (void)p; return 0; }
static int folio_nr_pages(struct page *p) { (void)p; return 1; }
static bool folio_test_workingset(struct page *p) { (void)p; return false; }
static bool folio_test_unevictable(struct page *page) { return page->unevictable; }
static bool folio_test_active(struct page *page) { return page->active; }
static int folio_is_file_lru(struct page *page) { return page->type; }
static int folio_zonenum(struct page *page) { return page->zone; }
static int folio_inc_gen(struct lruvec *lruvec, struct page *page, bool reclaiming)
{
    (void)reclaiming;
    page->gen = lru_gen_from_seq(lruvec->lrugen.min_seq[page->type] + 1);
    return page->gen;
}
static int reset_carryover_calls;
static void reset_ctrl_pos(struct lruvec *lruvec, int type, bool carryover)
{
    (void)lruvec; (void)type; reset_calls++;
    if (carryover) reset_carryover_calls++;
}
'''
code += '\n' + increment
code += '\n' + bump
code += r'''
static void add_page(struct lruvec *lruvec, struct page *page)
{
    list_add_tail(&page->lru,
        &lruvec->lrugen.folios[page->gen][page->type][page->zone]);
}

int main(void)
{
    struct lruvec lruvec = {0};
    struct page pages[] = {
        {.zone = 0, .type = LRU_GEN_ANON, .gen = 0},
        {.zone = 2, .type = LRU_GEN_ANON, .gen = 0},
        {.zone = 1, .type = LRU_GEN_FILE, .gen = 0},
    };
    struct lruvec no_swap = {0};
    int gen, type, zone, lru;
    for (gen = 0; gen < MAX_NR_GENS; gen++)
        for (type = 0; type < 2; type++)
            for (zone = 0; zone < MAX_NR_ZONES; zone++)
                list_init(&lruvec.lrugen.folios[gen][type][zone]);
    for (gen = 0; gen < MAX_NR_GENS; gen++)
        for (type = 0; type < 2; type++)
            for (zone = 0; zone < MAX_NR_ZONES; zone++)
                list_init(&no_swap.lrugen.folios[gen][type][zone]);
    lruvec.lrugen.min_seq[LRU_GEN_ANON] = 4;
    lruvec.lrugen.min_seq[LRU_GEN_FILE] = 4;
    no_swap.lrugen.min_seq[LRU_GEN_ANON] = 4;
    for (unsigned int i = 0; i < sizeof(pages) / sizeof(pages[0]); i++)
        add_page(&lruvec, &pages[i]);

    /* The no-swap anon path advances without moving anon pages. */
    assert(inc_min_seq(&no_swap, LRU_GEN_ANON, false));
    assert(no_swap.lrugen.min_seq[LRU_GEN_ANON] == 5);
    assert(reset_calls == 1 && reset_carryover_calls == 1);

    /* File pages advance in each populated zone, even without swap. */
    assert(inc_min_seq(&lruvec, LRU_GEN_FILE, false));
    assert(lruvec.lrugen.min_seq[LRU_GEN_FILE] == 5);
    assert(pages[2].gen == 1);

    /* With swap, old anon pages in multiple zones move before progression. */
    assert(!inc_min_seq(&lruvec, LRU_GEN_ANON, true));
    assert(lruvec.lrugen.min_seq[LRU_GEN_ANON] == 4);
    assert(list_empty(&lruvec.lrugen.folios[0][LRU_GEN_ANON][0]));
    assert(list_empty(&lruvec.lrugen.folios[0][LRU_GEN_ANON][2]));
    assert(inc_min_seq(&lruvec, LRU_GEN_ANON, true));
    assert(lruvec.lrugen.min_seq[LRU_GEN_ANON] == 5);
    assert(pages[0].gen == 1 && pages[1].gen == 1);
    assert(list_empty(&lruvec.lrugen.folios[0][LRU_GEN_ANON][0]));
    assert(list_empty(&lruvec.lrugen.folios[0][LRU_GEN_ANON][2]));
    assert(!list_empty(&lruvec.lrugen.folios[1][LRU_GEN_ANON][0]));
    assert(!list_empty(&lruvec.lrugen.folios[1][LRU_GEN_ANON][2]));
    assert(reset_calls == 3 && reset_carryover_calls == 3);

    /*
     * inc_max_seq() is the donor's bool-returning, lock-rechecked form: a
     * stale sequence must neither bump max_seq nor lose the lock.
     */
    struct lruvec bump_lv = {0};
    for (gen = 0; gen < MAX_NR_GENS; gen++)
        for (type = 0; type < 2; type++)
            for (zone = 0; zone < MAX_NR_ZONES; zone++)
                list_init(&bump_lv.lrugen.folios[gen][type][zone]);
    bump_lv.lrugen.min_seq[LRU_GEN_ANON] = 3;
    bump_lv.lrugen.min_seq[LRU_GEN_FILE] = 3;
    bump_lv.lrugen.max_seq = 4;
    jiffies = 12345;
    locks = 0;
    resched_calls = 0;

    /*
     * A stale sequence is rejected before the lock is even taken, so the
     * LRU lock is never acquired for a sequence that cannot be applied.
     */
    assert(!inc_max_seq(&bump_lv, 3, true));
    assert(bump_lv.lrugen.max_seq == 4 && locks == 0 && lock_takes == 0);

    /* The current sequence bumps and stamps the new generation. */
    assert(inc_max_seq(&bump_lv, 4, true));
    assert(bump_lv.lrugen.max_seq == 5);
    assert(bump_lv.lrugen.timestamps[1] == 12345);
    assert(locks == 0);
    /* Only the two non-carryover resets inc_max_seq() does itself. */
    assert(reset_calls == 5 && reset_carryover_calls == 3);

    /*
     * The active/inactive compatibility sizes are applied for both sides of
     * the old max_seq, so the totals come out unchanged.
     */
    long node_total = 0, zone_total = 0;
    for (lru = 0; lru < 4; lru++) {
        node_total += bump_lv.node[lru];
        for (zone = 0; zone < MAX_NR_ZONES; zone++)
            zone_total += bump_lv.zone[zone][lru];
    }
    assert(node_total == 0 && zone_total == 0);

    /*
     * A concurrent bump makes the caller's sequence stale. The re-check is
     * what keeps a lost generation bump from being applied twice.
     */
    bump_lv.lrugen.max_seq = 6;
    assert(!inc_max_seq(&bump_lv, 5, true));
    assert(bump_lv.lrugen.max_seq == 6);
    assert(locks == 0 && lock_takes == 1);
    assert(reset_calls == 5);

    /*
     * Matching the current sequence bumps. Both types are at MAX_NR_GENS, so
     * inc_min_seq() has to advance them first, which is what makes the call
     * drop the lock and restart in the real kernel.
     */
    reset_calls = 0;
    reset_carryover_calls = 0;
    resched_calls = 0;
    assert(inc_max_seq(&bump_lv, 6, true));
    assert(bump_lv.lrugen.max_seq == 7);
    /* inc_min_seq() advances each type once: 3 -> 4. */
    assert(bump_lv.lrugen.min_seq[LRU_GEN_ANON] == 4);
    assert(bump_lv.lrugen.min_seq[LRU_GEN_FILE] == 4);
    assert(reset_calls == 4 && reset_carryover_calls == 2);
    assert(locks == 0 && lock_takes == 2);

    puts("PASS: anon/file generation progression, max_seq bump, stale reject");
}
'''

resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
with tempfile.TemporaryDirectory(prefix='mglru-zone-progression-') as directory:
    source = Path(directory) / 'check.c'
    binary = Path(directory) / 'check'
    source.write_text(code)
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-O2',
                    str(source), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
