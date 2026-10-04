# Mi A1 (tissot) mainline port — findings, blockers, progress

## Current status

Milestone 1 (research + build, **no flashing**) is complete. The question was: what would it take to run a kernel newer than the CAF 4.19 currently on this phone, while keeping the ROM on it.

Short answer, measured rather than guessed:

- The ROM (Evox 12.2, Android 17) ships **zero kernel modules** — every CAF driver is built into the kernel image, so there is no module set to carry over to a different kernel.
- **No CAF kernel newer than 4.19 exists for SDM625.** Not a "not yet built" gap: the branches do not exist upstream.
- Mainline 6.12 for this device builds fine and is a real option **for a Linux userland**, but it cannot host this ROM's userland, because the ROM's vendor stack is prebuilt against CAF interfaces that upstream 6.12 does not have.

Consequence: staying on CAF 4.19 and backporting upstream features into this tree remains the only route that keeps Evox working. That is the pattern this repo already uses (the MGLRU port).

## Baseline facts

All verified this session; reproduction commands are in [Verified command transcript](#verified-command-transcript).

**Upstream Linux (torvalds/linux)**

- SoC + board support exists at v6.12 and at master: `arch/arm64/boot/dts/qcom/msm8953.dtsi` (2489 lines, defines every label the board file uses), `msm8953-xiaomi-tissot.dts` (333 lines, byte-identical at v6.12 and master), `pm8953.dtsi`, `pmi8950.dtsi`. Zero dangling `&label` references. Read from `https://raw.githubusercontent.com/torvalds/linux/v6.12/arch/arm64/boot/dts/qcom/`.
- The upstream board file enables only: gpio-keys (hall switch, volume-up), reserved-memory, the rpm-pm8953 regulator set, i2c_2 (MAX98927 codec, AW2013 LED), i2c_3 (edt-ft5406 touch), pmi8950 WLED, sdhc_1/sdhc_2, uart_0, usb3 + dwc3. Display, GPU, WLAN, audio graph and sensors stay `status = "disabled"` in the dtsi.
- Upstream is missing the hardware this phone actually has: `panel-ilitek-ili7807.c` (only ILI7807**S** exists), OTM1911, FT8716; every S5K camera sensor including S5K5E8; OV12A10 and OV13880; **all** fingerprint drivers (`drivers/input/fingerprint/` has no fingerprint binding); LTR579 ALS/proximity.

**Community fork `github.com/msm8953-mainline/linux`**

- A fork-of-torvalds whose `master` is byte-identical to v6.19. Real work lives on per-release branches `<version>/main` that track **linux-stable point releases**, not torvalds master. Cloned `6.12/main` → base tag `v6.12.0-r2`, tip `d9eabbae3ede`, `Linux version 6.12.0-gd9eabbae3ede`.
- The fork's only out-of-tree driver is `drivers/input/misc/qcom-spmi-haptics.c`. It has **no** camera driver, **no** `drivers/input/fingerprint/` directory at all, and **no** `qcom,spmi-flash` flashlight driver.
- The fork's tissot DTS adds what upstream lacks: panel, sound card, haptics, WLED, hall sensor, accelerometer and magnetometer. `panel:` resolves into the fork's `msm8953-xiaomi-common.dtsi`, and the board file sets `compatible = "xiaomi,tissot-panel"` on it.
- **That compatible has no driver anywhere in this branch.** `grep -rl 'xiaomi,tissot' drivers/` returns nothing in the 6.12 clone. Building this branch as-is would give a tissot DTB with a driverless panel node.

**postmarketOS (for reference)**

- Serves this phone from the generic `qcom-msm8953` port: fork-based, zero patches of its own, pinned tarball `v7.1.3-r0`, generated full `.config` with `CONFIG_LOCALVERSION="-msm8953"`, installs `zImage` + modules + dtbs to `/boot`, boots via lk2nd, GPU firmware `a506_zap` from `gitlab.com/jiaxyga/firmware-xiaomi-tissot` @ `bf686895224cae33c2130932b4a5914fea415287`, WiFi firmware read from the stock partition via `msm-firmware-loader`, cmdline `quiet loglevel=2`, and no tissot WiFi NV blob.
- Mi A1 has no FOSS bootloader; lk2nd is required (`github.com/msm8953-mainline/lk2nd`, org archived upstream).

**The ROM on the phone**

- Evox 12.2 (Android 17). The kernel actually running is this repo's CAF fork, not Evolution-X's tree (`https://github.com/Evolution-X-Devices/kernel_xiaomi_tissot`, cloned at `../kernel_xiaomi_tissot`, 4.19.325, HEAD `6a3636869919`).
- Stock `boot.img` kernel payload reports `Linux version 4.19.325-cip136-st20-perf-g9d3bf7da9553`. Bootimg cmdline carries `androidboot.hardware=qcom msm_rtb.filter=0x237 ehci-hcd.park=3 androidboot.bootdevice=7824900.sdhci loop.max_part=7`.
- Vendor HALs present as prebuilt binaries: `adsprpcd`, `mm-qcamera-daemon`, `hw/qcrild`, `hw/android.hardware.audio.service`, `hw/audio.primary.msm8953.so`, `hw/android.hardware.wifi-service`, `hw/android.hardware.sensors@1.0-service`, `hw/vendor.qti.hardware.vibrator.service`, `hw/android.hardware.gnss@2.0-service-qti`; 483 `.so` files under `/vendor/lib64`.
- KGSL is a CAF-tree feature: `drivers/gpu/msm/adreno.h:17` `#define DEVICE_3D0_NAME "kgsl-3d0"`. Upstream 6.12 has no KGSL equivalent.

## Blocker analysis

### Newer CAF kernel for SDM625 — does not exist

- Source: `https://android.googlesource.com/kernel/msm/+refs`.
- 591 branches. Zero matches for `msm8953|sdm625|sdm630|sdm632|sdm636|sdm660|cheeseburger|tissot`.
- Newest CAF lines are 5.15, all for unrelated SoCs: `redbull`, `coral`, `sunfish`, `marlin`, `bonito`, `marlin`, `barbet`, `p11`, `seluna`, `sw5100`.
- No unified 5.x CAF repo to check either: `kernel/msm-5.4`, `kernel/msm-5.10`, `kernel/msm-5.15` all return HTTP 404.
- Verdict: **Evox 12.2's userland is permanently coupled to this CAF 4.19 built-in driver set.** There is no 5.x/6.x CAF kernel to port to.

### GKI 6.x generic kernel + CAF vendor modules — impossible

- Source: module inventory of the ROM's own images.
- `/vendor_dlkm` exists but contains only `etc`. `/vendor/lib/modules`, `/vendor_dlkm/lib/modules`, `/system_dlkm/lib/modules` and `/lib/modules` do not exist.
- Verdict: the ROM ships **no modules at all**; the "keep the vendor modules, swap the kernel" plan has nothing to keep. And per the section above there is no CAF 6.x SDM625 module set to obtain elsewhere.

### Mainline 6.12 + this ROM's userland — blocked by prebuilt vendor binaries

- Source: ROM HAL inventory plus upstream/fork driver inventory.
- The userland is prebuilt against CAF interfaces. KGSL (`/dev/kgsl-3d0`) backs the GPU path and the prebuilt HWComposer; upstream 6.12 exposes only DRM (`CONFIG_DRM_MSM`, and `m` rather than `y` under defconfig). The camera daemon is the CAF `mm-qcamera` stack; upstream has no S5K5E8, OV12A10 or OV13880 driver at all. Radio needs CAF rmtfs/qrtr/IPA; audio needs CAF voice; WLAN needs the CAF wcnss host driver.
- Fixing this would mean rebuilding the entire vendor stack against a kernel whose driver sources are not public — no proprietary source is available.
- Verdict: **not reachable.** Mainline 6.12 on this phone means a Linux userland (that is what pmOS does), not this ROM.

### Staying on CAF 4.19 and backporting features — the only working route

- Verdict: viable, and already this repo's method. MGLRU is backported here (`CONFIG_LRU_GEN=y` in `arch/arm64/configs/vendor/tissot.config`, verified). What a newer kernel would otherwise buy is enumerated under [Next steps](#next-steps).

## Milestone log

- **2026-10-04 — Milestone 1 complete.** Cloned `msm8953-mainline/linux` branch `6.12/main`; built `msm8953-xiaomi-tissot.dtb` and a full `Image.gz` (NDK 29 clang 21 / LLD 21). Measured the ROM's module inventory (none) and HAL inventory. Surveyed CAF kernel sources for SDM625 (none above 4.19). Nothing was flashed; the phone was not touched.
- **2026-10-04 — Research established.** Mainline support for this SoC is already upstream (since 6.1); the remaining upstream gaps are device drivers, not SoC plumbing. The blocker is not the kernel, it is the ROM's prebuilt vendor layer.

## Verified command transcript

### 6.12 build (fork, no device work)

```console
$ git clone --branch 6.12/main --single-branch \
    https://github.com/msm8953-mainline/linux .../msm8953-linux-6.12
$ git describe --tags --always      # v6.12.0-r2-5-gd9eabbae3ede
$ head -5 Makefile                  # VERSION 6 / PATCHLEVEL 12 / SUBLEVEL 0
$ export PATH="$HOME/Android/Sdk/ndk/29.0.14206865/toolchains/llvm/prebuilt/linux-x86_64/bin:$PATH"
$ make -C $K O=$K/out ARCH=arm64 LLVM=1 LLVM_IAS=1 defconfig
$ make -C $K O=$K/out ARCH=arm64 LLVM=1 LLVM_IAS=1 qcom/msm8953-xiaomi-tissot.dtb
  DTC     arch/arm64/boot/dts/qcom/msm8953-xiaomi-tissot.dtb
$ make -C $K O=$K/out ARCH=arm64 LLVM=1 LLVM_IAS=1 -j12 Image.gz-dtb
  OBJCOPY arch/arm64/boot/Image
  make[3]: *** No rule to make target 'arch/arm64/boot/Image.gz-dtb'.  Stop.
$ make -C $K O=$K/out ARCH=arm64 LLVM=1 LLVM_IAS=1 -j12 Image.gz
  GZIP    arch/arm64/boot/Image.gz
```

Findings from the build:

- `Image.gz-dtb` does not exist as a target on arm64 in 6.12 — `arch/arm64/boot/Makefile` only offers `Image.zst Image.xz image.fit`; the DTB ships separately. This matches pmOS, which installs `zImage`, modules and dtbs separately rather than appending a dtb.
- Artifacts: `out/arch/arm64/boot/Image.gz` (14,126,601 bytes) and `out/arch/arm64/boot/dts/qcom/msm8953-xiaomi-tissot.dtb` (67,247 bytes).
- Kernel string: `Linux version 6.12.0-gd9eabbae3ede (kurision@omarchy) ... clang version 21.0.0`.
- DTB identity: `model = "Xiaomi Mi A1"`, `compatible = "xiaomi,tissot", "qcom,msm8953"`, and `compatible = "xiaomi,tissot-panel"`.
- `defconfig` gaps for this board:

```console
$ grep -E '^CONFIG_(DRM_MSM|DRM_PANEL_XIAOMI_TISSOT|QCOM_Q6V5_MSS|MFD_SPMI|QCOM_SMEM|QCOM_SMD_RPM|DRM_FBDEV|IIO_BUFFERED_SCAN|QCOM_RPMH|ARCH_QCOM)=' .config
CONFIG_ARCH_QCOM=y
CONFIG_DRM_MSM=m
CONFIG_QCOM_Q6V5_MSS=m
CONFIG_QCOM_RPMH=y
CONFIG_QCOM_SMD_RPM=y
CONFIG_QCOM_SMEM=y
```

`MFD_SPMI` is unset under plain `defconfig`, and the `xiaomi,tissot-panel` compatible has no driver in this branch at all (`grep -rl 'xiaomi,tissot' drivers/` → nothing).

### ROM measurements (read-only, in `../evox_images`)

```console
$ file boot.img system.img
boot.img: Android bootimg, kernel, ramdisk, page size: 2048, cmdline
          (androidboot.hardware=qcom msm_rtb.filter=0x237 ehci-hcd.park=3
           androidboot.bootdevice=7824900.sdhci loop.max_part=7 androidboot)
system.img: Linux rev 1.0 ext2 filesystem data
$ dd if=boot.img of=/tmp/rom-kernel bs=2048 skip=1 count=8579 status=none
$ gunzip -c /tmp/rom-kernel > /tmp/rom-kernel.raw      # 38,416,408 bytes
$ strings -a /tmp/rom-kernel.raw | grep -m1 'Linux version'
Linux version 4.19.325-cip136-st20-perf-g9d3bf7da9553 (build-user@build-host) ...

$ img=system.img
$ debugfs -R "ls -l /vendor_dlkm" $img | tail -1      # only "etc"
$ debugfs -R "ls /vendor_dlkm/lib/modules" $img      # File not found by ext2_lookup
$ debugfs -R "ls /vendor/lib/modules" $img           # File not found by ext2_lookup
$ debugfs -R "ls /system_dlkm/lib/modules" $img      # File not found by ext2_lookup
$ debugfs -R "ls /lib/modules" $img                  # File not found by ext2_lookup
$ debugfs -R "ls /vendor/bin" $img | grep -E 'adsprpcd|camera'
adsprpcd
mm-qcamera-daemon
```

Kernel interface each HAL class needs, and whether it exists in 6.12:

| HAL / subsystem (ROM) | CAF 4.19 provides | Mainline 6.12 provides | Verdict |
| --- | --- | --- | --- |
| `adsprpcd` GPU path | KGSL `drivers/gpu/msm/adreno.h:17` `"kgsl-3d0"` | no KGSL; DRM only (`CONFIG_DRM_MSM=m` under defconfig) | blocked |
| `mm-qcamera-daemon` | CAF mm-camera stack, S5K5E8 / OV12A10 / OV13880 | no S5K5E8, no OV12A10, no OV13880 | blocked |
| `hw/qcrild` radio | CAF rmtfs / qrtr / IPA / msm_phy | rmtfs, IPA, msm_phy absent | blocked |
| `hw/audio.primary.msm8953.so` | CAF voice (`voice2` referenced in the blob) | ALSA SoC only, no CAF voice ABI | blocked |
| `hw/android.hardware.wifi-service` | CAF wcnss host driver | wcn36xx exists in-tree, different ABI, and needs out-of-tree work on MSM8953 | blocked |
| `hw/android.hardware.sensors@1.0-service` | CAF sensor hub | `liteon,ltr579` node has no driver (`Driver still missing` comment in the fork DTS) | blocked |
| `vendor.qti.hardware.vibrator.service` | CAF SPMI haptics | fork ships `qcom-spmi-haptics.c` out of tree | missing upstream |
| fingerprint (fpc,fpc1020 / goodix,gf3208) | CAF goodix/fpc | no `drivers/input/fingerprint` driver at all | blocked |
| keypad backlight, IR blaster | CAF | absent upstream and in the fork | blocked |

### CAF source survey

```console
$ curl -s 'https://android.googlesource.com/kernel/msm/+refs' \
    | grep -oE 'android-msm-[a-z0-9._-]+' | sort -u > /tmp/msm-refs.txt
$ wc -l /tmp/msm-refs.txt
591 /tmp/msm-refs.txt
$ grep -iE 'msm8953|sdm625|sdm630|sdm632|sdm636|sdm660|cheeseburger|tissot' /tmp/msm-refs.txt
(no output)
$ grep -E '5\.[0-9]+|6\.[0-9]+' /tmp/msm-refs.txt | sort -V | tail -5
android-msm-redbull-4.19-u-beta5.3
android-msm-seluna-5.15-android14-qpr3
android-msm-seluna-5.15-android14-wear
android-msm-sw5100-5.15-android15-qpr2
$ for r in msm-5.4 msm-5.10 msm-5.15; do curl -s -o /dev/null -w '%{http_code}\n' \
    "https://android.googlesource.com/kernel/$r/"; done
404
404
404
```

## Next steps

Ordered, all still no-flash until the last one is explicitly approved:

1. **Feature backport shortlist from the 6.12 tree** — the realistic way to "get a newer kernel" while keeping Evox. Verified starting points, each to be read in `../msm8953-linux-6.12` before any claim is made about it:
   - EEVDF scheduler: `kernel/sched/fair.c` in the 6.12 clone contains `eevdf` (5 occurrences); this 4.19 tree contains none. Large backport, high payoff for launch latency, and the obvious thing to try given your existing launch-time measurements.
   - MGLRU: already backported here (`CONFIG_LRU_GEN=y`), so it is a control case rather than a candidate.
   - Thermal, battery/charger and scheduler areas: to be enumerated from the clone with the same "read the file first" rule before anything is listed.
2. **Driver-gap survey for a Linux userland** — if a mainline/Linux path is ever wanted, the concrete list is: tissot panel driver (missing even in the fork), camera (S5K5E8, OV12A10, OV13880), fingerprint (fpc1020/gf3208), ALS/proximity (LTR579), keypad backlight, IR blaster, SPMI flash. pmOS works around several of these today.
3. **Nothing gets flashed without a separate, explicit go-ahead.** The artifacts under `../msm8953-linux-6.12/out` exist only as a build reference.

### Notes on process

- Two background git fetches during this research (a pmOS patch listing and the upstream commit log for the tissot DTS) returned nothing; neither claim rests on them.
- One misdirected `make defconfig` wrote a stray in-tree `.config` into the 4.19 repo; it was removed immediately, no tracked file changed, and `out/.config` was never touched.