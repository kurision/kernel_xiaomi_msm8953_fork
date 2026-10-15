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

code = r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>

#define MAX_NR_GENS 4
#define MAX_NR_ZONES 3
#define MAX_LRU_BATCH 2
#define LRU_GEN_ANON 0
#define LRU_GEN_FILE 1
#define READ_ONCE(x) (x)
#define WRITE_ONCE(x, v) ((x) = (v))
#define VM_WARN_ON_ONCE_PAGE(condition, page) assert(!(condition))
#define list_empty(head) ((head)->next == (head))
#define lru_to_page(head) ((struct page *)((char *)(head)->prev - offsetof(struct page, lru)))

struct list_head { struct list_head *next, *prev; };
struct page { struct list_head lru; int zone, type, gen; bool unevictable, active; };
struct lru_gen_page {
    unsigned long min_seq[2];
    struct list_head pages[MAX_NR_GENS][2][MAX_NR_ZONES];
};
struct pglist_data { int lru_lock; };
struct lruvec { struct lru_gen_page lrugen; struct pglist_data pgdat; };
static int reset_calls;

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
static bool PageUnevictable(struct page *page) { return page->unevictable; }
static bool PageActive(struct page *page) { return page->active; }
static int page_is_file_cache(struct page *page) { return page->type; }
static int page_zonenum(struct page *page) { return page->zone; }
static int page_inc_gen(struct lruvec *lruvec, struct page *page, bool reclaiming)
{
    (void)reclaiming;
    page->gen = lru_gen_from_seq(lruvec->lrugen.min_seq[page->type] + 1);
    return page->gen;
}
static void reset_ctrl_pos(struct lruvec *lruvec, int type, bool carryover)
{
    (void)lruvec; (void)type; assert(carryover); reset_calls++;
}
'''
code += '\n' + increment
code += r'''
static void add_page(struct lruvec *lruvec, struct page *page)
{
    list_add_tail(&page->lru,
        &lruvec->lrugen.pages[page->gen][page->type][page->zone]);
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
    int gen, type, zone;
    for (gen = 0; gen < MAX_NR_GENS; gen++)
        for (type = 0; type < 2; type++)
            for (zone = 0; zone < MAX_NR_ZONES; zone++)
                list_init(&lruvec.lrugen.pages[gen][type][zone]);
    for (gen = 0; gen < MAX_NR_GENS; gen++)
        for (type = 0; type < 2; type++)
            for (zone = 0; zone < MAX_NR_ZONES; zone++)
                list_init(&no_swap.lrugen.pages[gen][type][zone]);
    lruvec.lrugen.min_seq[LRU_GEN_ANON] = 4;
    lruvec.lrugen.min_seq[LRU_GEN_FILE] = 4;
    no_swap.lrugen.min_seq[LRU_GEN_ANON] = 4;
    for (unsigned int i = 0; i < sizeof(pages) / sizeof(pages[0]); i++)
        add_page(&lruvec, &pages[i]);

    /* The no-swap anon path advances without moving anon pages. */
    assert(inc_min_seq(&no_swap, LRU_GEN_ANON, false));
    assert(no_swap.lrugen.min_seq[LRU_GEN_ANON] == 5);
    assert(reset_calls == 1);

    /* File pages advance in each populated zone, even without swap. */
    assert(inc_min_seq(&lruvec, LRU_GEN_FILE, false));
    assert(lruvec.lrugen.min_seq[LRU_GEN_FILE] == 5);
    assert(pages[2].gen == 1);

    /* With swap, old anon pages in multiple zones move before progression. */
    assert(!inc_min_seq(&lruvec, LRU_GEN_ANON, true));
    assert(lruvec.lrugen.min_seq[LRU_GEN_ANON] == 4);
    assert(list_empty(&lruvec.lrugen.pages[0][LRU_GEN_ANON][0]));
    assert(list_empty(&lruvec.lrugen.pages[0][LRU_GEN_ANON][2]));
    assert(inc_min_seq(&lruvec, LRU_GEN_ANON, true));
    assert(lruvec.lrugen.min_seq[LRU_GEN_ANON] == 5);
    assert(pages[0].gen == 1 && pages[1].gen == 1);
    assert(list_empty(&lruvec.lrugen.pages[0][LRU_GEN_ANON][0]));
    assert(list_empty(&lruvec.lrugen.pages[0][LRU_GEN_ANON][2]));
    assert(!list_empty(&lruvec.lrugen.pages[1][LRU_GEN_ANON][0]));
    assert(!list_empty(&lruvec.lrugen.pages[1][LRU_GEN_ANON][2]));
    assert(reset_calls == 3);
    puts("PASS: anon/file generation progression across eligible zone lists");
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
