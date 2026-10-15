#!/usr/bin/env python3
"""Run actual reference and shadow functions with modeled kernel primitives."""
from pathlib import Path
import resource
import subprocess
import tempfile

repo = Path(__file__).resolve().parent.parent


def function(path, signature):
    text = (repo / path).read_text()
    start = text.index(signature)
    return text[start:text.index('\n}', start) + 2]


code = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#define BIT(n) (1UL << (n))
#define READ_ONCE(x) (x)
#define BITS_PER_LONG 64
#define EVICTION_SHIFT 12
#define EVICTION_MASK ((1UL << 48) - 1)
#define MEM_CGROUP_ID_SHIFT 8
#define NODES_SHIFT 1
#define LRU_GEN_WIDTH 3
#define LRU_REFS_WIDTH 2
#define LRU_REFS_PGOFF 8
#define LRU_REFS_MASK (3UL << LRU_REFS_PGOFF)
#define MAX_NR_TIERS 4
#define PG_workingset 0
#define PG_referenced 1
#define PG_swapbacked 2
#define BUILD_BUG_ON(x) _Static_assert(!(x), "bad encoding")
#define VM_BUG_ON(x) assert(!(x))
#define VM_WARN_ON_ONCE(x) assert(!(x))
#define max(a, b) ((a) > (b) ? (a) : (b))
typedef unsigned long atomic_long_t;
struct lru_gen_struct {
    unsigned long min_seq[2];
    atomic_long_t evicted[1][2][MAX_NR_TIERS];
    atomic_long_t refaulted[1][2][MAX_NR_TIERS];
};
#define lru_gen_page lru_gen_struct
struct lruvec { struct lru_gen_struct lrugen; unsigned long stats[3]; };
typedef struct pglist_data { int node_id; } pg_data_t;
static pg_data_t nodes[2] = {{0}, {1}};
#define NODE_DATA(n) (&nodes[n])
struct mem_cgroup { unsigned short id; };
static struct mem_cgroup groups[2] = {{17}, {18}};
static struct lruvec lruvecs[2][2], root;
struct page { unsigned long flags; pg_data_t *node; struct mem_cgroup *memcg; int nr; bool swapcache; unsigned long private; };
typedef struct { unsigned long val; } swp_entry_t;
static bool disabled, in_fault;
static int rcu_depth;
enum { WORKINGSET_REFAULT, WORKINGSET_ACTIVATE, WORKINGSET_RESTORE };
#define PageWorkingset(p) (!!((p)->flags & BIT(PG_workingset)))
#define SetPageWorkingset(p) ((p)->flags |= BIT(PG_workingset))
#define PageSwapCache(p) ((p)->swapcache)
static unsigned long page_private(struct page *p) { return p->private; }
static unsigned short lookup_swap_cgroup_id(swp_entry_t entry) {
    assert(entry.val == 42);
    return 17;
}
static void *xa_mk_value(unsigned long v) { return (void *)((v << 1) | 1); }
static unsigned long xa_to_value(void *p) { return (uintptr_t)p >> 1; }
static int order_base_2(unsigned long n) {
    int order = 0;
    for (n--; n; n >>= 1) order++;
    return order;
}
static bool mem_cgroup_disabled(void) { return disabled; }
static unsigned short mem_cgroup_id(struct mem_cgroup *m) {
    if (disabled) return 0;
    assert(m);
    return m->id;
}
static void rcu_read_lock(void) { assert(rcu_depth++ == 0); }
static void rcu_read_unlock(void) { assert(--rcu_depth == 0); }
static struct mem_cgroup *page_memcg(struct page *p) { return p->memcg; }
static struct mem_cgroup *page_memcg_rcu(struct page *p) {
    assert(rcu_depth == 1);
    return p->memcg;
}
static struct mem_cgroup *mem_cgroup_from_id(int id) {
    assert(rcu_depth == 1);
    for (int i = 0; i < 2; i++) if (groups[i].id == id) return &groups[i];
    return NULL;
}
static pg_data_t *page_pgdat(struct page *p) { return p->node; }
static int page_is_file_cache(struct page *p) { return !(p->flags & BIT(PG_swapbacked)); }
static int hpage_nr_pages(struct page *p) { return p->nr; }
static struct lruvec *mem_cgroup_lruvec(pg_data_t *node, struct mem_cgroup *m) {
    if (disabled) return &root;
    assert(m == &groups[0] || m == &groups[1]);
    return &lruvecs[node->node_id][m == &groups[1]];
}
static int lru_hist_from_seq(unsigned long seq) { (void)seq; return 0; }
static bool lru_gen_in_fault(void) { return in_fault; }
static void atomic_long_add(int delta, atomic_long_t *v) { *v += delta; }
static void mod_lruvec_state(struct lruvec *v, int stat, int delta) { v->stats[stat] += delta; }
'''
inline = (repo / 'include/linux/mm_inline.h').read_text()
if 'static inline int page_lru_refs(' in inline:
    code += '\n' + function('include/linux/mm_inline.h', 'static inline int page_lru_refs(')
else:
    code += '\n' + function('mm/workingset.c', 'static int page_lru_refs(')
code += '\n' + function('include/linux/mm_inline.h', 'static inline int lru_tier_from_refs(')
code += '\n' + function('mm/workingset.c', 'static void *pack_shadow(')
code += '\n' + function('mm/workingset.c', 'static void unpack_shadow(')
code += '\n' + function('mm/workingset.c', 'void *lru_gen_eviction(')
code += '\n' + function('mm/workingset.c', 'void lru_gen_refault(')
code += r'''
int main(void) {
    struct page page = {.node = &nodes[0], .memcg = &groups[0], .nr = 1};
    const int tiers[] = {0, 1, 2, 2, 3};
    for (int refs = 0; refs <= 4; refs++) {
        page.flags = refs ? BIT(PG_workingset) | BIT(PG_referenced) |
                     ((unsigned long)(refs - 1) << LRU_REFS_PGOFF) : 0;
        assert(page_lru_refs(&page) == refs);
        assert(lru_tier_from_refs(refs) == tiers[refs]);
        struct lruvec *v = &lruvecs[0][0];
        memset(v, 0, sizeof(*v));
        v->lrugen.min_seq[1] = 7;
        void *shadow = lru_gen_eviction(&page);
        int id; pg_data_t *node; unsigned long token; bool workingset;
        unpack_shadow(shadow, &id, &node, &token, &workingset);
        assert(id == 17 && node == &nodes[0]);
        assert(token == (28UL | (refs ? (unsigned long)refs - 1 : 0)));
        assert(workingset == (bool)refs);
        assert(v->lrugen.evicted[0][1][tiers[refs]] == 1);
        page.flags = 0;
        lru_gen_refault(&page, shadow);
        assert(v->lrugen.refaulted[0][1][tiers[refs]] == 1);
        assert(v->stats[WORKINGSET_REFAULT] == 1);
        assert(v->stats[WORKINGSET_ACTIVATE] == 1);
        assert(PageWorkingset(&page) == (refs == 4));
        assert(!rcu_depth);
    }

    memset(lruvecs, 0, sizeof(lruvecs));
    lruvecs[0][0].lrugen.min_seq[1] = 7;
    lruvecs[0][1].lrugen.min_seq[1] = 7;
    page.flags = 0;
    page.memcg = &groups[1];
    lru_gen_refault(&page, pack_shadow(17, &nodes[0], 28, false));
    assert(!lruvecs[0][0].lrugen.refaulted[0][1][0]);
    assert(!lruvecs[0][1].lrugen.refaulted[0][1][0]);
    assert(!lruvecs[0][0].stats[WORKINGSET_REFAULT]);
    assert(!lruvecs[0][1].stats[WORKINGSET_REFAULT]);
    assert(!rcu_depth);

    /* Uncharged swap-cache readahead pages must not dereference NULL memcg. */
    page.memcg = NULL;
    lru_gen_refault(&page, pack_shadow(17, &nodes[0], 28, false));
    assert(!lruvecs[0][0].stats[WORKINGSET_REFAULT]);
    assert(!lruvecs[0][1].stats[WORKINGSET_REFAULT]);
    assert(!rcu_depth);

    /* Swap-cache ownership comes from the charged swap slot before page charge. */
    page.swapcache = true;
    page.private = 42;
    page.flags = BIT(PG_swapbacked);
    lruvecs[0][0].lrugen.min_seq[0] = 7;
    lru_gen_refault(&page, pack_shadow(17, &nodes[0], 28, false));
    assert(lruvecs[0][0].stats[WORKINGSET_REFAULT] == 1);
    assert(lruvecs[0][0].lrugen.refaulted[0][0][0] == 1);
    assert(!rcu_depth);
    page.swapcache = false;

    /* Wrong node and deleted/recycled IDs cannot feed the replacement page. */
    page.memcg = &groups[0];
    lru_gen_refault(&page, pack_shadow(17, &nodes[1], 28, false));
    lru_gen_refault(&page, pack_shadow(19, &nodes[0], 28, false));
	assert(lruvecs[0][0].stats[WORKINGSET_REFAULT] == 1 && !rcu_depth);

    /* Stale generations count refaults, but cannot train generation feedback. */
    lru_gen_refault(&page, pack_shadow(17, &nodes[0], 24, false));
	assert(lruvecs[0][0].stats[WORKINGSET_REFAULT] == 2);
    assert(!lruvecs[0][0].lrugen.refaulted[0][1][0]);

    /* Generation overflow retains the reference bits and matches modulo mask. */
    unsigned long seq = (EVICTION_MASK >> LRU_REFS_WIDTH) + 1;
    struct lruvec *v = &lruvecs[0][0];
    v->lrugen.min_seq[1] = seq;
    page.flags = BIT(PG_workingset) | BIT(PG_referenced) | LRU_REFS_MASK;
    page.nr = 512;
    void *shadow = lru_gen_eviction(&page);
    int id; pg_data_t *node; unsigned long token; bool workingset;
    unpack_shadow(shadow, &id, &node, &token, &workingset);
    assert(token == 3 && workingset);
    page.flags = 0;
    lru_gen_refault(&page, shadow);
    assert(v->lrugen.refaulted[0][1][3] == 512);

    /* Memcg-disabled anonymous refault, including a page-table stall. */
    disabled = true;
    in_fault = true;
    page.flags = BIT(PG_swapbacked);
    page.memcg = NULL;
    page.nr = 1;
    root.lrugen.min_seq[0] = 3;
    shadow = lru_gen_eviction(&page);
    lru_gen_refault(&page, shadow);
    assert(root.lrugen.refaulted[0][0][0] == 1);
    assert(root.stats[WORKINGSET_RESTORE] == 1 && PageWorkingset(&page));
    assert(!rcu_depth);
    puts("PASS: reference tiers, tokens, refault ownership, stale/wrapped generations, THP, disabled memcg");
}
'''

resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
with tempfile.TemporaryDirectory(prefix='mglru-refault-') as directory:
    source = Path(directory) / 'check.c'
    binary = Path(directory) / 'check'
    source.write_text(code)
    subprocess.run(['cc', '-std=c11', '-O2', str(source), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
