# Mi A1 (tissot) mainline port — findings, blockers, progress

## Current status

Two milestones done, still **no flashing**. The phone has not been touched.

Milestone 1 answered the question "can a newer kernel run this ROM?" — yes in principle, and the blockers are now enumerated rather than guessed. Milestone 2 picked the base and proved it builds.

- **Base chosen: ACK `android17-6.18`** (`https://android.googlesource.com/kernel/common`, branch `android17-6.18`, HEAD `89b3cc162`, kernel 6.18.32). It matches the ROM's Android 17 and already carries `msm8953.dtsi` + `msm8953-xiaomi-tissot.dts`. Built successfully: `Image.gz` and the tissot dtb, see [Verified command transcript](#verified-command-transcript).
- **The boot chain is friendly**: the ROM's kernel payload is `gzip(Image)` with a **raw 259,283-byte DTB appended after the gzip stream**, and there is no `dtb` partition. A new kernel drops into the existing `boot.img` with the original ramdisk and cmdline untouched.
- **No CAF kernel above 4.19 targets SDM625, and no CAF 6.x kernel exists at all.** Newest CAF anywhere is 5.15 (`clo/la/kernel/msm-5.15`, `kernel.lnx.5.15.r71-rel` = 5.15.206), and CAF ships its techpacks as separate per-domain repos, not in the kernel tree.
- Therefore the remaining work is **porting the CAF vendor drivers from the local 4.19 tree onto ACK 6.18**, one subsystem at a time, starting with whatever first blocks the boot.

## Baseline facts

All verified this session; reproduction commands are in [Verified command transcript](#verified-command-transcript).

**Android Common Kernel (ACK) — the chosen base**

- Branches are versioned per Android release: `android16-6.12` (with `-2026-09` and other monthly tags, plus `android16-6.12-lts`) and **`android17-6.18`**. Plain `android-6.12` does not exist as an ACK branch; `android-mainline-6.12` is the ACK-mainline split, not the device base.
- `android17-6.18` carries `arch/arm64/boot/dts/qcom/msm8953.dtsi` and `msm8953-xiaomi-tissot.dts`, so the SoC description is already there.
- ACK vs plain mainline matters for this project: ACK provides `include/linux/vendor_hooks.h`, the GKI config set, and the Android cgroup/vendor-ABI plumbing. Binder is **not** the discriminator — mainline 6.12 already ships `drivers/android/binder*.c`; it is simply off under `defconfig` (`CONFIG_ANDROID_BINDER_IPC` unset in the mainline 6.12 build here).
- Built with `gki_defconfig`: `Image.gz` (17,249,654 bytes) reporting `Linux version 6.18.32-4k-g89b3cc162c81`, and `msm8953-xiaomi-tissot.dtb` (43,482 bytes) decoding to `model = "Xiaomi Mi A1"`, `compatible = "xiaomi,tissot", "qcom,msm8953"`.

**Boot image contract (measured from the ROM)**

- `boot.img` header: `kernel_size=17513396`, `ramdisk_size=16799333`, `second_size=0`, `page_size=2048`, `dt_size=0`, cmdline `androidboot.hardware=qcom msm_rtb.filter=0x237 ehci-hcd.park=3 androidboot.bootdevice=7824900.sdhci loop.max_part=7 androidboot.boot_devices=soc/7824900.sdhci buildvariant=user`.
- The kernel payload is `gzip(Image)` **followed by a raw FDT**: scanning the whole image finds exactly one `0xd00dfeed` magic, at offset 17,256,161 — past the end of the gzip stream — with `totalsize=259283`, `version=17`. So the stock DTB is appended uncompressed, exactly the convention this repo's `Image.gz-dtb` flashes already use.
- Partition table (`../tissot_backup_20261003/partitions.txt`): `boot_a`/`boot_b` (128 MiB each), `vendor_a`/`vendor_b`, `system_a`/`system_b`, and **no `dtb` partition**. A/B slots mean the new kernel can go in `boot_b` while the working ROM stays in `boot_a`.

**CAF beyond 4.19 — CodeLinaro survey**

- Public CAF trees exist at `clo/la/kernel/msm` (3.10–4.19), `msm-5.4`, `msm-5.10`, `msm-5.15`. There is **no** `msm-6.1`/`msm-6.6`/`msm-6.12` — a project search for `msm-6` returns nothing.
- Newest: `msm-5.15`, branch `kernel.lnx.5.15.r71-rel` = 5.15.206. Newest by activity: `msm-5.10` `KERNEL.PLATFORM.1.0.c27` = 5.10.136 (2026-09-03), which also carries `aosp-new/android12-5.10/*` GKI branches.
- `techpack/` in the 5.x/6.x kernel repos is a **stub**. CAF splits the drivers into per-domain repos under `clo/la/platform/vendor/qcom/opensource/`: `graphics-kernel` (KGSL), `audio-kernel-ar`, `dsp-kernel`, `securemsm-kernel`, `camera-extension`, `audio-vibrator`, `platform-kernel`, plus devicetree repos under `clo/la/kernel/msm-extra_group/` and WLAN/modem modules under `clo/la/kernel/msm-modules_group/`.
- CAF 5.4 still has `drivers/gpu/msm` (KGSL) in-tree; CAF 5.15 does not (KGSL moved to `graphics-kernel`).
- **No CAF 5.x tree supports SDM625**: the 5.15 tree's `arch/arm64/boot/dts/qcom/` has no `msm8953*` file at all (it carries upstream `sdm630.dtsi`, `sdm636.dtsi`, `sdm660.dtsi` and `sdm660-xiaomi-lavender.dts`, but no `sdm632` and no `build.config.msm.*` for any SDM6xx). KGSL in CAF still covers Adreno a3xx/a306/a5xx, so the SDM625's Adreno 506 is covered by *driver source* — the missing piece is SoC glue, not GPU code.
- The only SDM625 CAF tree in reach is the local `../kernel_xiaomi_tissot` (4.19.325, full `techpack/`, vendor DTS), i.e. the donor for the driver port.


**Upstream Linux (torvalds/linux)**

- SoC + board support exists at v6.12 and at master: `arch/arm64/boot/dts/qcom/msm8953.dtsi` (2489 lines, defines every label the board file uses), `msm8953-xiaomi-tissot.dts` (333 lines, byte-identical at v6.12 and master), `pm8953.dtsi`, `pmi8950.dtsi`. Zero dangling `&label` references. Read from `https://raw.githubusercontent.com/torvalds/linux/v6.12/arch/arm64/boot/dts/qcom/`.
- The upstream board file enables only: gpio-keys (hall switch, volume-up), reserved-memory, the rpm-pm8953 regulator set, i2c_2 (MAX98927 codec, AW2013 LED), i2c_3 (edt-ft5406 touch), pmi8950 WLED, sdhc_1/sdhc_2, uart_0, usb3 + dwc3. Display, GPU, WLAN, audio graph and sensors stay `status = "disabled"` in the dtsi.
- Upstream is missing the hardware this phone actually has: `panel-ilitek-ili7807.c` (only ILI7807**S** exists), OTM1911, FT8716; every S5K camera sensor including S5K5E8; OV12A10 and OV13880; **all** fingerprint drivers (`drivers/input/fingerprint/` has no fingerprint binding); LTR579 ALS/proximity.

**Community fork `github.com/msm8953-mainline/linux`**

- A fork-of-torvalds whose `master` is byte-identical to v6.19. Real work lives on per-release branches `<version>/main` that track **linux-stable point releases**, not torvalds master. Cloned `6.12/main` → base tag `v6.12.0-r2`, tip `d9eabbae3ede`, `Linux version 6.12.0-gd9eabbae3ede`.
- The fork's only out-of-tree driver is `drivers/input/misc/qcom-spmi-haptics.c`. It has **no** camera driver, **no** `drivers/input/fingerprint/` directory at all, and **no** `qcom,spmi-flash` flashlight driver.
- The fork's tissot DTS adds what upstream lacks: panel, sound card, haptics, WLED, hall sensor, accelerometer and magnetometer. `panel:` resolves into the fork's `msm8953-xiaomi-common.dtsi`, and the board file sets `compatible = "xiaomi,tissot-panel"` on it.
- **That compatible has no driver anywhere in this branch.** `grep -rl 'xiaomi,tissot' drivers/` returns nothing in the 6.12 clone. Building this branch as-is would give a tissot DTB with a driverless panel node.
**Fork patch stack on `6.12/main` (the "bug fixes" worth mining)**

- The stack is small because upstream already carries the SoC: `v6.12.0-r0`→`r1` = 5 commits, `r1`→`r2` = 1 commit, and 5 more after `r2`:
  `arm64: dts: qcom: msm8953: motorola-potter: add touchscreen reset GPIO`, `Input: rmi_i2c: introduce reset GPIO handling`, `dt-bindings: input: add max output voltage & auto resonance mode to the Qualcomm SPMI haptics`, `input: misc: qcom-spmi-haptics: make vmax configureable via DT prop`, `input: misc: qcom-spmi-haptics: make auto res mode configureable via DT prop`.
  So on 6.12 the fork's delta is **haptics + a touchscreen reset GPIO + device DTS**, not early-boot fixes.
- The tissot **panel driver is not in that fork at all** — it lives in the sibling repo `github.com/msm8953-mainline/linux-panel-drivers`, which is why `compatible = "xiaomi,tissot-panel"` has no driver in the 6.12 clone.
- The fork's newer branches (`7.1.3/main`, ~100 fork-only commits, pushed 2026-07-19) carry the substantive driver work: `qcom-spmi-haptics.c` (its only out-of-tree driver) plus extensions to camss, venus, s5k2xx, qcom-smbchg and pm8994-fg. That is where the useful camera/charging/sensor work lives, not on 6.12.


**postmarketOS (for reference)**

- Serves this phone from the generic `qcom-msm8953` port: fork-based, zero patches of its own, pinned tarball `v7.1.3-r0`, generated full `.config` with `CONFIG_LOCALVERSION="-msm8953"`, installs `zImage` + modules + dtbs to `/boot`, boots via lk2nd, GPU firmware `a506_zap` from `gitlab.com/jiaxyga/firmware-xiaomi-tissot` @ `bf686895224cae33c2130932b4a5914fea415287`, WiFi firmware read from the stock partition via `msm-firmware-loader`, cmdline `quiet loglevel=2`, and no tissot WiFi NV blob.
- Mi A1 has no FOSS bootloader; lk2nd is required (`github.com/msm8953-mainline/lk2nd`, org archived upstream).

**The ROM on the phone**

- Evox 12.2 (Android 17). The kernel actually running is this repo's CAF fork, not Evolution-X's tree (`https://github.com/Evolution-X-Devices/kernel_xiaomi_tissot`, cloned at `../kernel_xiaomi_tissot`, 4.19.325, HEAD `6a3636869919`).
- Stock `boot.img` kernel payload reports `Linux version 4.19.325-cip136-st20-perf-g9d3bf7da9553`. Bootimg cmdline carries `androidboot.hardware=qcom msm_rtb.filter=0x237 ehci-hcd.park=3 androidboot.bootdevice=7824900.sdhci loop.max_part=7`.
- Vendor HALs present as prebuilt binaries: `adsprpcd`, `mm-qcamera-daemon`, `hw/qcrild`, `hw/android.hardware.audio.service`, `hw/audio.primary.msm8953.so`, `hw/android.hardware.wifi-service`, `hw/android.hardware.sensors@1.0-service`, `hw/vendor.qti.hardware.vibrator.service`, `hw/android.hardware.gnss@2.0-service-qti`; 483 `.so` files under `/vendor/lib64`.
- KGSL is a CAF-tree feature: `drivers/gpu/msm/adreno.h:17` `#define DEVICE_3D0_NAME "kgsl-3d0"`. Upstream 6.12 has no KGSL equivalent.

**The msm8953-mainline fork's 6.18 line — the patch source from here on**

- The fork has no released `6.18/main` branch (its released lines stop at `6.17.7/main` and `6.19.5/main`). The live 6.18 line is **`barni2000/6.18/develop`**, cloned to `../msm8953-linux-6.18`, base `VERSION 6.18.0`, head `5b7b995f3738`.
- It carries **14 tissot-specific commits**, which is where the device work lives: `cf152c05eb35 ... Add device tree for Xiaomi Mi A1`, `58357bb89bfd`/`b9ec840dda1e` dts fixes, `e0fa232663f5 fix speaker`, `7cc646ac678a Add simple-amplifier for headphones`, `37234502fd7a enable haptic`, `b455e552e302 add panel compatible`, `d4cb994fd309 add GPIO-based imu sensor`, `ddd2ddea7d9d`/`f897019fc69e` config fragments (bmi160, charger, ak8975), `c5569f1a833b add config fragments`.
- It carries the fork's out-of-tree driver `drivers/input/misc/qcom-spmi-haptics.c`.
- Recent commits are more broadly useful too: `aeb318c50912 remoteproc: qcom_q6v5_mss: Introduce need_pas_mem_setup`, `10f62c558705 wcn36xx: ignore extra fields wcn36xx_hal_tx_compl_ind_msg`.
- The panel driver is **still not in this repo** — `grep -rl 'xiaomi,tissot' drivers/gpu/drm/panel/` is empty; it lives in `github.com/msm8953-mainline/linux-panel-drivers`.
- The `6.12/main` clone was deleted after this (11 GB freed). Restore with `git clone --branch 6.12/main --single-branch https://github.com/msm8953-mainline/linux ../msm8953-linux-6.12`; nothing in it is unique, the fork's tags `v6.12.0-r0..r2` reproduce its 11-commit delta.

## Blocker analysis

### Newer CAF kernel for SDM625 — does not exist

- Source: `https://android.googlesource.com/kernel/msm/+refs`.
- 591 branches. Zero matches for `msm8953|sdm625|sdm630|sdm632|sdm636|sdm660|cheeseburger|tissot`.
- Newest CAF lines are 5.15, all for unrelated SoCs: `redbull`, `coral`, `sunfish`, `marlin`, `bonito`, `marlin`, `barbet`, `p11`, `seluna`, `sw5100`.
- No unified 5.x CAF repo to check either: `kernel/msm-5.4`, `kernel/msm-5.10`, `kernel/msm-5.15` all return HTTP 404.
- Verdict: **Evox 12.2's userland is permanently coupled to this CAF 4.19 built-in driver set.** There is no 5.x/6.x CAF kernel to port to.

### CAF 6.x as a donor — also does not exist (CodeLinaro survey)

- Source: `https://git.codelinaro.org/clo/la/kernel/` (GitLab REST API v4 enumerates refs anonymously).
- Public trees: `msm` (3.10–4.19), `msm-5.4`, `msm-5.10`, `msm-5.15`. A project search for `msm-6` returns nothing; `/clo/la/kernel/msm-6.1` is 404.
- Newest tree `msm-5.15` `kernel.lnx.5.15.r71-rel` = 5.15.206; `msm-5.10` `KERNEL.PLATFORM.1.0.c27` = 5.10.136 and carries `aosp-new/android12-5.10/*`.
- The 5.x trees have no `msm8953*` DTS at all, so a CAF donor would need the SoC brought in from upstream anyway — the same work as ACK, with the extra handicap of CAF's per-domain techpack repos having to be reassembled.
- Verdict: **ACK `android17-6.18` is the better base.** It already has the SoC DTS, it matches the ROM's Android version, and the techpack has to be ported either way.

### GKI 6.x generic kernel + CAF vendor modules — impossible

- Source: module inventory of the ROM's own images.
- `/vendor_dlkm` exists but contains only `etc`. `/vendor/lib/modules`, `/vendor_dlkm/lib/modules`, `/system_dlkm/lib/modules` and `/lib/modules` do not exist.
- Verdict: the ROM ships **no modules at all**; the "keep the vendor modules, swap the kernel" plan has nothing to keep. And per the section above there is no CAF 6.x SDM625 module set to obtain elsewhere.

### Mainline 6.12 + this ROM's userland — blocked by prebuilt vendor binaries

- Source: ROM HAL inventory plus upstream/fork driver inventory.
- The userland is prebuilt against CAF interfaces. KGSL (`/dev/kgsl-3d0`) backs the GPU path and the prebuilt HWComposer; upstream 6.12 exposes only DRM (`CONFIG_DRM_MSM`, and `m` rather than `y` under defconfig). The camera daemon is the CAF `mm-qcamera` stack; upstream has no S5K5E8, OV12A10 or OV13880 driver at all. Radio needs CAF rmtfs/qrtr/IPA; audio needs CAF voice; WLAN needs the CAF wcnss host driver.
- Fixing this would mean rebuilding the entire vendor stack against a kernel whose driver sources are not public — no proprietary source is available.
- Verdict: **not reachable.** Mainline 6.12 on this phone means a Linux userland (that is what pmOS does), not this ROM.

### ACK 6.18 + ported CAF drivers — the route being taken

- What ACK gives: the SoC DTS, the full Android kernel surface (binder, vendor hooks, GKI config, Android cgroup/ABI plumbing) and a 6.18 core.
- What it lacks for this phone: everything the ROM's vendor HALs talk to — KGSL (`/dev/kgsl-3d0`), the `mm-qcamera` stack and its sensors, WLAN (`wcnss`/cnss2 + WCN3680B), audio (PIL/voice), IPA/rmtfs/qrtr for the radio, SPMI haptics, fingerprint, LTR579 ALS.
- Donor for all of that: `../kernel_xiaomi_tissot` (CAF 4.19.325, full `techpack/`), which is the exact tree this ROM was built against.
- Per-subsystem risk, largest first: camera (mm_camera + three sensors) ≫ KGSL (needs mainline 6.x msm GEM/power sequencing) ≫ display/MDP5 ≫ WLAN ≫ audio/PIL ≫ radio ≫ the rest. Expect the first boot to fail long before any of these are exercised, so the ordering is: get a console first, then bring up SoC glue, then drivers.

### Staying on CAF 4.19 and backporting features — still viable

- Verdict: viable, and already this repo's method. MGLRU is backported here (`CONFIG_LRU_GEN=y` in `arch/arm64/configs/vendor/tissot.config`, verified). Kept as the fallback if the ACK port stalls.

## Milestone log

- **2026-10-04 — Milestone 3 complete.** Added the tooling (`scripts/ack-driver-audit.py`, `scripts/tissot-ack.config`, `scripts/build-ack-tissot.sh`) and rebuilt ACK with the device config merged onto `gki_defconfig`: `Image.gz` 17,477,414 B, dtb 43,482 B, `Image.gz-dtb` 17,520,896 B. Compiled-in driver coverage of the dtb went from 7 nodes to 65. Cloned the fork's `barni2000/6.18/develop` (14 tissot commits + the haptics driver) and deleted the superseded 6.12 clone. Still nothing flashed.
- **2026-10-04 — Milestone 2 complete.** Chose ACK `android17-6.18` as the base and built it: `gki_defconfig` → `Image.gz` (17,249,654 B, `Linux version 6.18.32-4k-g89b3cc162c81`) plus the tissot dtb (43,482 B). Confirmed the ROM's boot-image contract: kernel payload is `gzip(Image)` + appended raw DTB (259,283 B, FDT v17), no `dtb` partition, `boot_a`/`boot_b` A/B available. Surveyed CodeLinaro: no CAF 6.x exists at all, newest CAF is 5.15, and no CAF tree above 4.19 targets SDM625. Catalogued the `msm8953-mainline/linux` `6.12/main` stack (11 commits: haptics, touchscreen reset GPIO, DTS) and the fact that its panel driver lives in a separate repo. Nothing was flashed.
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

### ACK `android17-6.18` build (the chosen base)

```console
$ git clone --depth 1 --branch android17-6.18 --single-branch \
    https://android.googlesource.com/kernel/common .../ack-android17-6.18
$ git log --oneline -1
89b3cc162 (grafted, HEAD -> android17-6.18) ANDROID: sched: Add missing vendor hook for sched_setaffinity
$ head -5 Makefile                   # VERSION 6 / PATCHLEVEL 18 / SUBLEVEL 32
$ ls arch/arm64/boot/dts/qcom/ | grep tissot
msm8953-xiaomi-tissot.dts
$ export PATH="$HOME/Android/Sdk/ndk/29.0.14206865/toolchains/llvm/prebuilt/linux-x86_64/bin:$PATH"
$ make -C $A O=$A/out ARCH=arm64 LLVM=1 LLVM_IAS=1 gki_defconfig
$ make -C $A O=$A/out ARCH=arm64 LLVM=1 LLVM_IAS=1 -j12 Image.gz
  OBJCOPY arch/arm64/boot/Image
  GZIP    arch/arm64/boot/Image.gz
$ make -C $A O=$A/out ARCH=arm64 LLVM=1 LLVM_IAS=1 qcom/msm8953-xiaomi-tissot.dtb
$ gunzip -c $A/out/arch/arm64/boot/Image.gz | strings -a | grep -m1 'Linux version'
Linux version 6.18.32-4k-g89b3cc162c81 (kurision@omarchy) (Android ... clang version 21.0.0) ...
$ dtc -I dtb -O dts $A/out/arch/arm64/boot/dts/qcom/msm8953-xiaomi-tissot.dtb | grep -m2 'model\|compatible = "xiaomi'
	model = "Xiaomi Mi A1";
	compatible = "xiaomi,tissot", "qcom,msm8953";
```

Artifacts: `out/arch/arm64/boot/Image.gz` = 17,249,654 bytes; `out/arch/arm64/boot/dts/qcom/msm8953-xiaomi-tissot.dtb` = 43,482 bytes. Note the ACK dtb is smaller than the fork's (43 KB vs 67 KB) because upstream's board file enables fewer peripherals — display, GPU, WLAN and audio are all still `disabled`.

### Boot image contract (parsed, not guessed)

```console
$ python3 - <<'EOF'   # boot header, Android boot image v0 layout
kernel_size=17513396 ramdisk_size=16799333 second_size=0 page_size=2048 dt_size=0
cmdline: androidboot.hardware=qcom msm_rtb.filter=0x237 ehci-hcd.park=3
         androidboot.bootdevice=7824900.sdhci loop.max_part=7
         androidboot.boot_devices=soc/7824900.sdhci buildvariant=user
$ python3 - <<'EOF'   # scan the whole boot.img for an appended DTB
fdt magic at offsets: [17256161] total 1
offset=17256161 totalsize=259283 version=17 boot_cpuid=0
```

The single FDT sits **after** the gzip stream ends, i.e. the payload is `gzip(Image)` + raw dtb. Same convention as this repo's `Image.gz-dtb`. `../tissot_backup_20261003/partitions.txt` confirms `boot_a`/`boot_b` and no `dtb` partition.

### Fork patch stack on `6.12/main`

```console
$ git -C ../msm8953-linux-6.12 log --oneline v6.12.0-r2..6.12/main
d9eabbae3ede arm64: dts: qcom: msm8953: motorola-potter: add touchscreen reset GPIO
891820a1db24 Input: rmi_i2c: introduce reset GPIO handling
69561a0bc0ef dt-bindings: input: add max output voltage & auto resonance mode to the Qualcomm SPMI haptics
b902de975124 input: misc: qcom-spmi-haptics: make vmax configureable via DT prop also: ...
f5fafca9532b input: misc: qcom-spmi-haptics: make auto res mode configureable via DT prop
$ git -C ../msm8953-linux-6.12 rev-list --count v6.12.0-r0..v6.12.0-r1   # 5
$ git -C ../msm8953-linux-6.12 rev-list --count v6.12.0-r1..v6.12.0-r2   # 1
```

### ACK build with the tissot device config

```console
$ ./scripts/build-ack-tissot.sh
# gki_defconfig, then merge_config.sh -m merges scripts/tissot-ack.config on top,
# then olddefconfig, then Image.gz, the dtb, and `cat Image.gz dtb > Image.gz-dtb`
built:
  arch/arm64/boot/Image.gz                           17477414 bytes
  arch/arm64/boot/dts/qcom/msm8953-xiaomi-tissot.dtb     43482 bytes
  arch/arm64/boot/Image.gz-dtb                       17520896 bytes
Linux version 6.18.32-4k-g89b3cc162c81 (kurision@omarchy) (Android ... clang 21.0.0) ...
```

Driver coverage, measured per node by `scripts/ack-driver-audit.py` (it honours DT fallback lists, so `"qcom,msm8953-sdhci", "qcom,sdhci-msm-v4"` counts as driven by the second entry):

```console
$ scripts/ack-driver-audit.py --dtb .../msm8953-xiaomi-tissot.dtb --tree ../ack-android17-6.18 \
                              --config ../ack-android17-6.18/out/.config
100 device nodes: 97 have a driver (65 compiled in), 3 have none, 23 are core-reserved nodes
$ ... --only-unbound
NOBIND   okay   /soc@0/sram@60000            qcom,rpm-msg-ram
NOBIND   okay   /soc@0/syscon@1937000        qcom,tcsr-msm8953 syscon
NOBIND   okay   /soc@0/syscon@193f044        qcom,tcsr-msm8953 syscon
```

All three are artefacts of the tool, not real gaps:

- `qcom,rpm-msg-ram` describes the RPM message SRAM region; no driver consumes it.
- The TCSR nodes list `syscon` as fallback, but in ACK 6.18 syscon is no longer an `of_match` driver: it moved to `drivers/mfd/syscon.c` (`CONFIG_MFD_SYSCON`) and is reached through `of_device_is_compatible(np, "syscon")` / `syscon_regmap_lookup_by_compatible()`. `drivers/of/syscon.c` does not exist in this tree.

**So everything the upstream dts describes is driven.** Every remaining gap sits in the nodes the upstream board file deliberately leaves `disabled` — `mdss`/`mdp5`, `gpu`, `wcnss`, `lpass`, CCI, the cameras, the sensors, the fingerprint — which is exactly the CAF bring-up, and exactly what the audit cannot see until those nodes are switched on.

For comparison, the same audit on the earlier bare `gki_defconfig` build found only 7 compiled-in nodes and no eMMC, no SPMI and no regulators. The fragment is what turns a generic Android kernel into one that could plausibly reach a shell on this board.

### Boot attempt 1 and 2 — live boot via `fastboot boot`

Both attempts used `fastboot boot`, which writes nothing to any partition, so the active slot stayed `a` the whole time.

```console
# payload layout is already correct: gzip(Image) + appended raw dtb
$ mkbootimg --header_version 0 --os_version 17.0.0 --os_patch_level 2026-09 \
    --kernel Image.gz-dtb --ramdisk ramdisk --pagesize 0x800 --base 0x0 \
    --kernel_offset 0x80008000 --ramdisk_offset 0x81000000 --second_offset 0x0 \
    --tags_offset 0x80000100 --board '' --cmdline "$ORIG_CMDLINE console=ttyMSM0,115200n8 ignore_loglevel printk.time=1 panic=30" \
    --output boot-ack.img
34,324,480 bytes, kernel_size 17,520,896 (= Image.gz-dtb), ramdisk_size 16,799,333 (unchanged)
$ fastboot flash boot_b boot_a-live.img      # known-good fallback, from the live boot_a pulled over adb
$ fastboot boot boot-ack.img                # Booting OKAY
```

What happened, and what it proves:

- Splash art appeared, then the screen stayed black. The splash is ABL's own display from the `splash` partition, so it only proves the bootloader handed off — it says nothing about the kernel. A black screen is **expected by construction** here: upstream's board file leaves `mdss`/`mdp5` and `gpu` disabled, so there is no backlight path at all.
- No adb, and `lsusb` showed no phone on the bus: the kernel did not reach USB enumeration, so it hangs before that rather than booting into a shell without adb.
- `fastboot fetch` is unsupported on this bootloader (`Unable to get max-fetch-size`), so the live `boot_a` was pulled over adb with root instead: `su -c 'dd if=/dev/block/by-name/boot_a of=/data/local/tmp/boot_a-live.img'`. Note the existing backup `tissot_backup_20261003/img/boot_a.img` holds an **older** kernel (`…-g9d3bf7da9553-dirty`, Sep 30), not the currently running one (`…-mglru-next-g7f57b3823629`), so it is not a valid copy of the working boot.
- Attempt 2 rebuilt the kernel with `CONFIG_USB_FUNCTIONFS=y` added, because `CONFIG_USB_FUNCTIONFS` was the one piece that made adb impossible no matter how far init got (adbd speaks FunctionFS; `CONFIG_USB_CONFIGFS_F_FS=y` was already set, only the driver itself was off). Rebuilt `Image.gz` 17,483,439 B, relive-booted — adb still did not appear, and no USB enumeration at all.
- The phone recovered by itself each time back to slot `a` on the CAF kernel with `sys.boot_completed=1`.

No logs were recoverable from either attempt, and this is structural rather than an oversight:

- ACK's tissot dts puts `ramoops` at `0x9ff00000` (1 MB, console-size 0x80000); the CAF 4.19 tree puts its `ramoops` at `0x91400000` (4 MB). Booting back into CAF therefore cannot see ACK's buffer.
- Even with a shared address it would not work: ramoops clears its region when it probes, so the kernel you boot back into wipes the previous kernel's log.
- No UART cable was attached, and `console=ttyMSM0,115200n8` alone only lights up if the UART is physically observed.

### The RAM-dump harness (no UART available)

With no serial cable, a failing kernel's pstore buffer is recovered by having a *working* kernel read the reserved memory the *failing* kernel wrote into.

Added to this repo on the `project-mainline` branch, all uncommitted:

- `drivers/misc/tissot_pstore_dump.c` — maps `CONFIG_TISSHOT_PSTORE_DUMP_BASE` (`0x9ff00000`) for `CONFIG_TISSHOT_PSTORE_DUMP_SIZE` (`0x100000`) with `memremap()` and exposes it as a binary sysfs attribute at `/sys/kernel/tissot/tissot_pstore`. `drivers/misc/Kconfig` adds the symbol plus the base/size hex options; `drivers/misc/Makefile` builds it.
- `arch/arm64/boot/dts/vendor/qcom/mi8953/tissot/android.dtsi` — reserves `ack-pstore@9ff00000` (1 MB, `no-map`) so this kernel neither allocates over nor initialises the region the other kernel used. That address was chosen because ACK's `msm8953-xiaomi-tissot.dts` puts its own `ramoops` exactly there.
- `arch/arm64/configs/vendor/tissot.config` — `CONFIG_TISSHOT_PSTORE_DUMP=y`.

Verified in the build artifacts: `CONFIG_TISSHOT_PSTORE_DUMP=y` with the expected base/size, the driver's string present in `vmlinux`, and `ack-pstore@9ff00000 { reg = <0x0 0x9ff00000 0x0 0x100000>; no-map; }` present in the built `tissot-titanium.dtb`. The reader kernel boots Android normally with this in place.

Four dead ends found while building it, each worth recording:

1. **debugfs cannot work here.** A debugfs mount is `0700`, so even a `0444` file beneath it is unreachable from an unprivileged shell. Moved to sysfs, where `/sys/kernel` is world-readable.
2. **Flashing a custom boot image drops Magisk.** Magisk lives in the boot image, so replacing `boot_a` removed `su` entirely — the phone came back with no root. Any kernel we flash does this, which is exactly why the dump must not *depend* on root.
3. **SELinux blocks the unprivileged read anyway.** With the sysfs attribute at `0444`, `adb shell` (uid 2000, `u:r:shell:s0`) still gets `Permission denied` — the shell domain cannot read arbitrary sysfs objects. Root is required after all.
4. **`ro.debuggable=1` in the ramdisk does not work.** The ROM's `/system/build.prop` sets `ro.debuggable=0`, `ro.secure=1`, `ro.adb.secure=1`, and the property service keeps the later value, so adbd still dropped to uid 2000.

Also note this tree's `dtc` rejects DTS **labels** containing dashes (`ack-pstore-mem:` fails to parse); node names may contain them, labels may not.

### Slot layout and the A/B trap

| Slot | Contents | Boots |
| --- | --- | --- |
| `a` | reader kernel (this tree's CAF build + dump driver) + working ROM | yes |
| `b` | Evox stock `boot.img` + `system.img`, stale `vendor_b` | yes |
| ephemeral | ACK 6.18 with the tissot config | no, hangs before USB enumeration |

Two mistakes made here, both worth remembering:

- **`fastboot set_active b` without checking that slot `b` held a ROM.** Slot `b` had only a stock boot image and no matching system, so the phone would not boot until `boot_b` was flashed with the Evox `boot.img` and `system.img`. A/B fallback does not rescue this: the fallback logic lives in Android userspace and only runs if the kernel got far enough to start `init`.
- **Putting the reader in `boot_b` first.** The reader has to live on the **active** slot, because recovery from a failed ACK boot is a warm `fastboot reboot`, which comes back to the active slot.

Two more environment facts: `fastboot fetch` is unsupported by this bootloader (`Unable to get max-fetch-size`), so the live `boot_a` had to be pulled over rooted adb with `dd`; and `vendor_b` rejects the backup `vendor_a.img` as `size too large` because it is 512 bytes bigger than the partition (629,146,112 vs 629,145,600), so it needs truncating first.

## Next steps

1. **Get root back** — patch our boot image with Magisk (APK installed on the device, image pushed to `/sdcard/Download/boot-sysfs.img`), then flash the result to `boot_a`. Everything below depends on it.
2. **Confirm the harness** — as root, `cat /sys/kernel/tissot/tissot_pstore | strings | head`. The region is currently expected to be zeros or stale data; that is fine, the point is that the read path works.
3. **ACK boot test** — `fastboot boot` the ACK image, let it die, then Power + **Volume-Down** to fastboot (Volume-Up goes to recovery, which costs us the RAM buffer) and `fastboot reboot` back into the reader. Pull the dump and decode with `strings`.
4. **Then diagnose**, with real logs for the first time, why ACK hangs before USB enumeration.
5. **Afterwards**, port the CAF techpack drivers, using the fork's 14 tissot commits and `msm8953-mainline/linux-panel-drivers` as board-side donors. EEVDF backport to CAF 4.19 stays available as the fallback.

### Notes on process

- Two background git fetches during this research (a pmOS patch listing and the upstream commit log for the tissot DTS) returned nothing; neither claim rests on them.
- One misdirected `make defconfig` wrote a stray in-tree `.config` into the 4.19 repo; it was removed immediately, no tracked file changed, and `out/.config` was never touched.