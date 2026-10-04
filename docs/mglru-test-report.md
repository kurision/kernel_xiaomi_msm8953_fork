# Mi A1 MGLRU build and initial boot report

Date: 2026-10-04. Session paused at the user's request; continue with controlled device tests tomorrow.

## Result and limits

The kernel builds, packages and boots on the Mi A1. MGLRU's generation core is enabled. The short captured boot/use window contains no kernel panic or Oops, but includes three userspace lmkd kills and existing platform warnings. App retention, performance and sustained stability have not been established for this port.

No permanent flash was performed in this session. The user temporarily booted `out/boot-mglru-test.img`; a normal reboot returns to the installed boot image. Source changes are uncommitted on `mglru-test`, based on `oc-test` at `a8f025fb9452`.

## Changes and rationale

- Ported the complete older March 2022 page-based MGLRU series through a 4.19 donor, including Qualcomm follow-up fixes. This adds generation aging, eviction and refault feedback for memory reclaim; it is not the latest Android mainline implementation.
- Adapted page-table headers, CPU access-bit detection and mmap-lock names to this tree. Registered new exec address spaces after IRQ re-enable under the task lock so walkers have the correct lifecycle and locking.
- Preserved low bits in generation shadow tokens and moved legacy timestamp scaling to its caller. This avoids token corruption and duplicate scaling.
- Kept preloaded radix insertion for new swap-cache entries and allocation-free replacement of shadow entries. This preserves the existing allocation guarantees under memory pressure.
- Fixed swap-shadow cleanup to check the current iterator slot before deletion. The host regression demonstrated premature stopping before the fix and passed afterward.
- Accepted MGLRU page flags in FUSE and integrated flag layout checks; removed unrelated donor fork changes.
- Retained PSI/userspace lmkd, LZ4 zram, swappiness 100 and watermark scale 200. The earlier Simple LMK trial killed background apps too readily; earlier controlled tests favored watermark 200 for retention. Higher zram occupancy alone is not proof of improvement.

Full provenance, file locations and explanations: [mglru-port-design.md](mglru-port-design.md). Resume checklist and earlier memory comparisons: [HANDOFF.md](HANDOFF.md).

## Build verification

| Check | Evidence / scope |
| --- | --- |
| Final build and packaging | `scripts/build-tissot.sh`, exit 0; `out/mglru-verification/build-script-final.log` |
| MGLRU disabled | Affected objects compiled successfully in a separate output directory; not a complete disabled kernel image |
| Swap-shadow host regression | `scripts/test-mglru-shadow.py` passed actual-source cleanup and 1,024 token round trips with modeled storage primitives |
| Review | Two swap issues identified and fixed; subsequent review found no further concrete blocker in reviewed paths |
| Image / ZIP | ARM64 header, gzip round trip, appended DTB, ZIP integrity and exact kernel payload verified |
| Boot repack | Original-kernel round trip reproduced the captured image byte-for-byte; test kernel matches build, Magisk ramdisk and other boot arguments preserved |
| Source checks | `git diff --check` passed; checkpatch has imported warnings and one nested-loop macro false positive, so it is not warning-free |

These checks establish buildability and targeted correctness; device reclaim behavior requires the tests below.

## Initial device observations

Phone serial: `2819f2320604`. Confirmed running release:

`4.19.325-cip136-st20-perf-mglru-test-ga8f025fb9452-dirty`

| Observation | Value |
| --- | --- |
| Boot complete | `sys.boot_completed=1` |
| MGLRU enabled mask | `0x0001` (generation core enabled; optional page-table-walk acceleration bits not enabled) |
| Minimum TTL | `0` ms |
| Swappiness / watermark scale | `100 / 200` |
| Early check at 39.10 s | MemAvailable 2,202,284 KiB; zram not yet active |
| Capture-start snapshot at 84.58 s | MemAvailable 1,115,524 KiB; swap used 137,416 KiB; zram original data 139,694,080 bytes |
| Reclaim counters at 84.58 s | `pgscan_direct=0`, `pgsteal_direct=0`, `allocstall_dma32=0`, `oom_kill=0` |
| PSI totals at 84.58 s | some 1,706,285 us; full 455,451 us (cumulative, not a controlled test interval) |
| Later zram read | Swap capacity 2,734,468 KiB; used 565,828 KiB (~552.6 MiB); original data ~551.5 MiB; compressed data ~160.6 MiB; physical storage ~169.0 MiB |

Snapshots were taken at different times during boot and ordinary use. They must not be treated as a standardized app-launch benchmark.

### Captured kills and warnings

Saved logs: `out/mglru-live/20261004-004824/`.

| Phone log time | lmkd victim | Reported reason |
| --- | --- | --- |
| 00:48:04.242 | `com.topjohnwu.magisk` | Low watermark breached and swap low: 258,048 KiB below 273,444 KiB threshold |
| 00:48:05.110 | `org.lineageos.settingsconfig` | Low watermark breached and swap low: 170,368 KiB below 273,444 KiB threshold |
| 00:50:32.257 | `com.android.carrierconfig` | Low watermark breached |

The early swap-low reports occur while swap is coming online; they do not demonstrate that the fully initialized zram device was exhausted. The available evidence does not establish their precise cause or justify a new tuning change yet.

Kernel warnings include two `gic_irq_domain_alloc` warnings at `drivers/irqchip/irq-gic.c:1008` and one `qcom_smem_get` warning at `drivers/soc/qcom/smem.c:693`, consistent with earlier platform warnings. Other messages include the initial-console warning, legacy capability warning and repeated DevCheck SELinux denials reading GPU frequency. No captured panic or Oops was found. There is no identified MGLRU-specific warning in this window.

### Capture status at pause

`start-state.txt` records the initial memory/reclaim snapshot. `kernel.log` includes the existing boot ring buffer and streamed dmesg; `android.log` includes Android buffers and streamed logcat. Logs end around 00:51:41 phone time / 281 seconds uptime.

**Both host collectors have stopped; no overnight capture is active.** Original host PIDs 2021292 and 2021293 were absent when checked. The stop cause was not established. Lack of later log entries is not evidence of overnight stability.

## Artifacts

| Artifact | Path / SHA256 |
| --- | --- |
| Kernel | `out/arch/arm64/boot/Image.gz-dtb` — `459cbfffe410ef5df0927e96e2ecec760929c68b3b9b645e4c78adab3f6cc001` |
| Flashable ZIP | `out/tissot-4.19.325-cip136-st20-perf-mglru-test-ga8f025fb9452-dirty.zip` — `1ba12abd8553cfef8d3619384ec1d4a7cc8fee91ec860a01120c469961f5f9cf` |
| Temporary boot image | `out/boot-mglru-test.img` — `d5b1aca3fa01bb25eb2c59ffa66e565d2e1a6aa5f40607b896caa9cf75c3475b` |

## Tomorrow's checks

1. Pin adb to `2819f2320604`; the Pixel may also be connected. Recheck running release, uptime and boot completion. Do not assume the temporary kernel survived a reboot.
2. If a crash or reboot occurred, save current dmesg, Android logs and available pstore evidence before another reboot; then restart continuous capture.
3. On a fresh boot with 100/200 settings, repeat `scripts/test-tissot-memory.sh` and record kills, retained original app PIDs, launch times, zram, PSI and direct reclaim. Compare against the documented pre-port 14-launch runs.
4. If results warrant it, compare MGLRU disabled on the same kernel using an equivalent fresh-boot workload. Record temperature and test duration; one sample cannot establish a speed improvement.
5. Continue ordinary-use monitoring before permanent flashing. No rebuild is needed just to restart capture or test the existing image.

Latest workspace instructions require explaining and confirming file edits and prohibit starting a kernel build unless requested.
