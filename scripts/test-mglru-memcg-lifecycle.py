#!/usr/bin/env python3
"""Check memcg global-LRU teardown ordering using the actual CSS hooks."""
from pathlib import Path
import resource
import subprocess
import tempfile

repo = Path(__file__).resolve().parent.parent


def function(signature):
    text = (repo / 'mm/memcontrol.c').read_text()
    start = text.index(signature)
    return text[start:text.index('\n}', start) + 2]


code = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
struct cgroup_subsys_state { int unused; };
struct mem_cgroup {
    struct cgroup_subsys_state css;
    int id_live;
    int offlined;
    int released;
    int invalidated;
    int event_list_lock;
    int memory;
};
struct mem_cgroup_event { int list, remove; };
static struct mem_cgroup group = {.id_live = 1};
#define mem_cgroup_from_css(css) ((void)(css), &group)
#define spin_lock(lock) ((void)(lock))
#define spin_unlock(lock) ((void)(lock))
#define list_for_each_entry_safe(event, tmp, head, member) \
    for ((event) = NULL, (tmp) = NULL; (void)(tmp), (event) != NULL; )
static void list_del_init(void *entry) { (void)entry; }
static void page_counter_set_min(int *counter, int value) { (void)counter; (void)value; }
static void page_counter_set_low(int *counter, int value) { (void)counter; (void)value; }
static void memcg_offline_kmem(struct mem_cgroup *memcg) { (void)memcg; }
static void wb_memcg_offline(struct mem_cgroup *memcg) { (void)memcg; }
static void schedule_work(void *work) { (void)work; }
static void mem_cgroup_id_put(struct mem_cgroup *memcg)
{
	assert(memcg->offlined && memcg->id_live);
	memcg->id_live = 0;
}
static void lru_gen_offline_memcg(struct mem_cgroup *memcg)
{
    assert(memcg->id_live && !memcg->offlined);
    memcg->offlined = 1;
}
static void invalidate_reclaim_iterators(struct mem_cgroup *memcg)
{
    assert(!memcg->released);
    memcg->invalidated = 1;
}
static void lru_gen_release_memcg(struct mem_cgroup *memcg)
{
    assert(memcg->invalidated && !memcg->released);
    memcg->released = 1;
}
'''
code += '\n' + function('static void mem_cgroup_css_offline(')
code += '\n' + function('static void mem_cgroup_css_released(')
code += r'''
int main(void)
{
    mem_cgroup_css_offline(&group.css);
    assert(group.offlined && !group.id_live);
    mem_cgroup_css_released(&group.css);
    assert(group.invalidated && group.released);
    puts("PASS: memcg offlining and release ordering");
}
'''

resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
with tempfile.TemporaryDirectory(prefix='mglru-memcg-lifecycle-') as directory:
    source = Path(directory) / 'check.c'
    binary = Path(directory) / 'check'
    source.write_text(code)
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-O2',
                    str(source), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
