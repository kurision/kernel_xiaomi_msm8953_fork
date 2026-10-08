# Handoff — Mi A1 (tissot) 4.19 kernel: OC/UC/UV, repartition, flashing

## Latest session — MGLRU test branch (2026-10-04)

This section supersedes the old snapshot below. Full port notes, fixes and verification: [mglru-port-design.md](mglru-port-design.md).

### Pause / resume tomorrow

- The user temporarily booted the new image and then requested a handoff before sleeping. **Initial boot is verified; sustained stability and controlled app tests remain pending.** See [mglru-test-report.md](mglru-test-report.md).
- Confirmed Mi A1 serial `2819f2320604`, release `4.19.325-cip136-st20-perf-mglru-test-ga8f025fb9452-dirty`, boot completion `1`, MGLRU enabled `0x0001`, `min_ttl_ms=0`, swappiness `100`, watermark scale `200`.
- No permanent flash was performed in this session. A normal reboot returns to the installed boot image; recheck the running release before testing tomorrow. Do not assume the phone is still on the temporary kernel.
- Saved capture: `out/mglru-live/20261004-004824/{start-state.txt,kernel.log,android.log}`. It includes boot messages and ends around 00:51:41 phone time / 281 seconds uptime. **Collectors are stopped; no overnight capture is active.** Their original host PIDs no longer exist. The reason they stopped was not established.
- Captured three lmkd kills: Magisk and LineageOS settingsconfig during boot (low watermark plus low swap), then carrierconfig (low watermark). No captured kernel panic, Oops or kernel OOM kill; existing IRQ/SMEM warnings remain. This short window cannot establish overnight stability.
- At a later read, zram used 565,828 KiB swap (~552.6 MiB); original data 578,318,336 bytes (~551.5 MiB), physical storage 177,164,288 bytes (~169.0 MiB). No controlled 14-launch comparison was run on MGLRU yet.
- Tomorrow: pin all adb commands to `2819f2320604` (a Pixel may also be connected), check release/uptime/boot completion, collect dmesg/logcat and available pstore evidence before rebooting if a crash is suspected, then restart capture. Repeat `scripts/test-tissot-memory.sh` with current 100/200 settings and compare retention, kills, PSI, reclaim and launch times with the pre-port runs below. Consider a fresh-boot MGLRU-disabled comparison only if needed.
- Keep the source on `mglru-test`; changes remain uncommitted. Do not rebuild or flash merely to resume logging. Latest workspace instructions require explaining and confirming each file edit, and prohibit a build unless requested.

### Current progress

- Active branch: **`mglru-test`**, created from `oc-test` at `a8f025fb9452`. Tuning, port and scripts are currently uncommitted.
- **MGLRU port implemented.** Complete older page-based series adapted to this 4.19 tree, with Qualcomm follow-up fixes, runtime switch and debugfs.
- **Final `scripts/build-tissot.sh` build and ZIP packaging succeeded (exit 0).** Latest log: `out/mglru-verification/build-script-final.log`.
- MGLRU-disabled affected-object compile checks and actual-source swap-shadow host checks passed. Build success establishes buildability, not device boot stability or performance.
- The MGLRU image has now booted temporarily and its running release and enabled state were verified. No permanent flash was performed; controlled testing remains pending.

### Memory findings before the port

- Simple LMK's raw-pressure tuning still killed apps early, including on empty noncritical reclaim reports. Returned to userspace lmkd on `oc-test`, with PSI and `CONFIG_BALANCE_ANON_FILE_RECLAIM=y`.
- Backported the swappiness 0..200 range from the Android Common Kernel 5.4 change; keep default 100. Global sysctl, memcg validation and documentation updated.
- Pixel 7 Pro inspection: Sultan 6.1, swappiness 60, watermark scale 200, `lz77eh`, MGLRU configured enabled, Simple LMK active. At inspection its zram was approximately 87% used after almost 24 hours. This is a different workload and kernel, not proof that copying one value reproduces its behavior.
- Three fresh-boot Mi A1 runs, each the same 14 launches (13 distinct apps):

| Swappiness / watermark scale | lmkd kills during test | Original app PIDs retained | Final zram original data | Median launch time | Full memory stall time / window |
| --- | --- | --- | --- | --- | --- |
| 100 / 20 | 10 | 12/13 | 266 MiB | 961 ms | 1.19% |
| 100 / 200 | 0 | 13/13 | 386 MiB | 978 ms | 1.85% |
| 60 / 200 | 0 | 13/13 | 226 MiB | 1,027 ms | 1.51% |

Both watermark-200 runs had zero additional direct reclaim during launches. One run per setting and rising battery temperature (35.7 to 37.5 C) limit performance conclusions. The approved kernel defaults are now **100 / 200**; higher zram occupancy is not itself the success criterion.

Logs: `out/memory-tests/20261004-000115-swappiness-100-watermark-20-Qxmbv1/`, `20261004-000454-swappiness-100-watermark-200-edIYNB/`, `20261004-000831-swappiness-60-watermark-200-rbiytJ/`.

### Scripts

- `scripts/build-tissot.sh`: merges tissot fragments, builds `Image.gz-dtb`, then packages the ZIP. Use this for normal builds.
- `scripts/package-tissot.sh`: packages the latest existing build output; verifies ZIP contents and kernel payload.
- `scripts/test-tissot-memory.sh [SWAPPINESS [WATERMARK_SCALE_FACTOR]]`: repeats 14 launches, records continuous lmkd logs and memory/process snapshots, restores temporary values on exit.
- `python3 scripts/test-mglru-shadow.py`: runs actual-source host regressions for shadow cleanup and token encoding.

### Main port fixes

- Adapt existing page-table headers and mmap-lock names.
- Register exec address spaces before use, outside the IRQ-disabled region; retain task-lock protection.
- Preserve generation-token bits and single scaling of legacy workingset timestamps.
- Recognize XArray shadow values without bypassing the swap insertion preload mechanism.
- Fix shadow-range cleanup to bound the current slot before deletion; regression failed before the fix and passed afterward.
- Accept generation/reference page flags in FUSE checks, and add compile-time layout constraints.
- Preserve baseline tuning, remove unrelated donor fork additions, and label test builds `-perf-mglru-test`.

### Built artifacts

- Kernel release: `4.19.325-cip136-st20-perf-mglru-test-ga8f025fb9452-dirty`.
- Image: `out/arch/arm64/boot/Image.gz-dtb`.
- Flashable ZIP: `out/tissot-4.19.325-cip136-st20-perf-mglru-test-ga8f025fb9452-dirty.zip`.
- ZIP SHA256: `1ba12abd8553cfef8d3619384ec1d4a7cc8fee91ec860a01120c469961f5f9cf`.
- ZIP integrity, exact payload match, gzip image and appended DTB were verified. Temporary device boot was subsequently verified; permanent flashing remains untested.

### Temporary boot image ready

- `out/boot-mglru-test.img`, SHA256 `d5b1aca3fa01bb25eb2c59ffa66e565d2e1a6aa5f40607b896caa9cf75c3475b`.
- Preserves the captured phone boot image's Magisk ramdisk and boot parameters; only its kernel was replaced. Verified byte-identical old-kernel round trip, new kernel/ramdisk contents and partition-size fit.
- In bootloader mode: `fastboot -s 2819f2320604 boot out/boot-mglru-test.img`. This does not flash; reboot returns to the installed image.

### Next device checks

Initial temporary boot and enabled-state checks passed. Next repeat the existing app test, inspect reclaim counters and monitor for warnings under load. CPU access-bit support may leave page-table walking unavailable while the generation core still operates; the observed enabled mask is `0x0001`. Compare with the runtime switch set to 0 if needed. Zram remains LZ4; `lz77eh` was not ported. Permanent flashing and sustained hardware stability remain unverified.

## Historical handoff (older snapshot)

State as of 2026-10-03 ~21:20. Full technical write-up: `docs/oc-uc.md`.

## Current device state (verified over adb)

- **ROM:** EvolutionX 17.0 (2026-09-28, tissot), flashed via fastboot to **slot a only** (slot a active).
  **Slot b has no ROM** (only the old partition contents moved away) — no fallback slot yet.
- **Kernel:** our build #3 (`4.19.325-cip136-st20-perf-g9d3bf7da9553-dirty`, Oct 3 20:57),
  flashed with `tissot-oc-20261003-2100.zip`. Boots, all OC/UC/UV features verified (see below).
- **Root:** Magisk in boot ramdisk; Magisk app reinstalled; `adb shell su` granted.
- **Partition table:** repartitioned with our `Xiaomi_mi_a1_reclaim_hole.zip`
  (userdata 45.24 → 50.79 GB; Settings "System" ~19 → ~13.2 GB). Verified on device.
- **Thermal HAL:** not shipped by this EvolutionX build (ROM-side). `thermal-engine` +
  kernel thermal zones do the throttling.

## Verified on device after flashing the kernel

| Item | Result |
| --- | --- |
| CPU freqs | 480 … 2400 MHz (15 steps), all used (time_in_state) |
| GPU freqs | 100 … 725 MHz, governor msm-adreno-tz |
| `UV_mV_table` | 15 lines, 2400mhz 1140 mV … 480mhz 650 mV |
| CPR stock corners | identical to pre-OC values (650/700/770/820/870/935/955 mV) — extrapolation fix correct |
| CPR OC corners | 2150.4: 1030 (last 1020), 2208: 1055 (1045), 2304: 1100 (1095), 2400: 1140 cap (1110) mV |
| logcat | no FATAL EXCEPTION / native crashes |

## Open items (prioritised)

1. **`mm/memcontrol.c:1190` WARNING `lru_size -1`** (memcg LRU underflow in OOM-reaper path,
   `perfetto_hprof_`), plus lmkd killing ~8 cached apps 55–59 s after boot (MemFree 69 MB).
   Not from OC work. Prime suspect: **pre-existing uncommitted mm changes**
   (`include/linux/pageblock-flags.h`: `pageblock_order` → `PAGE_ALLOC_COSTLY_ORDER`;
   `mm/page_alloc.c`: watermark_boost_factor = 0). Proposed next step (offered, not started):
   build with only those two reverted, compare warning + boot-time kills.
2. **Populate slot b** for a fallback:
   `fastboot flash boot_b ~/development/kernel/evox_images/boot.img` and
   `fastboot flash system_b ~/development/kernel/evox_images/system.img`
   (then flash the kernel zip on slot b too if wanted).
3. **Stability testing** of OC steps (2304/2400 MHz) under sustained load — `docs/oc-uc.md` §6.
4. Harmless pre-existing boot warnings (no action needed): `irq-gic.c:1008` (DT interrupt
   mapping, 0.16 s) and `smem.c:693` (`msm_pil_init` early smem read).
5. Side findings from before the OC work: suspend-abort loop (`wcnss_wlan_suspend_noirq`
   -1, `alarmtimer` -EBUSY); sepolicy denials for apps reading `sysfs_kgsl`.

## Follow-up session (2026-10-03 evening)

- GPU appeared stuck at 650 MHz: it woke from slumber at `qcom,initial-pwrlevel` = 650 MHz.
  Now 320 MHz (`oc.dtsi`). When idle, `gpuclk` shows a stale value; the real clock is gated.
- Android 16 boosts tasks via `cpu.uclamp.*`, which didn't exist (`SCHED_TUNE=y`). Switched
  to `UCLAMP_TASK` + `UCLAMP_TASK_GROUP`, and patched the WALT `sugov_get_util()` path to
  keep the WALT signal and apply uclamp (`docs/oc-uc.md` §4.7).
- Default cpufreq governor is now schedutil (was performance), and the default I/O
  scheduler is kyber (measured, §4.10).
- **Not yet built or flashed.** After flashing, check that `/dev/cpuctl/top-app/cpu.uclamp.min`
  exists, then check GPU scaling and battery over a day.
- All work is committed, one commit per file. `origin` is now
  `git@github.com:kurision/kernel_xiaomi_msm8953_fork.git` (not pushed).

## Work done in the first session

| File | Change |
| --- | --- |
| `drivers/regulator/cpr4-apss-regulator.c` | Fmax corner from `fuse_corner_map`; extrapolate voltage + quotients above Turbo |
| `drivers/regulator/cpr3-regulator.{c,h}`, `include/linux/regulator/cpr3-uv.h` | `cpr3_regulator_get_corner_limits()` / `set_corner_ceiling()` (shifts CPR window + target quotients), `uv_adjust_volt` |
| `drivers/clk/msm/clock-cpu-8953.c` | HFPLL 480–2400 MHz; `UV_mV_table` attr (`include/linux/clk/msm8953-cpu-uv.h`) |
| `drivers/clk/msm/clock-gcc-8953.c` | 725 MHz GPU row |
| `drivers/cpufreq/qcom-cpufreq.c` | registers `UV_mV_table` |
| `drivers/clk/msm/Kconfig`, `arch/arm64/configs/vendor/tissot.config` | `CONFIG_MSM8953_CPU_VOLTAGE_CONTROL=y` |
| `arch/arm64/boot/dts/vendor/qcom/mi8953/tissot/oc.dtsi` (+ include in `tissot.dtsi`) | CPU/CCI/CPR/GPU/thermal-floor/energy-model tables |
| `techpack/audio-legacy/Makefile` | **build-speed fix**: bare `export` → export only `CONFIG_*` from `sdm450auto.conf` (bare export forced `size_append` `$(shell)` loop per object → ~1 object/min) |
| `docs/oc-uc.md`, `docs/HANDOFF.md` | documentation |

Changes that predate the first session (now committed separately): `.gitignore`, `tissot/misc.dtsi`
(pa-therm0 delete), `msm8953-gpu.dtsi` (gpu_opp_table), `tissot-titanium.dts` (model name),
`qpnp-smbcharger.c`, `pageblock-flags.h`, `sched-pelt.h`, `page_alloc.c`.

## Artifacts outside the repo (`~/development/kernel/`)

| Path | What |
| --- | --- |
| `tissot_backup_20261003/` | **Keep.** Verified raw images of all 50 partitions except userdata, `gpt_primary.bin` / `gpt_backup.bin` (pre-repartition GPT), `partitions.txt`, `SHA256SUMS`, `backup.sh` |
| `Xiaomi_mi_a1_reclaim_hole.zip` + `tissot_reclaim_zip/` | Repartition zip (applied). README has rollback `dd` commands. `extract_payload.py` = payload.bin extractor with hash verification |
| `Xiaomi_mi_a1_4GB_System.zip` | Original 4 GiB repartition zip (cause of the 6.5 GB hole) |
| `evox_images/` | `boot.img`, `system.img` extracted from EvolutionX OTA (hash-verified) — needed for slot b |
| `AnyKernel3/` | Configured for tissot (explicit block path, `IS_SLOT_DEVICE=1`, `split_boot`/`flash_boot`) |
| `tissot-oc-20261003-2100.zip` | Flashed kernel zip |
| `Lucifer-AnyKernel3/`, `LuciferKernel/` | Reference (Lucifer's AK3 fork + 4.9 kernel, branches OC/OC-reb/…) |

## Build / flash cheat-sheet

```sh
export PATH="$HOME/Android/Sdk/ndk/29.0.14206865/toolchains/llvm/prebuilt/linux-x86_64/bin:$PATH"
export ARCH=arm64 LLVM=1 LLVM_IAS=1
make O=out vendor/msm8953-perf_defconfig vendor/mi8953.config vendor/tissot.config
make O=out -j"$(nproc)" CC="ccache clang" Image.gz-dtb      # no =m drivers in config
cp out/arch/arm64/boot/Image.gz-dtb ../AnyKernel3/ && cd ../AnyKernel3 && \
  zip -r9 ../tissot-oc-$(date +%Y%m%d-%H%M).zip * -x .git README.md '*placeholder'
```

- Device boots **boot header v0, gzip kernel + appended DTB** (`Image.gz-dtb`), A/B, no dtbo/vendor_boot.
- `CONFIG_INITRAMFS_IGNORE_SKIP_FLAG=y` → no `skip_initramfs` hexpatch needed (Lucifer's AK3 did that for 4.9).
- EvolutionX OTA = payload with **boot + system only**; vendor lives in system (`/vendor -> /system/vendor`);
  `vendor_a/b` partitions are unused by this ROM.
- Rollback kernel: `fastboot flash boot_a ~/development/kernel/evox_images/boot.img`.

## Gotchas learned

- adb shows `offline` after mode switches (Android ↔ recovery ↔ sideload) → `adb kill-server`.
  With both USB and wireless debugging attached, pin with `ANDROID_SERIAL=2819f2320604`.
- OrangeFox R12 file browser/sideload misbehaved for the ROM zip → used fastboot with extracted images.
- The repartition zip's bundled `sgdisk` (0.8.10.2 Android build) accepts **long options only**
  and `--verify` exits 0 even on problems (parse output). It can't run on host qemu (bionic).
- Loop-device testing on the phone needs the backing file relabelled (`chcon u:object_r:magisk_file:s0`).
- `UV_mV_table` writes: exactly 15 values, highest freq first; not persistent across reboot.
