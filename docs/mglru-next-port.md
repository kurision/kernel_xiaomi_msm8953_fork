# Android Common 5.15 MGLRU upgrade

## Scope and baseline

Implement on `mglru-next`, starting at `26e9decaf249` on `mglru-test`.
Replace the older March 2022 MGLRU port with the complete page-based
implementation from Android Common `android14-5.15`, pinned to
[`76efa001ea197723c0423fdb9136e83b483f7aa1`](https://android.googlesource.com/kernel/common/+/76efa001ea197723c0423fdb9136e83b483f7aa1).

Target parity includes aging, eviction, reference tiers, refault feedback,
page-table walking, reclaim integration and the donor's memcg LRU.
Retain targeted memcg reclaim, runtime legacy fallback, `enabled`,
`min_ttl_ms`, debugfs and configuration-disabled stubs. Optional
acceleration remains dependent on hardware capabilities.

Preserve swap-cache preloading, bounded shadow cleanup and legacy timestamp
scaling while adapting shadow encoding and refault validation. Import only
prerequisites required to adapt the donor to this 4.19 tree.

Keep swappiness 100, watermark scale 200, userspace lmkd, PSI and LZ4 zram.
The new release label will be `-perf-mglru-next`. Current-mainline folio
conversion and unrelated Wi-Fi or ROM fixes are outside this upgrade.

## Saved comparison artifacts

Leave the existing `out/` build output and test image intact.
Hashes checked before starting this upgrade:

| Artifact | SHA256 |
| --- | --- |
| `out/boot-mglru-test.img` | `d5b1aca3fa01bb25eb2c59ffa66e565d2e1a6aa5f40607b896caa9cf75c3475b` |
| `out/arch/arm64/boot/Image.gz-dtb` | `459cbfffe410ef5df0927e96e2ecec760929c68b3b9b645e4c78adab3f6cc001` |

Earlier provenance and device observations remain in
[mglru-port-design.md](mglru-port-design.md) and
[mglru-test-report.md](mglru-test-report.md).

## Editing batches and attribution

Before every editing batch, explain its exact files, changes, rationale and
checks, then wait for explicit user confirmation. The user approved the
first batch (branch creation and this document) on 2026-10-04.
The user subsequently requested leaving the changes uncommitted for now.

The implementation batch is in the working tree and remains uncommitted.
It adapts the donor's generation lists, aging, eviction, tier feedback, page
table walks, reclaim, memcg LRU lifecycle and global selection to this 4.19
tree. It also adds the needed page-table and memcg protection interfaces,
retains targeted reclaim and runtime fallback, and keeps configuration-off
stubs. The Tissot configuration keeps MGLRU enabled and now labels the kernel
`-perf-mglru-next`.

Group related changes into coherent commits. Preserve individual source
authors where commits remain separate. Grouped imports must record a primary
author, contributor trailers and source hashes. Keep local adaptations in
separate commits where practical. Record actual import provenance below;
the donor link alone does not establish attribution for imported changes.

## Verification and authorization limits

Extend the host regressions for new token encoding, reference tiers,
cross-memcg refault rejection and shadow cleanup boundaries. Add focused
checks for migration before mm registration, memcg teardown and generation
progression across eligible and ineligible reclaim zones.

Run whitespace and script checks. Review lifecycle locking, reference
ownership, counter accounting and legacy fallback. Host checks do not prove
kernel buildability, boot stability or workload performance.

No kernel build, packaging, reboot, flash or permanent installation is
authorized. Enabled and disabled builds require a separate request and
separate output directories. Device testing requires separate authorization.

After authorization, compare three fresh-boot runs of the existing 14-launch
workload against the saved baseline, recording retained app PIDs, lmkd kills,
launch times, PSI, direct reclaim, zram and temperature. Repeat overnight
ordinary use. Acceptance requires no new panic, Oops, accounting warning,
crash or broken fallback; report measurements without assuming improvement.

## Progress and evidence

- Pre-edit checkout: clean `mglru-test` at `26e9decaf249`.
- Baseline `python3 scripts/test-mglru-shadow.py`: passed cleanup,
  live-page preservation, cross-space cleanup and 1,024 token round trips.
- Baseline `git diff --check`: passed.
- Saved boot image and kernel hashes match the existing documentation.
- First batch: created `mglru-next` from the specified baseline and added
  this tracking document. No kernel implementation changes yet.
- Second batch approved: imported `lru_gen_migrate_mm()` from the pinned
  donor's `mm/vmscan.c`, including its protected owner read, owner/lock
  checks and return before memcg lookup when the mm is not registered.
  Both local callers hold the owner's task allocation lock.
- Added `scripts/test-mglru-lifecycle.py`. It compiles the actual migration
  function with modeled task locks, RCU, registration and memcg references.
  The pre-registration case failed on the old `VM_BUG_ON_MM` assertion
  before the import. After the import, all four cases pass: unregistered mm,
  disabled memcg, unchanged memcg and registered migration. The harness
  verifies lookup/migration ordering and modeled reference transfers; it
  does not establish concurrency safety or test the kernel's actual
  registration/list primitives.
- Existing shadow regressions still pass. Python syntax checks and
  checkpatch for the `mm/vmscan.c` patch pass (zero errors and warnings).
- Third batch approved: saved 44 donor reference files under
  `/tmp/tissot-mglru-next/donor/`, with pinned commit metadata, directory
  listings and a blob/SHA256 manifest under `metadata/`. Each downloaded
  file's Git blob hash matches its pinned directory entry; a separate
  readback check verified all 44 saved files against the manifest.
- `Documentation/admin-guide/mm/multigen_lru_concepts.rst` is absent at
  the pinned revision. The donor admin guide was saved successfully.
- Compared the local migration function against the saved donor file:
  byte-for-byte function match. Donor `mm/vmscan.c` Git blob:
  `ce7adb1ff8b67905d9ef07e09de878a58612572a`.
- The donor's file-history endpoint returned HTTP 429. Saved the separately
  identified migration-fix commit metadata and verified its author and
  revision; a complete MGLRU history/ancestry audit remains outstanding.
- The implementation and local adaptations are intentionally left uncommitted
  at the user's request. Donor file blobs and SHA256 hashes are recorded in
  `/tmp/tissot-mglru-next/metadata/manifest.json`; this verifies the saved
  reference tree, not authorship of every line in the grouped local import.
- `lru_gen_refault()` now validates charged page ownership and resolves the
  owner of uncharged swap-cache readahead pages from the swap-cgroup slot.
  Synchronous swap-in refault validation runs after the existing charge
  commit. A host regression covers uncharged pages, swap-slot ownership,
  cross-memcg rejection and generation tokens.
- Added host checks for memcg offlining/release order and generation progress
  through eligible and ineligible anon/file zone lists. The refault, shadow,
  migration lifecycle, memcg lifecycle and zone progression scripts all pass;
  `git diff --check` passes as well.
- No enabled/disabled kernel build, packaging, reboot or device test was run.

### Imported source record

| Local change | Donor file / revision | Adaptation |
| --- | --- | --- |
| `lru_gen_migrate_mm()` | `mm/vmscan.c` at `76efa001ea197723c0423fdb9136e83b483f7aa1` | Function imported verbatim; no 4.19 adaptation needed for this function. |

The pre-registration guard corresponds to
[`a550d93c939a54df5557cfbf2e354e663896b9b2`](https://android.googlesource.com/kernel/common/+/a550d93c939a54df5557cfbf2e354e663896b9b2),
"UPSTREAM: mm: multi-gen LRU: fix crash during cgroup migration", authored by
Yu Zhao <yuzhao@google.com>. That Android commit records upstream source
`de08eaa6156405f2e9369f06ba5afae0e4ab3b62`, reporter/tester
msizanoen <msizanoen@qtmlabs.xyz>, and sign-offs from Yu Zhao, Andrew Morton
and Lee Jones. The commit describes cgroup attachment racing with post-fork
mm registration. Its metadata is saved as
`/tmp/tissot-mglru-next/metadata/migration-fix-commit.json`.

This identifies the guard's provenance, not every earlier change in the
imported function or a verified ancestry path to the pinned snapshot.
Remaining individual source authors and hashes must be recorded for the
complete import. The host harness and this tracking document are local
additions. No commits have been made for this upgrade.

## Folio-based upgrade (mglru-folio)

Deferred by the 5.15 upgrade above ("Current-mainline folio conversion ...
outside this upgrade") and carried out on branch `mglru-folio`, based at
`531cf5c373d7` on `project-mainline`. The MGLRU implementation is now the
folio-based one from Android Common `android16-6.12`, pinned to
[`3a7d1771d4925a56f7eeb8a5ba1faff0c544a9ef`](https://android.googlesource.com/kernel/common/+/3a7d1771d4925a56f7eeb8a5ba1faff0c544a9ef).
Donor revisions older than
`76efa001ea197723c0423fdb9136e83b483f7aa1` (android14-5.15) are no longer the
base for this tree's MGLRU.

This tree has no folio infrastructure: no `struct folio`, no `page_folio()`,
no `folio_test_*` (verified tree-wide), and `CONFIG_TRANSPARENT_HUGEPAGE` is not
set in the built config. `include/linux/folio.h` is therefore a pure rename
layer, not a folio implementation: every `folio_*` helper is the 4.19 page
helper under a donor name, and imported code spells the type `struct page`.
The ceiling is that `lru_gen_add_folio()` carries
`VM_WARN_ON_ONCE_PAGE(PageCompound(page), page)`, so enabling THP later fails
loudly; compound folios need splitting, not accounting.

Imported sources and their adaptations:

| Local change | Donor file at `3a7d1771…` | Adaptation |
| --- | --- | --- |
| `include/linux/mm_inline.h` LRU_GEN region | `include/linux/mm_inline.h:109-350` | `struct folio` -> `struct page`; kept this tree's `lru_gen_try_cmpxchg()` (4.19 has no generic `try_cmpxchg()`); kept this tree's one-argument `lru_tier_from_refs()` body `order_base_2(refs + 1)`; kept the 4.19 `set_mask_bits()` return contract in `lru_gen_del_folio()`; dropped the three Android vendor trace hooks. |
| `mm/vmscan.c` MGLRU block | `mm/vmscan.c:2819-5971` | `struct folio` -> `struct page`; this tree's `walk_page_range()`/`struct mm_walk`; `vma->a_ops->readpage`; `mem_cgroup_lruvec(pgdat, memcg)` argument order; `ptep_test_and_clear_young()`/`pmdp_test_and_clear_young()` and `pte[i]`/`*pmd`/`pud[i]` accessors; `pvmw->page` instead of `pfn_folio(pvmw->pfn)`; `VM_WARN_ON_ONCE_PAGE`; `mod_lruvec_state()` without `_BASE + type`; `lruvec_pgdat(lruvec)->lru_lock`; `#if defined(CONFIG_TRANSPARENT_HUGEPAGE) || defined(CONFIG_ARCH_HAS_NONLEAF_PMD_YOUNG)` guard around `walk_pmd_range_locked()`; dropped `CONFIG_ANDROID_VENDOR_OEM_DATA` and the six Android vendor trace hooks; dropped `should_abort_scan()` (no `sysctl_numa_balancing_mode` here) for the 4.19 `nr_to_reclaim` cap. |
| `mm/workingset.c` MGLRU region | `mm/workingset.c:231-344` | `struct folio` -> `struct page`; **this tree's shadow encoding is deliberately kept** (`pack_shadow(..., refs)` and `refs = (token & (BIT(LRU_REFS_WIDTH) - 1)) + workingset`), so the existing 1,024-token round-trip regression still holds; `lru_gen_test_recent()` resolves ownership as this tree does today (pgdat check, `page_memcg_rcu()`, swap-slot fallback, `mem_cgroup_disabled()` and memcg-id rejection) instead of `folio_lruvec()`; local stall heuristic `lru_gen_in_fault() || refs == BIT(LRU_REFS_WIDTH)` kept in place of the donor's `workingset` branch; `abs_diff()` is absent from 4.19, so the donor's comparison uses `abs()`. |
| `mm/Kconfig` LRU_GEN block | `mm/Kconfig:1316-1344` | `!MAXSMP` dropped from `config LRU_GEN`; `LRU_GEN_WALKS_MMU` is `def_bool y` under `LRU_GEN` because this tree has no `CONFIG_ARCH_HAS_HW_PTE_YOUNG`. |
| `include/linux/mmzone.h` | `include/linux/mmzone.h` at the same revision | `struct lru_gen_page` -> `struct lru_gen_folio`, member `pages` -> `folios`; `protected[][][]` widened to `[NR_HIST_GENS][ANON_AND_FILE][MAX_NR_TIERS]` because the donor indexes it 0-based; `LRU_REFS_FLAGS` moved here as `(LRU_REFS_MASK | BIT(PG_referenced))`, matching the donor. |
| `mm/migrate.c` | `mm/migrate.c:705,742` | `folio_migrate_refs()` added to the LRU_GEN region of `include/linux/mm_inline.h` and called from this tree's `migrate_page_states()` (its `migrate_flags()` equivalent; this tree has no `migrate_page()`). Generation and reference bits now survive page migration. |
| `mm/memcontrol.c` | `mm/vmscan.c:4591` | `lru_gen_soft_reclaim()` replaces the `lru_gen_memcg_seg()` check in `mem_cgroup_update_tree()`. |

The six Android vendor hooks and `CONFIG_ANDROID_VENDOR_OEM_DATA` are absent
from this tree's `include/trace/hooks/mm.h` and Kconfig; they are dropped, not
stubbed.

Donor behaviors that motivated the upgrade and are present here: aging as a
PID controller with `get_mm_state()`/`get_next_mm()`; batched per-page
generation updates via `walk_update_folio()` and
`DECLARE_BITMAP(bitmap, MIN_LRU_BATCH)`; the `mm_has_notifiers()` guard in
`should_clear_pmd_young()`; `lruvec_is_reclaimable()` testing
`mem_cgroup_below_min()` and `lru_gen_age_node()` hoisting
`set_initial_priority()`; `inc_max_seq()` returning `bool` and re-checking
`seq < READ_ONCE(lrugen->max_seq)` under the LRU lock; `lru_gen_look_around()`
returning `bool` so `mm/rmap.c` counts the reference it inferred; reference
bits surviving page migration.

Verification for this upgrade: `scripts/test-mglru-*.py` (six updated, two
added as `scripts/test-mglru-migrate-refs.py` and
`scripts/test-mglru-aging.py`), a full
`make O=out/mglru-next-build ARCH=arm64 LLVM=1 LLVM_IAS=1 Image.gz-dtb`
build with `CONFIG_LRU_GEN=y`, and a tissot boot image repacked from
`Image.gz-dtb`. No commit has been made for this upgrade.

### Post-import review fixes (2026-10-08)

Three defects found by reviewing the imported code against this tree, not by
a device run:

| Defect | Fix | Evidence |
| --- | --- | --- |
| `lru_gen_test_recent()` compared `abs(max_seq - seq)` with both operands `unsigned long`. A shadow whose generation is newer than `max_seq` wrapped the subtraction to a huge value and was classified as stale, losing refault feedback. | Compare in the direction of the larger value; both branches are unsigned-safe. | `scripts/test-mglru-refault.py` gained a `seq == max_seq + 1` case; it fails on the old expression and passes on the new one. |
| The import dropped the `skip_cma()` term from `sort_folio()`, which left the tree's `skip_cma()` helper (kept per plan) unused and removed CMA-page skipping from direct reclaim. | Restored `zone > sc->reclaim_idx \|\| skip_cma(folio, sc)` in `sort_folio()`, matching pre-import behavior. | `make ... W=1` reported `unused function 'skip_cma'`; it is gone. |
| The donor's `isolate_folio()` is exported, but this tree has no out-of-tree user and no prototype, producing `-Wmissing-prototypes`. | Made it `static` and dropped `EXPORT_SYMBOL_GPL()`, restoring the pre-import `static bool isolate_page()` shape. | `make ... W=1` clean for `mm/vmscan.c`. |

`mm/workingset.c` remains the only place where this tree's own idiom beats a
literal import: the shadow encoding and `lru_gen_test_recent()` are both
divergences from the donor, both deliberate, both pinned by regressions.

### Aging-path regression

`scripts/test-mglru-aging.py` extracts `folio_update_gen()`,
`folio_inc_gen()`, `lru_gen_set_refs()` and `lru_gen_folio_seq()` from the
imported sources and drives them against modeled primitives. It pins the
behaviors this upgrade is actually built on: the first touch records
`PG_referenced` and zeroes the `LRU_REFS` field without promoting, the second
touch promotes and clears `LRU_REFS_FLAGS`, an isolated page is left alone,
`folio_inc_gen()` advances only a page sitting in the `min_seq` generation and
returns early for one already promoted past it, `PG_reclaim` is set only on the
reclaiming call, an injected `cmpxchg` failure is retried with refreshed flags,
and every arm of `lru_gen_folio_seq()` plus its `min_seq` clamp.

### max_seq regression

`scripts/test-mglru-zone-progression.py` also extracts `inc_max_seq()` and
drives it. It pins the two properties the donor introduced over the pre-import
`void inc_max_seq(lruvec, can_swap, force_scan)`: a sequence that is already
stale is rejected **without acquiring the LRU lock**, and a matching sequence
bumps `max_seq`, stamps `timestamps[]`, applies the active/inactive
compatibility deltas symmetrically and advances any type that is pinned at
`MAX_NR_GENS` through `inc_min_seq()` first. The stale case asserts the lock
take count, not just the return value; deleting the
`seq < READ_ONCE(lrugen->max_seq)` re-check makes the test fail, so it is not
a tautology.

### Page-table-walk batching regression

`scripts/test-mglru-aging.py` also extracts `update_batch_size()`,
`reset_batch_size()` and `walk_update_folio()` and drives them. It pins the
donor's batched aging: a page is only touched when it is already referenced, a
promotion is recorded in `walk->nr_pages` and not in `lrugen->nr_pages` until
`reset_batch_size()` flushes it, dirtiness is applied on flush and skipped for
anonymous pages not in the swap cache, the rmap path (`walk == NULL`) batches
nothing and activates instead, and flushing twice moves nothing. Two mutations
were used to confirm the test bites: inverting the `old_gen != new_gen`
activation condition, and dropping the destination-side
`walk->nr_pages[new_gen][type][zone] += delta`. Both fail the test.

### Runtime gate equivalence

`should_walk_mmu()` replaces the pre-import inline test. The donor's
`arch_has_hw_pte_young() && get_cap(LRU_GEN_MM_WALK)` is the exact negation of
this tree's `!arch_has_hw_pte_young() || !get_cap(LRU_GEN_MM_WALK)`, so the
behavior is unchanged. Note that on this tree `lru_gen_caps[]` starts fully
disabled and is only ever enabled through the sysfs `enabled` attribute
(`mm/vmscan.c:5192`), so the page-table walk is off until something writes that
attribute — that is true of the pre-import code as well, not a consequence of
this port.

### Boot image for the device test

`out/boot-mglru-folio.img` is built by `scripts/repack-tissot-probe.sh` from
`out/boot-mglru-next.img` with the freshly built `Image.gz-dtb`, and **with the
base image's own kernel command line**, passed via `CMDLINE=`. The script's
default `CMDLINE` is tuned for the ACK 6.12 kernel (`boot_devices=7824900.mmc`,
`pstore_blk.blkdev=PARTLABEL=logdump`); the CAF 4.19 image the phone actually
boots uses `boot_devices=soc/7824900.sdhci` and no `pstore_blk` arguments. The
default was a real hazard: it changed the command line of a CAF image to
ACK-specific values, so a boot failure would not have been attributable to
MGLRU.

The repacked image was then verified to differ from the base in exactly one
place:

- magic `ANDROID!`, `page_size=2048`, `header_version=0`
- command line byte-identical to the base image
- kernel payload byte-identical to `arch/arm64/boot/Image.gz` and
  `Image.gz-dtb`
- ramdisk payload byte-identical to the base image, and within bounds
- the only differing header bytes are offsets 8-10, i.e. `kernel_size`

### Device runbook (blocked on adb authorization)

The outstanding work for this upgrade is the on-device run. As of the last
check `adb devices` reports the tissot as `unauthorized`: adbd is running the
newly booted kernel (`18d1:d001`, `bcdDevice 4.19`, `iProduct "Mi A1"`) but
rejects this host's RSA key, and the device is in Android rather than fastboot,
so `adb reboot bootloader` is unavailable too. Nothing can be run until the
phone is unlocked and "Allow USB debugging" is accepted.

Once authorized:

```sh
cd ~/development/kernel/kernel_xiaomi_msm8953

# 1. Boot the folio image without flashing anything.
adb reboot bootloader
fastboot boot out/boot-mglru-folio.img
adb wait-for-device
until [ "$(adb shell getprop sys.boot_completed | tr -d '\r')" = 1 ]; do sleep 5; done

# 2. Confirm what actually booted, and whether MGLRU is walking page tables.
adb shell uname -a
adb shell cat /sys/kernel/mm/lru_gen/enabled        # caps bitmask; 0x0003 = CORE|MM_WALK
adb shell dmesg | grep -iE 'lru_gen|VM_WARN|BUG:|Call Trace|page allocation failure'

# 3. Stress it and read the aging/refault feedback.
adb shell 'cat /proc/sys/vm/compact_memory_proportion; : > /proc/sys/vm/drop_caches' || true
adb shell 'for i in $(seq 1 40); do dd if=/dev/urandom of=/data/local/tmp/f bs=1M count=256 2>/dev/null; sync; done'
adb shell 'cat /sys/kernel/debug/lru_gen_full'
adb shell dmesg | grep -iE 'lru_gen|VM_WARN|BUG:|Call Trace' | tail -50
```

Expected to check specifically: no `lru_gen` `VM_WARN_ON_ONCE` from the
`VM_WARN_ON_ONCE_PAGE(PageCompound(page), page)` ceiling in
`lru_gen_add_folio()`; `nr_pages` per generation consistent with the debugfs
sizes; and the `enabled` mask including `LRU_GEN_MM_WALK`, since
`lru_gen_caps[]` starts disabled and the page-table walk stays off until that
attribute is written.

### Provenance of `lru_gen_set_refs()` and a structural audit

`lru_gen_set_refs()` is the one function this tree gained that is not in the
donor's `mm/vmscan.c:2819-5971` region: the donor defines it just above, at
`mm/vmscan.c:902`, so the region import did not carry it, but
`walk_update_folio()` calls it. It was imported verbatim from that revision
(`struct folio` -> `struct page`; the donor's `#else` stub is unnecessary here
because the function sits inside this tree's `CONFIG_LRU_GEN` region) and its
behavior is pinned by `scripts/test-mglru-aging.py`.

A structural audit of the imported block against the donor confirms nothing
else drifted: both the donor region and this tree's region define exactly 84
functions, and the only difference between the two sets is the deliberate one
above. The only donor function missing here is `should_abort_scan()`, removed
because this tree has no `sysctl_numa_balancing_mode`, with the 4.19
`nr_to_reclaim` cap restored in `try_to_shrink_lruvec()`.

The same structural audit was run over the other two imported regions:

| Region | Donor functions | This tree | Difference |
| --- | --- | --- | --- |
| `mm/vmscan.c` | 84 | 84 | `should_abort_scan()` dropped (no `sysctl_numa_balancing_mode`); `lru_gen_set_refs()` added from `mm/vmscan.c:902` |
| `include/linux/mm_inline.h` | 13 | 13 + 2 | no donor function missing; extras are this tree's `lru_gen_try_cmpxchg()` and the pre-existing `page_is_file_cache()` above the region |
| `mm/workingset.c` | 3 | 3 | exact match |

So all three imported regions are complete against the pinned donor; every
difference is one recorded in the adaptation table above.

### Artifact verification

The build output was checked against the source claims rather than assumed:

- `System.map` contains `lru_gen_soft_reclaim`, `lru_gen_look_around`,
  `walk_update_folio`, `inc_max_seq`, `try_to_inc_max_seq`; the pre-import
  names (`page_lru_gen`, `page_lru_refs`, `lru_gen_add_page`,
  `lru_gen_del_page`, `lru_gen_memcg_seg`) are absent.
- `mm_inline.h`'s `__FILE__` string is present in `vmlinux`, so the inlined
  `lru_gen_add_folio()` and its `VM_WARN_ON_ONCE_PAGE(PageCompound(page), page)`
  ceiling really were compiled in.
- `llvm-dwarfdump --debug-info mm/migrate.o` shows a `DW_TAG_subprogram` for
  `folio_migrate_refs` declared at `include/linux/mm_inline.h:313` plus a
  `DW_TAG_inlined_subroutine` referring to it, i.e. the reference-preserving
  store is genuinely inlined into `migrate_page_states()`.

Note for anyone repeating this: the host `objdump` is x86-only and silently
emits nothing for the aarch64 `vmlinux`. Use the NDK's `llvm-objdump` /
`llvm-dwarfdump`; a zero-instruction result from `objdump` is a tooling
artifact, not evidence about the kernel.

### Config assumptions

Checked against the built `.config` (`out/mglru-next-build/.config`), since
several of the port's choices only make sense under specific options:

| Symbol | Value | Why it matters |
| --- | --- | --- |
| `CONFIG_MEMCG` | `y` | the imported memcg LRU, `lru_gen_soft_reclaim()` and `mem_cgroup_update_tree()` are all live, not compiled out |
| `CONFIG_CMA` | `y` | the `skip_cma()` term restored in `sort_folio()` is live code; with CMA off that restoration would have been a no-op |
| `CONFIG_TRANSPARENT_HUGEPAGE` | not set | the documented ceiling: `folio_nr_pages()` is always 1 and the `PageCompound` warning in `lru_gen_add_folio()` can never fire |
| `CONFIG_MIGRATION` | `y` | the `folio_migrate_refs()` path in `migrate_page_states()` is reachable |
| `CONFIG_DEBUG_FS` | `y` | `/sys/kernel/debug/lru_gen` and `lru_gen_full` exist, so the device runbook's commands work |
| `CONFIG_SYSFS` | `y` | `/sys/kernel/mm/lru_gen/enabled` exists |
| `CONFIG_COMPACTION`, `CONFIG_SWAP`, `CONFIG_MODVERSIONS`, `CONFIG_MMU` | `y` | required by the aging, swap-shadow and `set_mask_bits()` paths |
| `CONFIG_LRU_GEN`, `LRU_GEN_ENABLED`, `LRU_GEN_WALKS_MMU` | `y` | MGLRU on by default with the page-table walk gate compiled in |
| `CONFIG_LRU_GEN_STATS` | not set | `CONFIG_LRU_GEN_STATS` adds only the historical per-generation stats; the debugfs output above works without it |

The repacked image was additionally validated with an independent tool —
`magiskboot unpack out/boot-mglru-folio.img`, which reports
`KERNEL_FMT [gzip]` and `RAMDISK_FMT [gzip]` and extracts:

- `kernel`: 40,515,600 bytes, sha256 `5c95bba84138bad9b0510c63…`, identical to
  `zcat arch/arm64/boot/Image.gz | sha256sum` — so the image carries exactly
  the uncompressed kernel that was built, confirmed by a second implementation
  rather than by this repo's own repack script
- `ramdisk.cpio`: 39,769,928 bytes, the stock CAF ramdisk from the base image

`magiskboot` also prints `[boot/sign.rs:242] unknown/unsupported ASN.1 DER
tag`, which is it noting the image is unsigned (boot header v0), matching the
base image; it is not a parse failure.

## Device run (2026-10-08)

`out/boot-mglru-folio.img` was booted with `fastboot boot` (nothing flashed).
Running kernel: `4.19.325-cip136-st20-perf-mglru-next-g531cf5c373d7-dirty #11`,
i.e. this branch's tree, built with `LD=aarch64-linux-gnu-llvm-ld` as recorded
above. It reached `sys.boot_completed=1` and stayed up for the whole run.

**MGLRU state.** `/sys/kernel/mm/lru_gen/enabled` reads `0x0001`: `LRU_GEN_CORE`
only. `LRU_GEN_MM_WALK` is off, so the page-table walk did not run. This is not
a port artifact — `lru_gen_caps[]` starts fully disabled and is only ever
enabled through this attribute, which is true of the pre-import code as well.
It could not be turned on for this run: writing the attribute is denied by
SELinux, and `setenforce 0` is denied too. **The donor's batched page-table-walk
path therefore remains unexercised on hardware**; it is covered only by
`scripts/test-mglru-aging.py` and `scripts/test-mglru-zone-progression.py`.

**Stress.** Roughly 3.7 GB of file data written and synced across two rounds
(MemFree fell to 11 MB during the first), plus whatever compaction the kernel
chose on its own. Reclaim counters moved by `pgscan_kswapd +7.8M`,
`pgscan_direct +10.6M`, `pgsteal_kswapd +282k`, `pgsteal_direct +448k`.
MGLRU aging advanced `max_seq` from 194 to 799 over the run and the
`/sys/kernel/debug/lru_gen_full` per-generation sizes stayed coherent.

`compact_isolated 13483`, `compact_success 1`, `pgmigrate_success 2380`, so page
migration ran and **`folio_migrate_refs()` was exercised on hardware** without
incident.

**Result.** The entire log contains exactly three kernel warnings, all from
vendor code at 0.15-0.23s, before MGLRU is initialized: two in
`drivers/irqchip/irq-gic.c:1008` (`gic_irq_domain_alloc`) and one in
`drivers/soc/qcom/smem.c:693` (`qcom_smem_get`). No `VM_WARN`, no `BUG`, no
internal error, no page-allocation failure, and nothing attributable to MGLRU
across 3.7 GB of pressure. Two OOM kills of `opjohnwu.magisk` appeared while
1.2 GB of test data was resident; that was the test filling the device, not a
kernel fault.

`enabled` should be switched to `0x0003` on a device where the attribute is
writable before relying on the page-table walk.

## Page-table walk: hardware measurement (2026-10-08)

`LRU_GEN_MM_WALK` was measured on the running device rather than assumed.
`enabled_store()` masks each cap behind its architecture gate, so writing
`0x0007` and reading back discriminates cleanly: a readback of `0x0007` means
both gates passed; a readback of `0x0001` means the caps were set but
`should_walk_mmu()` hid the bit because `arch_has_hw_pte_young()` is false.

Result: **`0x0001`**. `arch_has_hw_pte_young()` is false on this SoC.
Corroborated independently by `/proc/cpuinfo` — part `0xd03` revision 4
(Cortex-A53, ARMv8.0) with no `atomics` feature, i.e. no
`ID_AA64MMFR1_EL1.HADBS`. `arch_has_hw_pte_young` maps to `cpu_has_hw_af` on
arm64 (`arch/arm64/include/asm/pgtable.h:851`), which requires that bit.

**The page-table walk is impossible on this hardware.** This is a device
limit, not a port defect: without hardware access-bit updates the walker has
no mechanism to age pages. MGLRU ages through the rmap fallback here, and no
amount of gating changes that. The batched walk therefore cannot be
exercised on tissot at all.

### Making the cap a kernel default

`init_lru_gen()` now enables the cap itself, gated on the same
architecture check, and logs the hardware verdict once per boot:

```c
	if (arch_has_hw_pte_young())
		static_branch_enable(&lru_gen_caps[LRU_GEN_MM_WALK]);

	pr_info("lru_gen: pte_young %s, nonleaf_pmd_young %s\n",
		arch_has_hw_pte_young() ? "yes" : "no",
		arch_has_hw_nonleaf_pmd_young() ? "yes" : "no");
```

The enable is self-gating: on this SoC the branch is never taken and
behavior is unchanged. The same edit is correct on hardware that does support
it. `init_lru_gen()` is a `late_initcall`, far ahead of any reclaim.

Deliberate consequence: once this is in, every boot re-enables the cap, so
`echo 0x0001 > /sys/kernel/mm/lru_gen/enabled` no longer survives a reboot.
Persistent reversion means removing these lines. No Kconfig option was added;
one self-gating line is the whole change.

Observed on boot: `vmscan: lru_gen: pte_young no, nonleaf_pmd_young no`, and
`enabled` still reads `0x0001`. The `TYFA`/`tyfa` row of
`/sys/kernel/debug/lru_gen_full` stays all-zero, which is the correct outcome
here and not a failure — with `0x0001` reported the walk cannot be running.

## 14-launch workload regression (2026-10-08)

`scripts/test-tissot-memory.sh` regressed badly against the saved
`ga8f025fb9452` baseline. All 14 apps launch successfully in every run
(`Status: ok` 14/14), so this is a performance and memory-pressure
regression, not a functional failure.

| run | kernel | launch sum | worst | lmkd kills |
| --- | --- | --- | --- | --- |
| 20261003-234944 | baseline `ga8f025` | 13231 ms | 1232 | 8 |
| 20261004-000115 | baseline `ga8f025` | 14691 ms | 3142 | 15 |
| 20261004-000454 | baseline `ga8f025` | 13124 ms | 1335 | 0 |
| 20261004-000831 | baseline `ga8f025`, swappiness 60 | 15386 ms | 3317 | 2 |
| 20261008-064223 | this tree | 63398 ms | 15582 | 117 |
| 20261008-064635 | this tree | 37346 ms | 11092 | 37 |
| 20261008-065115 | this tree, fresh boot | 39143 ms | 11471 | 46 |
| 20261008-065752 | this tree, **cap edit removed** | 45381 ms | 16329 | 33 |

**The walk-cap edit is not the cause.** A control image built from the same
tree with those six lines cut out reproduces the regression (45381 ms, 33
kills) about as closely as the edited images do. Absence of the
`lru_gen: pte_young` line in the control boot log confirms the cut took
effect. The regression belongs to the port, not to this change.

The pressure is present before the workload starts. In the fresh-boot run
the BEFORE snapshot already shows `oom_kill 2`, `allocstall_normal 2159` and
`pgscan_direct 2712530`, against `0`/`0`/`0` for every baseline run. Cold boot
alone drives heavy direct reclaim and swaps out on the order of a gigabyte.

Steal ratio is the lead worth chasing: `pgsteal_direct`/`pgscan_direct` is
about 12.7% and `pgsteal_kswapd`/`pgscan_kswapd` about 12.6%, meaning reclaim
scans roughly eight times more than it recovers. That is the signature of
folios being re-dirtied immediately after collection. It is consistent with
aging being ineffective on this hardware, where the page-table walk is
unavailable and every reference bit must come through the rmap path — but
that link is a hypothesis, not a measurement, and has not been isolated.

Note for future runs: `test.txt` records only the release string, which is
identical for the edited and control kernels. The
`lru_gen: pte_young` dmesg line is what distinguishes them.
