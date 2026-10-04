#!/usr/bin/env python3
"""Host regression checks against the actual swap-shadow functions in this tree."""
from pathlib import Path
import subprocess
import tempfile

repo = Path(__file__).resolve().parent.parent

def function(path, signature):
    source = (repo / path).read_text()
    start = source.index(signature)
    end = source.index('\n}', start) + 2
    return source[start:end]

code = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#define __rcu
#define SWAP_ADDRESS_SPACE_SHIFT 6
#define MEM_CGROUP_ID_SHIFT 8
#define NODES_SHIFT 1
#define EVICTION_MASK ((1UL << 48) - 1)
static unsigned int bucket_order = 3;
typedef struct { int node_id; } pg_data_t;
static pg_data_t nodes[2] = {{0}, {1}};
#define NODE_DATA(n) (&nodes[n])
static void *xa_mk_value(unsigned long v) { return (void *)((v << 1) | 1); }
static unsigned long xa_to_value(void *p) { return (uintptr_t)p >> 1; }
static bool xa_is_value(void *p) { return (uintptr_t)p & 1; }
struct xarray { void *slots[128]; unsigned long limit; int xa_lock; };
struct address_space { struct xarray i_pages; };
static struct address_space spaces[2];
typedef struct { unsigned long offset; } swp_entry_t;
static swp_entry_t swp_entry(int type, unsigned long offset) {
    (void)type; return (swp_entry_t){offset};
}
static struct address_space *swap_address_space(swp_entry_t entry) {
    return &spaces[entry.offset >> SWAP_ADDRESS_SPACE_SHIFT];
}
#define xa_lock_irq(root) ((void)(root))
#define xa_unlock_irq(root) ((void)(root))
struct radix_tree_iter { unsigned long index, next_index; };
/* next_index is the leaf-chunk boundary, as in lib/radix-tree.c. */
#define radix_tree_for_each_slot(slot, root, iter, start) \
    for (unsigned long i = (start); i < (root)->limit && \
         (((iter)->index = i), ((iter)->next_index = (i | 63UL) + 1), \
          ((slot) = &(root)->slots[i]), true); i++) if (*(slot))
#define radix_tree_deref_slot_protected(slot, lock) (*(slot))
#define radix_tree_iter_delete(root, iter, slot) (*(slot) = NULL)
'''
code += '\n' + function('mm/swap_state.c', 'void clear_shadow_from_swap_cache(')
code += '\n' + function('mm/workingset.c', 'static void *pack_shadow(')
code += '\n' + function('mm/workingset.c', 'static void unpack_shadow(')
code += r'''
int main(void) {
    spaces[0].i_pages.limit = 64;
    spaces[1].i_pages.limit = 128;
    spaces[0].i_pages.slots[10] = xa_mk_value(1);
    spaces[0].i_pages.slots[11] = xa_mk_value(2);
    spaces[0].i_pages.slots[20] = xa_mk_value(3);
    spaces[0].i_pages.slots[21] = xa_mk_value(4);
    spaces[0].i_pages.slots[12] = (void *)0x1000; /* live page */
    clear_shadow_from_swap_cache(0, 10, 20);
    assert(!spaces[0].i_pages.slots[10]);
    assert(!spaces[0].i_pages.slots[11]);
    assert(!spaces[0].i_pages.slots[20]);
    assert(spaces[0].i_pages.slots[21]);
    assert(spaces[0].i_pages.slots[12] == (void *)0x1000);
    clear_shadow_from_swap_cache(0, 15, 19);
    assert(spaces[0].i_pages.slots[21]); /* sparse out-of-range shadow */
    spaces[0].i_pages.slots[62] = xa_mk_value(5);
    spaces[1].i_pages.slots[64] = xa_mk_value(6);
    spaces[1].i_pages.slots[70] = xa_mk_value(7);
    spaces[1].i_pages.slots[71] = xa_mk_value(8);
    clear_shadow_from_swap_cache(0, 60, 70);
    assert(!spaces[0].i_pages.slots[62]);
    assert(!spaces[1].i_pages.slots[64]);
    assert(!spaces[1].i_pages.slots[70]);
    assert(spaces[1].i_pages.slots[71]);
    for (unsigned long token = 0; token < 1024; token++) {
        int id; pg_data_t *node; unsigned long decoded; bool workingset;
        void *shadow = pack_shadow(17, &nodes[1], token, token & 1);
        unpack_shadow(shadow, &id, &node, &decoded, &workingset);
        assert(id == 17 && node == &nodes[1] && decoded == token);
        assert(workingset == (bool)(token & 1));
    }
    puts("PASS: shadow range cleanup, live-page preservation, cross-space cleanup, token round trips");
}
'''
with tempfile.TemporaryDirectory(prefix='mglru-shadow-') as directory:
    source = Path(directory) / 'check.c'
    binary = Path(directory) / 'check'
    source.write_text(code)
    subprocess.run(['cc', '-std=c11', '-O2', str(source), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
