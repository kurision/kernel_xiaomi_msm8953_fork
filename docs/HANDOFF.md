# Handoff — Mi A1 (tissot) 4.19 kernel: OC/UC/UV, repartition, flashing

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
| `drivers/regulator/cpr3-regulator.{c,h}`, `include/linux/regulator/cpr3-uv.h` | `cpr3_regulator_get_corner_limits()` / `set_corner_ceiling()`, `default_floor_volt` |
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
