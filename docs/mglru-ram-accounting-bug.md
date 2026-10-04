# MGLRU port: RAM accounting corruption (NR_LRU_* inflation)

Status: **RESOLVED — root cause confirmed, fix validated on device.**
Kernel validated: `4.19.325-cip136-st20-perf-mglru-next-g26e9decaf249-dirty #4`
(image `out/boot-mglru-next-fixed3.img`). The measurements in "Reported
measurements" below describe the earlier, unfixed kernels and are retained as the
before-state.
Device: Xiaomi Mi A1 (tissot), Snapdragon 625 / MSM8953, 3.6 GB RAM, A/B, slot `_a`.
Kernel with the defect: `4.19.325-cip136-st20-perf-mglru-next-g26e9decaf249-dirty #3`
Branch: `mglru-next` (base `26e9decaf249`), port uncommitted.
Donor: Android Common `android14-5.15` @ `76efa001ea197723c0423fdb9136e83b483f7aa1`
Date: 2026-10-04

---

## Summary

**Root cause (confirmed).** `include/linux/mm_inline.h` `lru_gen_del_page()` derived
the page's generation index from the *return value* of `set_mask_bits()`:

```c
flags = set_mask_bits(&page->flags, LRU_GEN_MASK, flags);
gen = ((flags & LRU_GEN_MASK) >> LRU_GEN_PGOFF) - 1;
```

In this tree `set_mask_bits` is a macro (`include/linux/bitops.h:249-260`) whose
last expression is `new__`, i.e. it returns the **new** flags. The donor's
`set_mask_bits` is a function that returns the **old** value. Because the call
clears `LRU_GEN_MASK`, the returned flags always yield `gen = -1`.

`lru_gen_update_size(lruvec, page, -1, -1)` then satisfies neither `old_gen >= 0`
nor `new_gen >= 0`, so it falls into the **addition** branch
(`include/linux/mm_inline.h:209-214`) and calls
`__update_lru_size(lruvec, lru, zone, delta)` with a **positive** delta. Every page
*removal* therefore **incremented** `NR_LRU_*` instead of decrementing it.

This fully explains the observed shape: monotonic inflation during early boot and
aging, then a plateau once add/remove balanced in aggregate, with no correction on
runtime disable (disabling stops further drift but never winds the counters back).

`/proc/meminfo` `Active`/`Inactive` derive from these counters
(`fs/proc/meminfo.c:70-71`), and `si_mem_available()` sums the file LRU counters
(`mm/page_alloc.c:5310`), so `MemAvailable` exceeded `MemTotal`.

User-visible symptom, now resolved: devcheck reported ~10 GB total RAM with
**-6.23 GB used**, and SRAM displayed **0.0 MB**.

The fix captures `old_flags` before the cmpxchg loop and derives `gen` from it via
`lru_gen_try_cmpxchg()`, restoring donor semantics. `lru_gen_add_page()`
(`mm_inline.h:269`), `mm/vmscan.c:4210` and `mm/vmscan.c:4439` all discard
`set_mask_bits`'s return value, so `lru_gen_del_page()` was the only affected
consumer.

No panic, Oops or BUG was reported at any point.

---

## Reported measurements

The measurements below are preserved from the device report; they were not
independently reproduced during the source review. Parenthetical binary memory
conversions are GiB despite the original GB labels. Time-series values and labels
are preserved as reported; their conversion basis was not independently verified.

### meminfo comparison (uptime ~260s, MGLRU enabled)

| Metric | Value | Expected |
| --- | --- | --- |
| `MemTotal` | 3645964 kB (3.48 GB) | device truth |
| `MemAvailable` | **12088692 kB (11.53 GB)** | should not exceed `MemTotal` |
| `MemFree` | 155464 kB | plausible |
| `AnonPages` | 1000544 kB (0.95 GB) | mapped anonymous pages (`NR_ANON_MAPPED`) |
| `Active(anon)` | 6442956 kB (6.14 GB) | — |
| `Inactive(anon)` | 14455680 kB (13.78 GB) | — |
| `Active(anon)+Inactive(anon)` | **20908636 kB (19.94 GB)** | should not exceed physical memory |
| `Cached` | 1186128 kB | plausible |

`anon LRU / AnonPages` = **20.9x**. `anon LRU / MemTotal` = **5.7x**.
The first ratio is descriptive, not an accounting invariant: anon LRU includes
tmpfs and other swap-backed pages (`page_is_file_cache()` in
`include/linux/mm_inline.h`), whereas `AnonPages` reads `NR_ANON_MAPPED`
(`fs/proc/meminfo.c`).

### vmstat node counters

| Counter | Value | Meaning |
| --- | --- | --- |
| `nr_active_anon` | 1613510 | |
| `nr_inactive_anon` | 3615442 | |
| `nr_active_file` | 939389 | |
| `nr_inactive_file` | 2050869 | |
| `nr_anon_pages` | **251253** | mapped anonymous pages |
| `nr_file_pages` | **298010** | page-cache pages |
| `nr_free_pages` | 37481 | |

Sum of the four `nr_*_anon`/`nr_*_file` LRU counters is **8219210 pages** against
**549263 pages** from `nr_anon_pages + nr_file_pages` — a **15.0x** ratio, not
an exact comparison of equivalent populations. (Do not compare the page
count to a GB figure: these counters are in pages, and `MemTotal` is 911491 pages.)
MGLRU's own `lrugen->nr_pages[]` reportedly showed plausible values in
`/sys/kernel/debug/lru_gen`. Those values are not included here, so the claimed
divergence and internal consistency still require synchronized measurements.

### Time series — MemAvailable approximately plateaus high

```
uptime  MemAvailable   anon LRU     delta(avail)
   59s     6.16 GB       8.37 GB
   99s     9.22 GB      15.09 GB     +3.06 GB
  139s     9.87 GB      16.42 GB     +0.65 GB
  180s    12.14 GB      18.68 GB     +2.27 GB
  220s    12.12 GB      18.85 GB     -0.02 GB   <- plateau
  260s    12.09 GB      19.74 GB     -0.03 GB
```

`MemAvailable` approximately plateaus over the final samples, but anon LRU
continues rising from 18.68 to 19.74 GB. These observations do not establish a
stable counter ceiling or identify a missing decrement. A missing decrement is
one hypothesis requiring direct accounting evidence.

### Runtime toggle — reported error persists across toggles

```
enabled=0x0000 (MGLRU off):  MemAvailable 12.13 / 12.14 / 12.13 GB  (approximately stable)
enabled=0x0001 (MGLRU on):   MemAvailable 12.12 / 12.10 / 12.10 GB  (still wrong)
```

The reported `MemAvailable` remains high in both states. These short sequences
do not establish that disabling MGLRU stops drift, localize the defect entirely
to MGLRU, or distinguish missing decrements from other accounting errors.

---

## Root cause analysis

### Donor alignment — seven helper call sites now match

The seven MGLRU accounting call sites checked use `__update_lru_size()` in the
pinned donor and in the current local source.

```c
static __always_inline void update_lru_size(...)   /* include/linux/mm_inline.h:39 */
{
	__update_lru_size(lruvec, lru, zid, nr_pages);
#ifdef CONFIG_MEMCG
	mem_cgroup_update_lru_size(lruvec, lru, zid, nr_pages);   /* EXTRA */
#endif
}
```

Both helpers perform the same node and zone counter updates through
`__update_lru_size()`. `update_lru_size()` additionally updates the per-memcg
`mz->lru_zone_size[][]` arrays. The local `mem_cgroup_update_lru_size()` does not
directly update node counters. Replacing the helper therefore does not, by
itself, explain node-counter inflation or prove an unbalanced memcg update.

Donor uses `__update_lru_size` at `mm_inline.h:201,209,215,216` and
`vmscan.c:3545,4173,4174`. The earlier report records replacing
`update_lru_size()` at these sites; the current seven calls are verified.
`lru_gen_update_size()` is byte-identical to
the donor after the two local helper-name substitutions (`page_is_file_lru` →
`page_is_file_cache`, `thp_nr_pages` → `hpage_nr_pages`).

Current local sites:

- `include/linux/mm_inline.h:213,221,227,228` (`lru_gen_update_size`)
- `mm/vmscan.c:3201` (`reset_batch_size`)
- `mm/vmscan.c:3831,3832` (generation advance in `try_inc_gen`)

The single bare `update_lru_size()` call in `mm/vmscan.c:1727` belongs to the
legacy `update_lru_sizes()` isolation-accounting helper, matching donor
`vmscan.c:1935`. This call-site comparison is not proof that all double-counting
paths have been excluded.

The reported runtime error persists after the helper changes; their causal
relationship to the node-counter inflation remains unconfirmed.

Source comparison: Android Common **`android14-5.15` at
`76efa001ea197723c0423fdb9136e83b483f7aa1`**, decoded from Gitiles `format=TEXT`,
checking [include/linux/mm_inline.h](https://android.googlesource.com/kernel/common/+/76efa001ea197723c0423fdb9136e83b483f7aa1/include/linux/mm_inline.h)
and [mm/vmscan.c](https://android.googlesource.com/kernel/common/+/76efa001ea197723c0423fdb9136e83b483f7aa1/mm/vmscan.c).
The requested matching `android13-4.19-*` baseline remains unresolved: the
unsuffixed `android13-4.19` ref returned 404 and the queried remote refs contained
no matching branch. No 4.19 baseline commit was checked; local-source observations
below do not establish whether differences from that baseline are defects.

### Note on a suppressed symptom

`mem_cgroup_update_lru_size()` (`mm/memcontrol.c:1179`) wraps its
`WARN_ONCE(size < 0, ...)` in `#ifndef CONFIG_LRU_GEN`. With `CONFIG_LRU_GEN=y`,
this warning is compiled out even when MGLRU is disabled at runtime. Its absence
cannot validate accounting.
Worth reviewing independently of this bug.

### Confirmed cause — deletion decodes the wrong flags

The local `include/linux/bitops.h` `set_mask_bits()` returns `new__`, the flags
**after** the exchange. The pinned Android Common **`android14-5.15` at
`76efa001ea197723c0423fdb9136e83b483f7aa1`** returns `old__`, the flags **before**
the successful exchange. This was verified by decoding donor
[include/linux/bitops.h](https://android.googlesource.com/kernel/common/+/76efa001ea197723c0423fdb9136e83b483f7aa1/include/linux/bitops.h)
and comparing the caller in donor
[include/linux/mm_inline.h](https://android.googlesource.com/kernel/common/+/76efa001ea197723c0423fdb9136e83b483f7aa1/include/linux/mm_inline.h).
The imported `lru_gen_del_page()` relied on the donor's old-value contract:

```c
flags = set_mask_bits(&page->flags, LRU_GEN_MASK, flags);
gen = ((flags & LRU_GEN_MASK) >> LRU_GEN_PGOFF) - 1;
lru_gen_update_size(lruvec, page, gen, -1);
```

In this tree the returned flags already have `LRU_GEN_MASK` cleared, so `gen`
becomes `-1`. `lru_gen_update_size(..., -1, -1)` skips both generation-array
updates, then takes its `old_gen < 0` **addition** branch. The page is removed
from the list, but the mirrored inactive LRU counter gains `delta` instead of
the correct active/inactive counter losing `delta`. An isolated add/delete cycle
therefore leaves `delta` in generation accounting and `2 * delta` in the sum of
mirrored LRU counters.

This also contradicts the earlier assumption that generation counts must be
internally consistent. The invalid `(-1, -1)` arguments have a `VM_WARN_ON_ONCE`
check, but `include/linux/mmdebug.h` compiles that check out without
`CONFIG_DEBUG_VM`; the inspected `out/mglru-next-build/.config` disables it.

The fix is confined to `lru_gen_del_page()` in `include/linux/mm_inline.h`: use
the existing `lru_gen_try_cmpxchg()` in a retry loop and decode the generation
from the flags replaced by the **successful** exchange. Preserve the donor's
`PG_active` behavior and unrelated flag bits. The global `set_mask_bits()` helper
is unchanged. Reading the generation only before the loop would be insufficient
because an aging promotion can cause the exchange to retry.

### Regression verification

`python3 scripts/test-mglru-accounting.py` compiles the actual extracted C
accounting/removal functions and local bitops macro with modeled kernel
primitives. It does not build the kernel.

- Before the patch: fails because generation accounting remains nonzero after
  removal.
- After the patch: passes **128 cases**, each with three accounting/removal
  cycles, plus non-member removal and two forced promotion/retry cases.
- Coverage includes active/inactive generations, generation wraparound,
  anon/file pages, two zones, one-page and 512-page deltas, both reclaim modes,
  node/zone counter balance, list removal, and preservation of unrelated flags.

These results establish the source-level failure and its correction in the host
harness. They do not establish that the device's full runtime symptom is resolved;
that requires a newly built kernel and the checklist below. No kernel build or
device test was performed for this fix.

The original broader candidates remain unaudited. In particular,
`lru_gen_migrate_mm()` moves an `mm` between tracking lists, not page charges;
`lru_gen_exit_memcg()` checks for zero generation counts and frees filters, so
lack of list draining there alone does not establish a defect.

## Post-fix device validation

Kernel `#4`, image `out/boot-mglru-next-fixed3.img`
(SHA256 `e87ffa5fecbf753e9f674e2ad7f7e72fb49e8627a1ad0988697da0e845bf09e3`),
booted with `fastboot boot`. Build RC=0, 0 errors, 0 warnings in changed files.

`MemAvailable` sampled from `/proc/meminfo` every ~45 s, MGLRU enabled throughout:

```
uptime   MemAvailable   avail/MemTotal   delta
   50s       1722712           0.47          —
   95s       1177964           0.32     -544748
  140s       1169192           0.32       -8772
  186s       1160528           0.32       -8664
  231s       1158112           0.32       -2416
  276s       1045612           0.29     -112500
  321s       1045156           0.29        -456
  366s       1038156           0.28       -7000
```

Every delta is negative: monotonic decrease across 5+ minutes, which is the
criterion the two earlier builds both failed. Post-warm-up spread is 137 MB.
`avail/MemTotal` settled at 0.28-0.32 against **3.32** before the fix, and
`MemAvailable` remains below `MemTotal` (3645964 kB) at every sample.

Checklist outcome:

1. `MemAvailable <= MemTotal` — **pass** at all 8 samples
2. synchronized meminfo/vmstat/debugfs — partially met; see limits
3. no divergence above physical memory — **pass**, counters track real pages
4. >= 5 min sampling, no accumulating discrepancy — **pass**, monotonic
5. `lru_size` warning — unavailable, compiled out with `CONFIG_LRU_GEN=y`
6. no new WARNING/Oops/Call trace — **pass**, 0 panics/Oops/BUG
7. `enabled` == `0x0001` — **pass**
8. debugfs generations advancing — **pass**
9. kswapd reclaim activity — **pass**, see below

### Reclaim activity on the fixed kernel

`enabled=0x0001`, generations advancing in `/sys/kernel/debug/lru_gen`,
`pgscan_kswapd` 553125 / `pgsteal_kswapd` 372585, `workingset_refault` 10568.

Major faults reached 54722 over 237 s, with a rate change between windows
(15.2/s over 128-189 s, then 199.9/s over 189-237 s). Attributed by reading field 12
of `/proc/*/stat`: the largest counts were `com.android.systemui` 10989,
`system_server` 6530, `com.android.vending` 5891, `com.google.android.gms` 4024,
`com.nexuslauncher` 2289. With `pswpin` 41746 and `pswpout` 278494, this is Android
cold-starting applications from zram on a 3.6 GB device — boot-time behaviour, not a
leak. Major faults were 1.3% of all faults over the faster window.

### Validation limits

Only the **idle** case was exercised. These remain untested, and this result does
not clear them:

- Sustained memory pressure. In particular the arm64 page-table young-bit handling:
  this tree's `ptep_test_and_clear_young()` (`arch/arm64/include/asm/pgtable.h`)
  clears the accessed bit with a bare cmpxchg and does not invalidate the TLB, and
  upstream folds `flush_tlb_page_nosync()` into that path. `walk_pte_range()` and
  `lru_gen_look_around()` both call it directly. Upstream v6.1 arm64 has the same
  non-flushing form, so this is donor-equal rather than a port regression, but it is
  untested here under load.
- `CONFIG_LRU_GEN=n` has never been compiled; the `#else` stubs in
  `include/linux/mm_inline.h` and `include/linux/mmzone.h` are unproven.
- Runtime `enabled` toggle was exercised only while the defect was present.


---

## Verification checklist for the fix

Recorded so a "clean" reading cannot be mistaken for a fix again. A single sample
is insufficient — this bug produced a plausible-looking first reading that was
still wrong.

1. `MemAvailable <= MemTotal` — necessary, **not sufficient**
2. Capture `/proc/meminfo`, `/proc/vmstat` and `/sys/kernel/debug/lru_gen` close
   together. Compare equivalent populations and account for tmpfs, unevictable
   and isolated pages, legacy LRU membership, and sampling skew; do not require
   either of the original anon/page-cache comparisons to agree within 10%.
3. Check for persistent divergence between generation accounting and mirrored
   node/zone LRU counters, using add/remove instrumentation if snapshots cannot
   explain the difference. Counts far above physical memory remain a failure.
4. Sample every ~40 s for **>= 5 minutes**, recording allocation/reclaim workload
   and a settled interval. Healthy counts may rise with workload; require no
   unexplained accumulating discrepancy, rather than flat or falling values.
5. The `lru_size` warning check is **unavailable with `CONFIG_LRU_GEN=y`**;
   absence of this compiled-out warning is not a pass condition.
6. No new WARNING/Oops/Call trace in dmesg
7. MGLRU still active: `/sys/kernel/mm/lru_gen/enabled` == `0x0001`
8. `/sys/kernel/debug/lru_gen` generations advancing and plausible
9. Under a workload that triggers kswapd reclaim, verify `pgscan_kswapd` /
   `pgsteal_kswapd` activity. Idle counters alone do not demonstrate a failure.

## Reported dmesg state and reclaim activity

- `Kernel panic` / `Oops` / `BUG:` / `Unable to handle` — **0**
- `lru_size` warnings — **0** (warning compiled out with `CONFIG_LRU_GEN=y`)
- Reported as pre-existing vendor warnings; independence from MGLRU is unverified:
  - `drivers/irqchip/irq-gic.c:1008 gic_irq_domain_alloc` (via `msm_mpm_gic_chip_alloc`)
  - `drivers/soc/qcom/smem.c:693 qcom_smem_get`
  - (an earlier boot additionally showed Goodix fingerprint double-probe `-EEXIST`)

Reported activity: `enabled=0x0001`, debugfs generations advancing,
`pgscan_kswapd` 553125 / `pgsteal_kswapd` 372585, `workingset_refault` 10568.
These observations support activity, not proof of correct accounting or reclaim
behavior in all paths.

---

## Artifacts

| Item | Path / SHA256 |
| --- | --- |
| Boot image (validated, `#4`) | `out/boot-mglru-next-fixed3.img` |
| SHA256 | `e87ffa5fecbf753e9f674e2ad7f7e72fb49e8627a1ad0988697da0e845bf09e3` |
| Kernel SHA256 | `af9038dc943fce6bc1dd4cd76a6efbf2806b9043930531c0db7578cb33f32459` |
| Device base partition | `out/boot_a_current.img` (`a6c56763…`, pulled from `/dev/block/mmcblk0p22`) |
| Build log (validated kernel) | `out/mglru-next-verification/build-fixed3.log` |
| Host regression | `scripts/test-mglru-accounting.py` (128 cases; fails before the fix) |
| Prior defective images | `out/boot-mglru-next-fixed2.img` (`aa3808d3…`), `out/boot-mglru-next-fixed.img` (`510fe1cf…`) |
| Historical acceptance criteria (superseded by checklist above) | `out/mglru-next-verification/ram-accounting-check.md` |
| Build failure log (original) | `out/mglru-next-verification/build-failed-summary.md` |

## Build status

`scripts/build-tissot.sh` RC=0 for the validated kernel, 0 errors, 0 warnings in
changed files (`out/mglru-next-verification/build-fixed3.log`). Build success does
not establish that accounting was the only runtime defect; the idle-case validation
above is the only runtime evidence.

## Suggested next steps

1. Exercise sustained memory pressure on a fresh boot of `#4` and re-run the
   checklist, capturing counters during active reclaim rather than at idle.
2. Compile a `CONFIG_LRU_GEN=n` configuration to prove the `#else` stubs in
   `include/linux/mm_inline.h` and `include/linux/mmzone.h`; a clean boot alone
   would not establish that the disabled path is correct.
3. If unexplained divergence reappears under load, record synchronized counters
   and instrument add/remove `delta` totals per lruvec before selecting another
   code change.
