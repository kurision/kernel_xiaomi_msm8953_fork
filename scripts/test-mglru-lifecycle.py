#!/usr/bin/env python3
"""Exercise the actual mm migration function with modeled kernel primitives."""
from pathlib import Path
import resource
import subprocess
import tempfile

repo = Path(__file__).resolve().parent.parent
source = (repo / 'mm/vmscan.c').read_text()
start = source.index('void lru_gen_migrate_mm(')
end = source.index('\n}', start) + 2

code = r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
struct mem_cgroup { int refs; };
struct list_head { bool empty; };
struct mm_struct;
struct task_struct {
    struct mm_struct *mm;
    struct mem_cgroup *memcg;
    bool alloc_lock;
};
struct mm_struct {
    struct task_struct *owner;
    struct {
        struct mem_cgroup *memcg;
        struct list_head list;
    } lru_gen;
};
static bool disabled;
static int rcu_depth, lookups, moves;
#define rcu_dereference_protected(pointer, condition) (pointer)
#define lockdep_assert_held(lock) assert(*(lock))
#define VM_BUG_ON_MM(condition, mm) assert(!(condition))
#define VM_WARN_ON_ONCE(condition) assert(!(condition))
#define list_empty(list) ((list)->empty)
static bool mem_cgroup_disabled(void) { return disabled; }
static void rcu_read_lock(void) { assert(rcu_depth++ == 0); }
static void rcu_read_unlock(void) { assert(--rcu_depth == 0); }
static struct mem_cgroup *mem_cgroup_from_task(struct task_struct *task)
{
    assert(rcu_depth == 1 && task->alloc_lock);
    lookups++;
    return task->memcg;
}
/* Model registration's list membership and held memcg reference. */
static void lru_gen_del_mm(struct mm_struct *mm)
{
    assert(moves++ == 0 && !rcu_depth && !mm->lru_gen.list.empty);
    assert(mm->lru_gen.memcg && mm->lru_gen.memcg->refs == 1);
    mm->lru_gen.memcg->refs--;
    mm->lru_gen.memcg = NULL;
    mm->lru_gen.list.empty = true;
}
static void lru_gen_add_mm(struct mm_struct *mm)
{
    assert(moves++ == 1 && !rcu_depth && mm->lru_gen.list.empty);
    assert(!mm->lru_gen.memcg);
    mm->lru_gen.memcg = mm->owner->memcg;
    mm->lru_gen.memcg->refs++;
    mm->lru_gen.list.empty = false;
}
'''
code += '\n' + source[start:end]
code += r'''
int main(void)
{
    struct mem_cgroup old = {0}, target = {0};
    struct task_struct task = {.memcg = &target, .alloc_lock = true};
    struct mm_struct mm = {.owner = &task, .lru_gen.list.empty = true};
    task.mm = &mm;

    /* Before registration: no lookup, list movement or reference acquisition. */
    lru_gen_migrate_mm(&mm);
    assert(!lookups && !moves && !rcu_depth);
    assert(!mm.lru_gen.memcg && mm.lru_gen.list.empty && !target.refs);

    /* Disabled memcg: leave an existing registration intact. */
    mm.lru_gen.memcg = &old;
    mm.lru_gen.list.empty = false;
    old.refs = 1;
    disabled = true;
    lru_gen_migrate_mm(&mm);
    assert(!lookups && !moves && !rcu_depth);
    assert(mm.lru_gen.memcg == &old && old.refs == 1 && !target.refs);
    assert(!mm.lru_gen.list.empty);

    /* Already in the owner's memcg: retain the registration and reference. */
    disabled = false;
    task.memcg = &old;
    lru_gen_migrate_mm(&mm);
    assert(lookups == 1 && !moves && !rcu_depth);
    assert(mm.lru_gen.memcg == &old && old.refs == 1);
    assert(!mm.lru_gen.list.empty);

    /* Registered migration: remove from old before adding to target. */
    task.memcg = &target;
    lru_gen_migrate_mm(&mm);
    assert(lookups == 2 && moves == 2 && !rcu_depth);
    assert(mm.lru_gen.memcg == &target && !old.refs && target.refs == 1);
    assert(!mm.lru_gen.list.empty);
    puts("PASS: pre-registration, disabled memcg, same memcg, registered migration");
}
'''

# An expected assertion failure during regression development needs no core dump.
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
with tempfile.TemporaryDirectory(prefix='mglru-lifecycle-') as directory:
    source_path = Path(directory) / 'check.c'
    binary = Path(directory) / 'check'
    source_path.write_text(code)
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-O2',
                    str(source_path), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
