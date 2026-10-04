# MGLRU port for tissot 4.19

## Scope and source

Work on `mglru-test`, retaining the approved swappiness 100, watermark scale 200, PSI/userspace lmkd and balanced anonymous/file reclaim baseline.
Port the complete page-based MGLRU series, including aging, eviction, refault feedback, reverse-map locality, page-table walking, memcg integration, runtime switch, thrashing prevention and debugfs.

Donor: shinichi-c/Dynamic_kernel_4.19_oneplus_sdm845, commits ae75c1a83c1b76c33e64c3637fda8505da86d975 through c0aff1f77c194400f41b39a451c7b9d78462c7ef (26 prerequisite/implementation commits). The implementation retains Yu Zhao authorship and March 2022 mailing-list provenance; it is a 4.19 adaptation, not a direct import of the current Android Common Kernel implementation.

## Compatibility decisions

- Use this tree's include/linux/pgtable.h and mmap_lock names.
- Preserve already backported architecture helpers and LRU cleanup.
- Move legacy workingset bucket scaling out of shared shadow packing so generation/refault tokens retain their bits.
- Permit generation/reference flags in FUSE page checks.
- Register new exec address spaces before use, after IRQ re-enable and while the task allocation lock is held.
- Retain radix-node preloading for empty swap slots; replace existing XArray shadow values without allocation.
- Bound swap shadow cleanup by the current iterator index before deleting a slot.
- Include donor Qualcomm fixes from 59a4952e7940da5223a5c28ef8c0c348febb6e5c. The speculative-fault patch is unnecessary here because this tree has no speculative-fault implementation.
- Enable CONFIG_LRU_GEN and CONFIG_LRU_GEN_ENABLED for tissot; leave detailed history statistics disabled. Label builds -perf-mglru-test.
- Runtime fallback: /sys/kernel/mm/lru_gen/enabled = 0; do not change zram compression, size or Simple LMK.

## Implementation and checks

1. Preserve the baseline diff and donor series in /tmp/tissot-mglru; adapt prerequisite and complete MGLRU patches.
2. Resolve rejected hunks against current APIs; inspect shadow encoding, page flags, mm lifetime and lock ordering.
3. Generate the three tissot config fragments and compile Image.gz-dtb with the existing NDK LLVM toolchain. Resolve concrete compiler errors.
4. Verify enabled/disabled MGLRU configurations, inspect linked symbols and runtime interfaces, run diff/patch checks, then package the build.
5. Report build evidence and remaining hardware verification. A successful build proves buildability; boot stability and performance require a subsequent temporary boot and app test.

The user authorized commands and edits scoped to this port on 2026-10-04. No phone boot or flash is part of implementation verification.

## Fixes: what changed and why

| Area / files | Problem | Change and reason |
| --- | --- | --- |
| `include/linux/pgtable.h`, `arch/arm64/include/asm/{cpufeature,pgtable}.h` | Donor includes the old `asm-generic/pgtable.h`; this tree already moved generic helpers. MGLRU needs to know whether the CPU updates access bits in hardware. | Integrate helpers into the existing header and expose `cpu_has_hw_af()` to MGLRU. Keep existing non-leaf helpers instead of applying duplicate patches. |
| `mm/vmscan.c` | Donor page-table walks use `mm->mmap_sem`; this tree uses `mmap_lock`. | Use the current lock member. Retain aging, eviction, refault feedback, rmap locality and page-table walking; this is the complete older implementation, not just a tuning knob. |
| `fs/exec.c`, `kernel/{fork,exit}.c`, `kernel/sched/core.c`, `mm/memcontrol.c` | Address spaces need registration, migration and removal for generation walkers. The imported exec hunk only marked usage and did not register this tree's new exec mm. | Initialize/register forked mm lists, register new exec mm before marking it used, move mm lists with their owning memcg, and remove them during destruction. Exec registration is after IRQ re-enable and under task allocation lock, matching the later locking fix's intent. |
| `mm/workingset.c` | Shared shadow packing right-shifted values by `bucket_order`. Generation/refault tokens need their low bits; the imported legacy eviction path also already shifted timestamps. | Move timestamp scaling entirely to the legacy caller and leave shared packing unscaled. This avoids both corrupt generation tokens and double-scaling legacy timestamps. |
| `mm/memory.c`, `mm/swap_state.c` | Old `radix_tree_exceptional_entry()` and `__radix_tree_create()` APIs are unavailable. An initial conversion to `__xa_store(GFP_ATOMIC)` compiled but bypassed radix preloads, weakening allocation reliability under pressure. | Use `xa_is_value()` for shadow identification. Replace existing shadow slots without allocation; use the existing preloaded radix insertion path for empty slots. Preserve the callers' allocation guarantees. |
| `mm/swap_state.c:clear_shadow_from_swap_cache()` | `iter.next_index` denotes the end of an entire radix chunk, not the current slot. Testing it after deletion could stop early or delete a shadow beyond the requested range. | Check `iter.index > end` before touching each slot. The regression reproduced premature stopping before this fix. |
| `fs/fuse/dev.c`, page flags/layout and `kernel/bounds.c` | MGLRU adds generation/reference bits to pages. Old FUSE validation would reject valid pages; insufficient bit space must be caught at compile time. | Accept the new bits and integrate their widths with existing flags and generated bounds. |
| `mm/swap.c`, `mm/vmscan.c`, `include/linux/vm_event_item.h`, `mm/vmstat.c` | The original older series needed Qualcomm baseline corrections for active-page insertion, aging when swap is unavailable and no-progress behavior. | Include donor commit `59a4952e...`, adapt its VMA API, and expose its diagnostic VM events for later device tests. |
| `kernel/fork.c` | A donor hunk also added unrelated `CONFIG_PERF_HUMANTASK` initialization. | Remove that donor-specific addition; it is not part of MGLRU. |
| tissot configuration | An experimental kernel should be identifiable and permit fallback. | Enable MGLRU by default, disable detailed history statistics, retain 100/200 defaults, and label the release `-perf-mglru-test`. |

## Progress and verification (2026-10-04)

- Created and switched to `mglru-test`; the port and tuning are currently uncommitted workspace changes.
- Captured the pre-port tuning diff in `/tmp/tissot-mglru/baseline-tuning.patch` before editing.
- Imported 26 prerequisite/implementation patches and the Qualcomm follow-up, resolved contextual differences, then reviewed critical lifecycle and swap paths.
- Initial compile exposed removed radix-tree APIs. Fixed the API adaptations; the later read-only review identified the preload and cleanup issues above.
- Using `scripts/build-tissot.sh` for final verification and packaging, as requested. Final script runs completed with exit 0; latest evidence is `out/mglru-verification/build-script-final.log`.

### Completed checks

- Full enabled build: NDK 29 clang, ARCH=arm64 LLVM=1 LLVM_IAS=1, make O=out -j8 CC=clang Image.gz-dtb, exit 0.
- Disabled configuration: compile the changed memory-management, process-lifecycle, scheduler, FUSE and arm64 feature objects in a separate output directory, exit 0. This is a compile check of affected objects, not a second complete disabled kernel image.
- `python3 scripts/test-mglru-shadow.py`: actual-source host checks of swap range cleanup, live-page preservation, cross-space cleanup and 1,024 shadow token round trips. The cleanup check failed before the boundary fix and passes after it. These tests use modeled iterator/storage primitives; they do not establish hardware reclaim or boot stability.
- Final read-only review found the two swap issues, confirmed their fixes, and identified no further concrete blocker in reviewed paths.
- Verification logs and exact donor patches: out/mglru-verification/. The source patch there excludes new untracked files; use the workspace and documented donor sources for the full port.
- `git diff --check` passes. Checkpatch reports imported debug-assertion and short Kconfig-help warnings; its complex-value error on the nested `for_each_gen_type_zone` loop macro is a false positive (it is a statement iterator, not an expression). This is not a warning-free checkpatch result.

## Hardware follow-up

Use a temporary boot of the packaged kernel before permanent flashing. Check uname for -perf-mglru-test; inspect /sys/kernel/mm/lru_gen/enabled and min_ttl_ms, dmesg warnings, zram counters and app retention. Hardware access-bit support determines which page-table-walking capability is available; the generation core can operate through reverse mappings.
Repeat the existing 14-launch test. If necessary compare with enabled=0 on the same kernel. Booting, writing runtime settings and flashing are outside this buildability check.

## Final artifacts

- Release: `4.19.325-cip136-st20-perf-mglru-test-ga8f025fb9452-dirty`.
- Kernel image: `out/arch/arm64/boot/Image.gz-dtb`, SHA256 `459cbfffe410ef5df0927e96e2ecec760929c68b3b9b645e4c78adab3f6cc001`.
- Flashable ZIP: `out/tissot-4.19.325-cip136-st20-perf-mglru-test-ga8f025fb9452-dirty.zip`, SHA256 `1ba12abd8553cfef8d3619384ec1d4a7cc8fee91ec860a01120c469961f5f9cf`.
- Validated arm64 image header, gzip round trip against the built Image, appended DTB magic, ZIP integrity and exact kernel payload match.
- Final build entry point: `CCACHE_DIR="$PWD/out/ccache-mglru" JOBS=8 scripts/build-tissot.sh`, exit 0. The workspace cache override keeps build writes inside the permitted directory; it is not needed for normal local builds.
- Ready for hardware testing; device boot and stability are not established by these build and host checks.

## Temporary boot image

- Image: `out/boot-mglru-test.img`, 34584576 bytes, boot header v0.
- SHA256: `d5b1aca3fa01bb25eb2c59ffa66e565d2e1a6aa5f40607b896caa9cf75c3475b`.
- Base: the phone's previously captured Magisk boot image (`boot_a_current.img`, SHA256 `2ef7f0844d556cb81cb62476d73514f23e4b4a1c053be7776f5496a7119f773d`). Only the kernel was replaced.
- Repacking the original kernel and zero-padding to the captured partition size reproduced the original image byte-for-byte. The MGLRU image was unpacked again: kernel matches the final build, ramdisk matches the base, other mkbootimg arguments are unchanged, and the image fits the original partition.
- Prepared for a live test; not booted or flashed by this session.

Once the phone is in bootloader mode:

```sh
fastboot -s 2819f2320604 boot out/boot-mglru-test.img
```

This command temporarily boots the image. A normal reboot returns to the installed boot image.
