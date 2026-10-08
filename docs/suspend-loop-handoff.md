# Handoff: tissot suspend loop fix (branch `oc-test-2ghz`)

Written 2026-10-08, mid-task, because the device went away. Everything below
is verified against the tree unless marked otherwise.

## State

- Worktree `/home/kurision/development/kernel/oc-test`, branch `oc-test-2ghz`,
  base `df4a1f863991` (2784 MHz OC) on top of `7f57b3823629` (mglru-next).
  The device last booted `4.19.325-cip136-st20-perf-mglru-next-gdf4a1f863991`,
  i.e. the branch tip without these changes.
- Two files changed, uncommitted at the time this note was written:
  - `drivers/staging/prima/CORE/HDD/src/wlan_hdd_dev_pwr.c` — Step 1
  - `docs/mglru-next-port.md` — Steps 2 and 3 (new `## Deferred backports`)
- Steps 2 and 3 are documentation only, and every citation in them was
  checked against the tree (see below).

## Step 1: what was changed and why it differs from the approved plan

The approved plan replaced the fatal return with
`__pm_wakeup_event(ws, 100); return 0;`. That snippet cannot compile in this
tree. Verified:

- There is no `struct wakeup_events` and no global `ws` anywhere in
  `kernel/` or `include/` (`grep -rn "wakeup_events" kernel/ include/` only
  hits `kernel/events/core.c`, unrelated, and a stale comment at
  `drivers/base/power/wakeup.c:996`).
- `__pm_wakeup_event()` at `include/linux/pm_wakeup.h:201` takes a
  `struct wakeup_source *` — it is the vendor wakelock/debugfs API
  (`pm_wakeup_ws_event`), not upstream's suspend wakeup-event counter. The
  `ws` in `kernel/time/alarmtimer.c` is a file-static `struct wakeup_source *`
  registered at `kernel/time/alarmtimer.c:106`.
- `pm_check_wakeup_events()` does not exist in this tree, so there is no
  "abort this suspend, retry in N ms" mechanism to borrow.
- `pm_wakeup_event(dev, ms)` is the same vendor wakelock accounting and is a
  no-op unless the device registered a wakeup source, which wcnss_wlan does
  not.

So there is no retry primitive to call. What actually happens at noirq time
is worse than a race: `->suspend` (`wlan_suspend()`,
`drivers/staging/prima/CORE/HDD/src/wlan_hdd_dev_pwr.c:134`) waits for the RX
thread to acknowledge suspend, and `vos_sched.c:1268` is the only place that
clears `RX_POST_EVENT`. By the time `->suspend_noirq` runs, the RX thread is
frozen, so a message posted in the window between the two callbacks sets the
bit and nobody can ever clear it. Every retry then fails identically — the
~0.3 s loop recorded at `docs/oc-uc.md:66-68`. The check cannot succeed, so
it was deleted rather than downgraded.

The commit therefore removes `pSchedContext` (now unused, which would have
produced a `-Wunused-but-set-variable` warning) and the whole
`RX_POST_EVENT` branch, leaving a comment that says why there is no check.

## Step 1: what is NOT yet verified

The change has not been booted. Remaining, on a machine with the device:

1. Build:
   ```sh
   cd /home/kurision/development/kernel/oc-test
   export PATH="$HOME/Android/Sdk/ndk/29.0.14206865/toolchains/llvm/prebuilt/linux-x86_64/bin:$PATH"
   make O=out-oc ARCH=arm64 LLVM=1 LLVM_IAS=1 LD=aarch64-linux-gnu-ld -j12 Image.gz-dtb
   ```
2. Repack. `scripts/repack-tissot-probe.sh` is untracked and lives only in
   the `mglru-folio` worktree
   (`/home/kurision/development/kernel/kernel_xiaomi_msm8953/scripts/repack-tissot-probe.sh`);
   call it by absolute path with `BASE_IMAGE`, `KERNEL`, `OUT_IMAGE` pointing
   at `out-oc/`, or copy it into this worktree first. CAF cmdline:
   `androidboot.bootdevice=7824900.sdhci androidboot.boot_devices=soc/7824900.sdhci …`
   as on 2026-10-08. `fastboot boot` the result; nothing is flashed.
3. Loop gone: `grep -c "failed to suspend"` in dmesg stays 0 (or at least no
   longer climbs) with the screen off, `mWakefulness=Asleep`. Not "a lower
   rate".
4. Wi-Fi reassociates after a real suspend/resume and data flows
   (`dumpsys wifi`, `ping -c 3 1.1.1.1`).
5. No new `WARNING:` class beyond the three known-good vendor ones.
6. The six `scripts/test-mglru-*.py` on this branch (accounting, lifecycle,
   memcg-lifecycle, refault, shadow, zone-progression) still pass.

Fallback if the loop persists after this change: per the approved plan, do
not touch `alarmtimer_suspend()`; read the device name out of the
`PM: Device <name> failed to suspend …: error -N` line
(`drivers/base/power/main.c:446`) and report it. If it is neither
`wcnss_wlan` nor `alarmtimer`, that is a third cause and needs its own
diagnosis.

## Device observations from this session (branch-tip kernel, pre-fix)

- `dmesg` is not readable directly (`klogctl: Permission denied`, also under
  `su -c`). Redirect instead: `su -c 'dmesg > /data/local/tmp/d.txt'`, then
  grep the file from a script pushed with `adb push` and run as
  `/system/bin/sh /data/local/tmp/x.sh`. Multi-word `grep` patterns through
  `su -c` get their quotes eaten and produce nonsense counts.
- **The loop was not reproduced.** With the screen off for 70 s there were 0
  `failed to suspend` lines, 0 `PM:` lines at all, and every counter in
  `/sys/power/suspend_stats/*` was 0 — no suspend was even attempted. The
  device stayed at `mWakefulness=Dozing`. `settings get global
  stay_on_while_plugged_in` is already 0, but the charging policy still holds
  `CHG_PLCY_MAIN_WL` (active_count 843 in
  `/sys/kernel/debug/wakeup_sources`) because the phone is USB-powered, so
  the framework never asks for deep suspend. Reproducing the loop needs the
  device off USB, which costs adb.
- The device dropped off adb during the session and reappeared after 90 s
  unaided, so a forced suspend does recover; still, arm an RTC wake alarm
  before forcing one.
- Evidence for the Step 3 decision, captured before the drop: in
  `/sys/kernel/debug/wakeup_sources`, `video1`, `video2` and `video3` all
  have `active_count=1`, so video4linux nodes are open and the CAF video
  stack is the live path. The `ls /dev/video*` and `dumpsys media.camera`
  cross-checks from the plan are still outstanding.

## Steps 2 and 3: citations that were verified

- `mm/Kconfig:485` `config FRONTSWAP` ("if tmem is present", "transcendent
  memory"); `mm/Kconfig:564` `config ZSWAP` `depends on FRONTSWAP &&
  CRYPTO=y`, help text "as of v3.11".
- `out-oc/.config`: `# CONFIG_FRONTSWAP is not set`,
  `# CONFIG_ZPOOL is not set`, no `ZSWAP` line,
  `CONFIG_ZRAM_WRITEBACK=y`, `CONFIG_ZRAM_DEFAULT_COMP_ALGORITHM="lz4"`.
- `drivers/block/zram/zram_drv.c`: zero `frontswap` matches;
  `zcomp_decompress()` at 1383, `zcomp_compress()` at 1463.
- `arch/arm64/boot/dts/vendor/qcom/mi8953/tissot/camera.dtsi:1` opens with
  `&cci {` and `qcom,actuator@1` / `qcom,eeprom@2` children
  (`qcom,slave-addr`, `qcom,page0`, `qcom,eeprom-name = "ofilm_s5k5e8"`).
- `drivers/media/platform/qcom/camss/` has 17 files;
  `# CONFIG_VIDEO_QCOM_CAMSS is not set`;
  `drivers/media/platform/qcom/venus/` is present with no Kconfig symbol in
  `out-oc/.config`.
- Charger and fuel gauge counterparts exist and are on:
  `CONFIG_QPNP_SMBCHARGER=y` (the `QPNP_SMB2`/`QPNP_SMB5` sub-options are
  off, so this device uses another chip in that family) and
  `CONFIG_QPNP_FG=y`.
- No `s5k2*` sensor exists under `drivers/media/i2c/` (only s5k4ecgx,
  s5k5baf, s5k6a3, s5k6aa). `drivers/input/misc/qti-haptics.c` binds
  `qcom,haptics`, `qcom,pm660-haptics`, `qcom,pm8150b-haptics` — a different
  binding from the fork's, and `# CONFIG_INPUT_QTI_HAPTICS is not set`.

## Housekeeping

`git diff --check` is clean; the one-file code change is 0 errors / 0 warnings
under `scripts/checkpatch.pl --no-signoff`. `kernel/time/alarmtimer.c` is
untouched on purpose: its `-EBUSY` at line 297-298 for an alarm expiring in
under 2 s is correct upstream behaviour and is a symptom, not a cause.
