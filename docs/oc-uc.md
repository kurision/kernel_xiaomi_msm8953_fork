# CPU / GPU overclock and underclock — Mi A1 (tissot), msm8953, Linux 4.19

| | Stock | This kernel |
| --- | --- | --- |
| CPU (all 8 cores) | 652.8 – 2016 MHz, 7 steps | **480 – 2400 MHz, 15 steps** |
| GPU (Adreno 506) | 133.3 – 650 MHz, 7 steps | **100 – 725 MHz, 9 steps** |
| CPU voltage source | CPR4, 7 corners | CPR4, 15 corners (4 extrapolated above Turbo) |
| Scope | — | tissot only (`mi8953/tissot/oc.dtsi`) + 3 small driver changes |

This document records how the port was done: what was measured on the device,
what was learned from the old 4.9 LuciferKernel, every change with its purpose,
reasoning and possible later improvement, plus how to build, flash and verify.

---

## 1. Findings on the live device

Collected over `adb` (root) on the running 4.19 build
`4.19.325-cip136-st20-perf-g9d3bf7da9553-dirty`, before any OC changes.

### CPU / CPR

From `/sys/kernel/debug/cpr3-regulator/apc/thread0/apc_corner/`:

| Field | Value |
| --- | --- |
| `speed_bin_fuse` | **2** (the 2.0 GHz SD625 table) |
| `cpr_rev_fuse` | **3** |
| `fuse_combo` | 19 (= rev 3 + 8 × bin 2) |
| `corner_count` | 7 |

| Corner | Freq (MHz) | Open-loop (mV) | Floor (mV) | Ceiling (mV) | Closed-loop `last_volt` (mV) |
| --- | --- | --- | --- | --- | --- |
| 1 | 652.8 | 650 | 600 | 650 | 640 |
| 2 | 1036.8 | 700 | 650 | 700 | 680 |
| 3 | 1401.6 | 770 | 720 | 770 | 765 |
| 4 | 1689.6 | 820 | 770 | 820 | 815 |
| 5 | 1804.8 | 870 | 820 | 870 | 860 |
| 6 | 1958.4 | 935 | 885 | 935 | 925 |
| 7 | 2016 | 955 | 905 | 955 | 930 |

Takeaways:

- The chip settles at ~930 mV at 2016 MHz. The APC rail (PM8953 S5) is allowed
  up to 1140 mV (`regulator-max-microvolt`) and Qualcomm's own boost ceiling
  for this SoC is also 1140 mV (`MSM8953_APSS_BOOST_CEILING_VOLT`), so there
  is ~200 mV of headroom for overclocking.
- The ceiling equals the open-loop voltage on every corner because the DT sets
  `qcom,cpr-scaled-open-loop-voltage-as-ceiling`. Any OC corner therefore needs
  a sane *open-loop* voltage — the DT ceiling only caps it.

### GPU

- `gpu_available_frequencies`: 650, 560, 510, 400, 320, 216, 133.33 MHz.
- devfreq governor `msm-adreno-tz` is active (thanks to the existing
  `gpu_opp_table` fix in `msm8953-gpu.dtsi`).
- The GPU OPP table (`/sys/kernel/debug/opp/soc-1c00000.qcom,kgsl-3d0`)
  contains only the static `gpu_opp_table` entries (`dynamic=N`). The clock
  driver's `qcom,gcc_oxili_gfx3d_clk-opp-handle` does not contribute OPPs, so
  `gpu_opp_table` is what devfreq sees.

### Kernel health

- No `BUG:`, `WARNING:`, `Oops`, panic or call trace in the current ring
  buffer or in the previous boot (`/sys/fs/pstore/console-ramoops-0`).
- **Unrelated issue worth fixing separately:** suspend aborts in a tight loop
  (~every 0.3 s): `wcnss_wlan_suspend_noirq` returns -1 and `alarmtimer`
  returns -EBUSY (-16). Likely a battery drain.
- Apps like DevCheck hit `avc: denied` on `sysfs_kgsl` (`cur_freq`,
  `freq_table_mhz`, …) — a sepolicy issue, not a kernel one.

---

## 2. What LuciferKernel (4.9) did, and why it was not copied

LuciferKernel's `OC-reb` branch (vs `NonOC-reb`) edits the same files this
4.19 tree uses, because both trees use the legacy `drivers/clk/msm` clock
framework and the same CPR4 / GFX LDO drivers. Its headline numbers, however,
do not hold up:

| Area | Lucifer change | Problem |
| --- | --- | --- |
| GPU clock table | 779 / 908 / 1037 / 1166 MHz rows on GPLL3 @ 1380 / 1420 / 1460 / 1500 MHz | GPLL3 output is divided by 2 (510 MHz = 1020 / 2). Real rates ≈ **690 / 710 / 730 / 750 MHz**. |
| GPU pwrlevels | 850 / 760 / 610 MHz | Not in the clock table — rounded to some other table rate. |
| `qcom,gfxfreq-corner` | Extra leading `<0 0>`, SVS+ at 485 MHz | Map shifted by one; 485 MHz is not a table rate. |
| CPU PLL | `max_rate` and VDD_MX fmax raised to 3.066 GHz | No voltage behind it: the top CPR ceiling stays 1065 mV, same as stock 2016 MHz. |
| CPR | 20 corners (420 MHz – 3.03 GHz), fmax map `<1 2 4 20>` | Turbo's fused voltage is anchored at 3.03 GHz and interpolated *down*, so stock frequencies such as 2016 MHz get **less** voltage than their fuse says (see §3.3). |
| `msm_cpufreq` | 21 clock phandles for 9 names | Malformed. |
| `clock-cpu-8953.c` | Removed `CLKFLAG_NO_RATE_CACHE` from the cluster muxes | Unrelated to OC; risks stale cached rates. |

What was reused: the low CPU steps (480, 576, 806.4, 1248 MHz), lowering the
HFPLL `min_rate` to 480 MHz, and adding GPLL3 rows for the GPU.

### Other Lucifer branches

Source: `~/development/kernel/LuciferKernel`, branches `OC`, `old-OC`,
`OC-reb`, `OC-base`, `OC-test`, `NonOC-reb`, `nonOC-*`.

| Branch | Differences from `OC-reb` |
| --- | --- |
| `OC-base`, `OC-test` | Only qseecom/adsp CMA sizes and `KGSL_MAX_CLKS` 16 → 17. No OC differences. |
| `OC` (= `old-OC`) | A different OC table plus an **undervolt interface**, described below. |

**`OC` branch tables.** CPU steps run up to 2409 / 2616 / 2958.4 / 3150.4 MHz,
with PLL `max_rate` at 3.15 GHz and `min_rate` back at 652.8. The CPR side is
still the stock 7/9-corner bins (`<9 0 13 0 0 0 7 9>`, ceilings ≤ 1065 mV), so
the steps above 2208 MHz have no CPR corner of their own. GPU levels are
labelled 850 / 760 / 610 MHz on GPLL3 at 1450 / 1300 / 1120 MHz, which after the
÷2 really run at **725 / 650 / 560 MHz**. Lucifer's "850 MHz GPU" is the same
725 MHz this port uses, under its real name.

**`OC` branch undervolt (commit "Added Voltage control msm8953"):**

- `CONFIG_VOLTAGE_CONTROL` adds `/sys/devices/system/cpu/cpufreq/policy0/UV_mV_table`
  (in `drivers/cpufreq/cpufreq.c`). It shows and stores ceiling, floor and last
  voltage for every CPU corner of both clusters.
- Backend: `get_Voltages()` / `set_Voltages()` in `clock-cpu-8953.c`, which call
  new `cpr_regulator_{get,set}_{ceiling,floor,last}_voltage()` helpers in
  `cpr3-regulator.c`. These write `corner[].ceiling_volt` / `floor_volt` /
  `last_volt` under the controller lock.
- `CONFIG_CPU_VOLTAGE_TABLE` (the older faux123 variant in the same file) is
  **broken on this SoC**. It writes millivolts into `vdd_class->vdd_uv[]`, but
  here that array holds CPR *corner numbers*, not microvolts.
- Weaknesses of the `VOLTAGE_CONTROL` version: no bounds check against the
  1140 mV rail limit, no `floor ≤ ceiling` check, no rounding to the 5 mV step,
  and writing `last_volt` has no effect while CPR closed loop runs. New limits
  only take effect at the next corner switch. It isn't ported yet; see
  "Improve later" in §4.4.

---

## 3. How frequency scaling works on msm8953 (what had to change and why)

### 3.1 CPU clock tree

```
XO 19.2 MHz ──► apcs_hf_pll (L-value × 19.2 MHz) ──┬─► a53ssmux_pwr  (÷1 … ÷16, half steps) ─► a53_pwr_clk  (cpu0-3)
                                                    ├─► a53ssmux_perf (÷1 … ÷16, half steps) ─► a53_perf_clk (cpu4-7)
                                                    └─► ccissmux      (÷2.5, set once at boot) ─► cci_clk
```

- **One PLL for everything.** Both clusters and the CCI hang off the same
  HFPLL, so all 8 cores always run the same frequency (msm-cpufreq lists
  `clk_a53_pwr_clk` for every CPU).
- The PLL range is clamped by `apcs_hf_pll.min_rate` / `max_rate`
  (`variable_rate_pll_round_rate()` in `drivers/clk/msm/clock-pll.c`).
- The CCI divider is programmed once at boot (`cpu_clk_cci_set_rate()` has a
  `set_rate_done` latch), so **CCI is always PLL / 2.5**. This is why the
  underclock steps must come from the PLL itself, not from a mux divider (see
  §4.2).
- `qcom,speedN-bin-v0-cl` / `-cci` map each frequency to a CPR corner (the
  voltage vote). `qcom,cpufreq-table` is the list cpufreq exposes. Both must
  agree.

### 3.2 CPU voltage: CPR4

- The SoC carries per-chip **fuses** for 4 *fuse corners* (LowSVS, SVS, NOM,
  Turbo): an open-loop voltage and a ring-oscillator target quotient each.
- The DT defines N *virtual corners* (one per frequency) and
  `qcom,cpr-corner-fmax-map` says which virtual corner is the Fmax of each
  fuse corner.
- Voltages and quotients for corners in between are **linearly interpolated
  by frequency** between fuse corners.
- At runtime CPR closed-loop hardware raises or lowers the voltage until the
  ring oscillators hit the target quotient, bounded by floor and ceiling.

### 3.3 The problem with corners above Turbo (driver fix)

`cpr3_parse_common_corner_data()` assigns every corner *above* the last
fmax-map entry to the Turbo fuse corner. Then
`cpr4_apss_calculate_open_loop_voltages()` and
`cpr4_apss_calculate_target_quotients()` found "the Fmax corner of each fuse
corner" by scanning for the **highest** corner mapped to it. With OC corners
present that is 2400 MHz, not 2016 MHz, so:

- Turbo's fused voltage (calibrated for 2016 MHz) would be placed at 2400 MHz.
- 2016 MHz would get an interpolated NOM→Turbo value, i.e. **lower than its
  fuse**: 2016 MHz becomes unstable even though it is a stock frequency.

That is exactly what Lucifer's 20-corner table did. The fix is in §4.1.

### 3.4 GPU clock and voltage

- `gfx3d_clk_src` picks rates from `ftbl_gfx3d_clk_src`
  (`drivers/clk/msm/clock-gcc-8953.c`). High rates come from **GPLL3, whose
  output is divided by 2** (the second column of `F_MM` is the PLL VCO rate).
  GPLL3's VCO range is 1000–2000 MHz.
- `qcom,gfxfreq-corner` maps each rate to a GFX corner (1 Min SVS … 7 Turbo).
  Corners 1–3 run from the GFX LDO; corners 4–7 run in BHS mode on VDD_CX,
  whose level is voted through RPM (Turbo = `RPM_SMD_REGULATOR_LEVEL_TURBO`).
- KGSL picks frequencies from `qcom,gpu-pwrlevels`; devfreq additionally needs
  matching entries in `gpu_opp_table`. `KGSL_MAX_PWRLEVELS` is **10**,
  including the trailing XO level.

---

## 4. Every change: purpose, reasoning, and later improvements

### 4.1 `drivers/regulator/cpr4-apss-regulator.c` — extrapolate corners above Turbo

**What:**

- New helper `cpr4_apss_extrapolate()`: the same linear formula as
  `cpr3_interpolate()`, but for `x > x2` (which `cpr3_interpolate()` clamps
  to `y2`).
- In both `cpr4_apss_calculate_open_loop_voltages()` and
  `cpr4_apss_calculate_target_quotients()`, the Fmax corner of each fuse
  corner now comes from `vreg->fuse_corner_map[]` (the parsed
  `qcom,cpr-corner-fmax-map`) instead of a top-down scan.
- Corners above the Turbo Fmax get open-loop voltage **and** target quotient
  extrapolated along the NOM → Turbo line.

**Why this way:**

- It keeps every stock corner (≤ 2016 MHz) on exactly its fused, calibrated
  values — the stock behaviour is untouched when the top fmax corner equals
  `corner_count` (true for every upstream DT), because then
  `fuse_corner_map[]` and the scan give the same answer.
- Extrapolating both voltage and quotient lets CPR closed loop keep working
  above Turbo: the hardware raises voltage until the ring oscillators are fast
  enough for the extrapolated target, instead of the chip running blind on a
  fixed voltage.
- The NOM → Turbo slope is the best per-chip data available about how voltage
  must grow with frequency at the top end.

**Expected numbers for this device** (bin 2, rev 3; adjusted fuse
voltages NOM 820 mV @ 1689.6 MHz, Turbo 955 mV @ 2016 MHz → slope ≈ 0.41 mV/MHz):

| Freq (MHz) | Extrapolated open-loop | + margin (§4.4) | DT ceiling | Effective start voltage |
| --- | --- | --- | --- | --- |
| 2150.4 | ~1010 mV | +15 | 1065 | ~1025 mV |
| 2208 | ~1035 mV | +20 | 1090 | ~1055 mV |
| 2304 | ~1075 mV | +25 | 1115 | ~1100 mV |
| 2400 | ~1115 mV | +30 | 1140 | 1140 mV (capped) |

Closed loop then trims down from there (it cannot go above the ceiling).

**Improve later:**

- Silicon is not linear near Fmax; a real per-chip voltage/frequency sweep
  (find the lowest stable voltage per OC step, add margin) beats
  extrapolation. Results could replace extrapolation with explicit per-corner
  `qcom,cpr-open-loop-voltage-adjustment` values.
- If 2400 MHz is pinned at the 1140 mV cap and still unstable, the step is
  beyond what this chip can do; drop it.

### 4.2 `drivers/clk/msm/clock-cpu-8953.c` — HFPLL range 480 – 2400 MHz

**What:** `apcs_hf_pll.max_rate` 2208 → 2400 MHz, `min_rate` 652.8 → 480 MHz.

**Why this way:**

- `max_rate` is the hard clamp in `variable_rate_pll_round_rate()`; without it
  every OC request rounds down to 2208. 2400 MHz = L 125 × 19.2 MHz. The PLL
  already declares VDD_MX SVS sufficient up to 2400 MHz
  (`VDD_MX_HF_FMAX_MAP1(SVS, 2400000000UL)`), so no MX change is needed.
- `min_rate` is lowered rather than letting the mux divide, because the CCI
  divider is fixed at boot: 480 MHz via a divider would be PLL 720 ÷ 1.5,
  leaving CCI at 720 / 2.5 = **288 MHz** on LowSVS voltage (stock 652.8 MHz has
  CCI at 261 MHz). With the PLL itself at 480 MHz the CCI drops to 192 MHz.
  LuciferKernel ran the PLL at 480 MHz for years on this SoC.
- `CLKFLAG_NO_RATE_CACHE` was intentionally *not* removed (unlike Lucifer).

**Improve later:**

- If the HFPLL ever fails to lock at 480 MHz (`PLL lock` errors / hangs when
  pinned to 480), raise `min_rate` back and drop 480/576 from the tables.
- The CCI could be scaled independently (re-arm `set_rate_done`) for a little
  extra memory latency at high CPU clocks, but that is new behaviour, not a
  port.

### 4.3 `drivers/clk/msm/clock-gcc-8953.c` — 725 MHz GPU row

**What:** `F_MM(725000000, 1450000000, gpll3, 1, 0, 0)` in
`ftbl_gfx3d_clk_src` (the table used by the plain msm8953 compatible; the
SDM450 / SDM632 tables are separate and untouched).

**Why this way:** this is the same entry Qualcomm ships in
`ftbl_gfx3d_clk_src_sdm632` for the same Adreno 506 GPU, GPLL3 at 1450 MHz is
inside the 1000–2000 MHz VCO range, and 725 MHz fits within the Turbo VDD_CX
corner Qualcomm already validated for 700/725 MHz on SDM632. 100 MHz needed
no clock change (it is already in the table, from GPLL0).

**Improve later:** a 700 MHz step (also in the SDM632 table) could be added
if KGSL's 10-level limit is raised (`KGSL_MAX_PWRLEVELS` in
`drivers/gpu/msm/kgsl_pwrctrl.h`) or the 133 MHz level is dropped.

### 4.4 `arch/arm64/boot/dts/vendor/qcom/mi8953/tissot/oc.dtsi` (new), included from `tissot.dtsi`

Why a separate tissot file: other msm8953 devices built from this tree
(e.g. sakura) keep stock behaviour, and the whole OC can be turned off by
removing one `#include` line.

| Override | Value | Purpose / reasoning |
| --- | --- | --- |
| `&clock_cpu` `qcom,speed{0,2,6,7}-bin-v0-cl` | 15 rows, `<freq corner>` | One CPR corner per frequency. Same table for all populated bins, so a bin-0/7 chip gets the same steps. |
| `&clock_cpu` `…-cci` | freq × 0.4 | CCI bookkeeping matches PLL / 2.5. |
| `&msm_cpufreq` `qcom,cpufreq-table` | 480 000 … 2 400 000 kHz | The frequencies cpufreq exposes. |
| `&apc_vreg` `qcom,cpr-speed-bin-corners` / `qcom,cpr-corners` | 15 for bins 0, 2, 6, 7 | All populated bins share the same corner count, so every per-corner property can be one 15-value tuple (`cpr3_parse_corner_array_property` "length == corner_count" form). |
| `qcom,cpr-corner-fmax-map` | `<3 5 8 11>` | LowSVS @ 652.8, SVS @ 1036.8, NOM @ 1689.6, **Turbo @ 2016 MHz**. Keeps fuses anchored at their calibrated frequencies on bin 2. For bin 0/7 chips (fused at 2208) this is conservative (their Turbo voltage is applied at 2016). |
| `qcom,corner-frequencies` | 15 Hz values | Drives interpolation/extrapolation. |
| `qcom,cpr-voltage-ceiling` | stock values on stock-equivalent corners; 790 mV for 806.4/1248; **1065 / 1090 / 1115 / 1140 mV** for 2150.4–2400 | Caps open-loop (and therefore the closed-loop range). 1140 mV is the S5 rail limit and the SoC's boost ceiling — never exceed it. 1248 MHz is capped at 790 mV so it stays in mem-acc region 1 (see below). |
| `qcom,cpr-voltage-floor` | 500 mV everywhere | Stock. |
| `qcom,cpr-floor-to-ceiling-max-range` | 50 mV everywhere | Stock for CPR rev ≥ 1. Rev-0 parts used 0 (open-loop only); they are pre-production and not expected on retail tissot. |
| `qcom,cpr-misc-fuse-voltage-adjustment` | stock +30 mV @ 1401.6 for misc = 1; **+15 / +20 / +25 / +30 mV** on the 4 OC corners for both misc values | Added to open-loop **and** closed-loop targets of the OC corners: safety margin on top of extrapolation. |
| `qcom,mem-acc-voltage` | 1 up to 1248 MHz, 2 from 1401.6 MHz | Memory accelerator setting follows voltage: stock uses 1 up to 1036.8 MHz (≤ 790 mV) and 2 from 1401.6 MHz. |
| `qcom,cpr-aging-ref-corner` | 10 | Same frequency (1958.4 MHz) as stock corner 6, matching `qcom,cpr-aging-ref-voltage = 990000`. |
| `&clock_gcc_gfx` `qcom,gfxfreq-corner` | adds `<725000000 7>` | 725 MHz votes GFX corner 7 (Turbo), like 650. 100 MHz needs no row: rates ≤ 133.33 MHz already resolve to corner 1. |
| `&gpu_opp_table` | adds `opp-725`, `opp-100` | devfreq only knows OPPs from this table (see §1). |
| `&msm_gpu` `qcom,gpu-pwrlevels` | 725, 650, 560, 510, 400, 320, 216, 133.3, 100, XO | Rebuilt with `/delete-node/` because indices shift. 725 copies 650's bus votes; 100 copies 133's. Exactly 10 levels = `KGSL_MAX_PWRLEVELS`, so 700 MHz was left out. |
| `qcom,initial-pwrlevel` | 5 | 320 MHz. kgsl restarts at this level on every wake from slumber; at 650 MHz (stock) the GPU sat at 650 nearly all the time it was awake, because the governor rarely got a sample window before the next idle. |
| `qcom,ca-target-pwrlevel` | 4 | Context-aware jump target stays 400 MHz (index moved from 3 to 4). |
| `&thermal_zones` `*-lowf` cooling maps | CPU `THERMAL_MAX_LIMIT - 6`, GPU `3` | Cold-temperature (< 5 °C) voltage floors are expressed as *indexes* into the frequency tables. Re-pointed so they still mean CPU 1401.6 MHz and GPU 510 MHz. |
| `&CPU_COST_0`, `&CLUSTER_COST_0`, `&CLUSTER_COST_1` `busy-cost-data` | adds 480 / 576 / 806.4 MHz rows | Energy model for the underclock steps; see §4.6. |

**Improve later:**

- Per-bin tables. All four bins share one table today; a bin-6 chip (stock max
  1804.8 MHz) would be asked for 2.4 GHz too. If other tissot units turn out
  to be bin 0 or 6, give them their own fmax maps / ceilings.
- Make OC a Kconfig option (`CONFIG_MACH_XIAOMI_TISSOT_OC`) that selects the
  include and the C changes, so non-OC builds come from the same tree.
- Undervolting: done, see §4.5.
- Energy model: done, see §4.6.

### 4.5 CPU undervolt control — `UV_mV_table`

**What:**

- New option `CONFIG_MSM8953_CPU_VOLTAGE_CONTROL` (`drivers/clk/msm/Kconfig`),
  enabled in `arch/arm64/configs/vendor/tissot.config`.
- New file `/sys/devices/system/cpu/cpu0/cpufreq/UV_mV_table`. It's the same
  file under every `cpuN/cpufreq`, because all 8 cores share one policy clock.
- `drivers/regulator/cpr3-regulator.c` gets two exported helpers, declared in
  `include/linux/regulator/cpr3-uv.h`:
  - `cpr3_regulator_get_corner_limits()` reads a corner's floor and ceiling.
  - `cpr3_regulator_set_corner_ceiling()` moves a corner's ceiling and shifts
    its whole CPR window and target quotients with it.
- `drivers/clk/msm/clock-cpu-8953.c` implements the attribute
  (`show_UV_mV_table()` / `store_UV_mV_table()`). It exports
  `msm8953_uv_mv_table`, declared in `include/linux/clk/msm8953-cpu-uv.h`.
- `drivers/cpufreq/qcom-cpufreq.c` adds the attribute to `msm_freq_attr[]`.
- `struct cpr3_corner` gains `uv_adjust_volt`.

**Usage:**

```sh
# Read: one line per CPU step, highest first, showing the CPR ceiling
cat /sys/devices/system/cpu/cpu0/cpufreq/UV_mV_table
# 2400mhz: 1140 mV
# 2304mhz: 1115 mV
# ...
# 480mhz: 715 mV

# Write: exactly one value per line above, in the same order (15 values)
echo "1120 1100 1080 1055 1050 980 920 865 860 790 790 790 715 715 715" \
  > /sys/devices/system/cpu/cpu0/cpufreq/UV_mV_table
```

**What a write does, per step:**

1. The value is clamped to 500–1140 mV, rounded **up** to 5 mV, and capped
   at the corner's DT ceiling (`abs_ceiling_volt`).
2. The difference from the current ceiling is the step's adjustment. It's
   applied like a CPR aging margin (`cpr3_regulator_readjust_volt_and_quot()`
   is the model):
   - ceiling, floor and open-loop voltage all move by it, so the closed-loop
     range (ceiling − 50 mV floor) is kept;
   - each active RO's target quotient moves by
     `cpr3_quot_adjustment(ro_scale, adjustment)`, so CPR aims lower (or
     higher) by the same amount and keeps adapting to temperature, load and
     droop;
   - `last_volt` moves too and is kept inside the new range;
   - the unaged voltages move, so a later aging adjustment keeps it.
3. `cpr3_regulator_update_ctrl_state()` reprograms the CPR hardware right
   away.

Before this, lowering a ceiling only pulled the floor down to
`min(original floor, new ceiling)` and left the quotients alone. Any
undervolt of 50 mV or more made floor = ceiling on every step, so closed loop
had no range and every step ran at a fixed voltage (seen on the device with
−75 mV: `floor_volt == ceiling_volt` on all 19 corners).

**Why this way:**

- **Format:** it's the classic faux123 format (`NNNmhz: NNN mV`, a write is
  the same number of values in the same order). Kernel Adiutor, SmartPack and
  EX Kernel Manager already read and write it.
- **One value per step (the ceiling):** it's what kernel managers write, and
  it's the top of the CPR window, so moving it moves the window. Lucifer
  exposed ceiling, floor *and* `last_volt` per cluster. The two clusters share
  one corner here, so that duplicated every line, and `last_volt` is owned by
  closed loop.
- **All-or-nothing writes:** every value is parsed before any is applied, so
  a truncated or garbage write changes nothing (`-EINVAL`).
- **Clamp at 1140 mV:** that's the PM8953 S5 maximum and
  `MSM8953_APSS_BOOST_CEILING_VOLT`, so userspace can't overvolt past the
  rail.
- **Attribute in the msm cpufreq driver, not the cpufreq core:** Lucifer
  patched `drivers/cpufreq/cpufreq.c`. Using `msm_freq_attr[]` keeps the core
  untouched and puts the file at the usual path.
- **Lucifer's older `CONFIG_CPU_VOLTAGE_TABLE` isn't ported:** it wrote
  millivolts into `vdd_uv[]`, which holds CPR corner numbers on this SoC.

**Limits to know:**

- Settings don't survive a reboot. Re-apply them from an init script or with
  a kernel manager's "apply on boot".
- CPR aging adjustment runs once early in boot and recomputes limits from
  the unaged values. Those move with every write, so a write made before
  aging finishes is kept.
- A step can't go above its DT ceiling (`qcom,cpr-voltage-ceiling`).
- A ceiling that's too low crashes or freezes the device at that step. Lower
  in 10–15 mV steps, stress-test each one (§6), and keep a known-good set.

**Improve later:**

- Persist a validated table in the DT, as a negative per-corner
  `qcom,cpr-misc-fuse-voltage-adjustment`, so no boot script is needed.
- A GPU equivalent (GFX LDO corners 1–3 and the CX level for higher corners)
  is a separate piece of work.
- A floor file (`UV_floor_mV_table`) could be added if anyone needs to set
  the closed-loop range width directly.

### 4.6 Energy model — underclock rows

**What:** `busy-cost-data` of `CPU_COST_0`, `CLUSTER_COST_0` and
`CLUSTER_COST_1` (from `msm8953-cpu.dtsi`) is overridden in `oc.dtsi` with the
same rows plus 480, 576 and 806.4 MHz.

**Finding:** the base tree's energy model already had rows up to 2400 MHz,
and no CPU node has a `clock-frequency`. The legacy EM driver
(`drivers/energy_model/legacy_em_dt.c`) recomputes each row's frequency as
`row × policy max / last row`.
- On the stock 2016 MHz max, every EM frequency was therefore scaled by
  2016 / 2400 = 0.84 and didn't match the real OPPs.
- With the 2400 MHz max the rows line up exactly. That's why the last row
  must stay 2400000.

**Why these values:** 480, 576 and 652.8 MHz share the LowSVS voltage, and
806.4 MHz sits between LowSVS and SVS. Dynamic power then scales roughly
with frequency:
- CPU cost: 3, 4, 5 (existing), 7.
- Cluster costs: interpolated the same way between the existing neighbours.

Without these rows, EAS priced 480 and 576 MHz the same as 652.8 MHz, so it
saw no energy benefit in them.

**Improve later:** the cost numbers in the base tree look estimated, not
measured. Measuring power per OPP (battery current at fixed frequency, one
cluster busy) would give EAS real data.

### 4.7 Scheduler boosting — schedtune replaced by uclamp

**Finding (on the device):** Android 16's `task_profiles.json` boosts tasks
through `cpu.uclamp.min`, `cpu.uclamp.max` and `cpu.uclamp.latency_sensitive`
in the `/dev/cpuctl/*` groups. The kernel was built with `CONFIG_SCHED_TUNE=y`,
which excludes `CONFIG_UCLAMP_TASK`, so those files didn't exist. Android no
longer mounts the schedtune cgroup either. As a result, neither boost
mechanism was active: top-app got no frequency boost and no prefer-idle
placement.

**What:**
- `tissot.config`: `# CONFIG_SCHED_TUNE is not set`, `CONFIG_UCLAMP_TASK=y`,
  `CONFIG_UCLAMP_TASK_GROUP=y`. The uclamp code was already in the tree;
  only the config was missing.
- `kernel/sched/cpufreq_schedutil.c`, WALT `sugov_get_util()`: without
  schedtune, the `stune_util()` stub returns `cpu_util_cfs()`, which is the
  PELT signal. That would quietly drop WALT from frequency selection. Under
  `!CONFIG_SCHED_TUNE` it now returns `cpu_util_freq()` (WALT), capped at
  capacity and clamped by `uclamp_rq_util_with()`.
- `kernel/sched/fair.c`: four placement checks still called
  `schedtune_task_boost()` / `schedtune_prefer_idle()`, which are stubbed to 0
  without schedtune. They now call `uclamp_boosted()` /
  `uclamp_latency_sensitive()`. With schedtune enabled these map back to the
  schedtune calls (`core.c`), so a schedtune build behaves as before.

**Side effect:** WALT's related-thread-group colocation keyed on
`schedtune.colocate` is off (`schedtune_task_colocated()` returns false).
On a single-cluster SoC there's nothing to colocate onto, so this costs
nothing here.

**Verify after flashing:** `/dev/cpuctl/top-app/cpu.uclamp.min` exists, and
`cat /dev/cpuctl/*/cpu.uclamp.latency_sensitive` shows 1 for top-app.

### 4.8 Default CPU governor

`CONFIG_CPU_FREQ_DEFAULT_GOV_SCHEDUTIL=y` (was performance). Until init picks
a governor, the CPU no longer sits at the 2400 MHz OC step with nothing
managing it.

### 4.9 GPU wake level

`qcom,initial-pwrlevel` is now 5 (320 MHz); see the table in 4.4.
`kgsl_pwrctrl_enable()` restarts the GPU at `default_pwrlevel` on every wake
from slumber. At 650 MHz the GPU therefore ran at 650 almost all the time it
was awake, because the idle timer (80 ms) usually fired before
msm-adreno-tz had a sample window to step down. When idle, `gpuclk` still
shows the last level set; the real clock is gated (`gcc_oxili_gfx3d_clk`
enable = 0).

### 4.10 Default I/O scheduler — kyber

`block/elevator.c` picked bfq whenever it was built. It now picks the first
of kyber, bfq and mq-deadline that is built in.

**Measured on the device (2026-10-03):** cold launches (`am force-stop`,
`drop_caches`, `am start -W`, TotalTime in ms), 4 rounds per scheduler,
interleaved:

| App | bfq | kyber | mq-deadline |
| --- | --- | --- | --- |
| Calculator | 1087 | 1102 | 1067 |
| Chrome | 757 | 722 | 729 |
| Contacts | 90 | 81 | 87 |
| Clock | 1032 | 1037 | 1049 |
| Dialer | 1570 | 1456 | 1462 |
| Settings | 1294 | 1305 | 1297 |
| **Sum of medians** | 5829 | 5702 | 5690 |
| **Worst launch** | 1703 | 1465 | 1486 |

Medians are within about 2% of each other. bfq had the highest worst case
(Dialer 1416 - 1703 ms against about 1450 for the others), which matches
published tail-latency results. kyber and mq-deadline are tied. kyber was
chosen for the lowest worst case and its lower per-request CPU cost on the
A53 cores. Switching at runtime is
`echo kyber > /sys/block/mmcblk0/queue/scheduler`.

---

## 5. Build

### Toolchain

- Android NDK 29 LLVM (clang 21, `Android (13989888 … based on r563880c)`):
  `$HOME/Android/Sdk/ndk/29.0.14206865/toolchains/llvm/prebuilt/linux-x86_64/bin`
- Full LLVM build (`LLVM=1 LLVM_IAS=1`); `ccache` optional.

### Commands

```sh
cd kernel_xiaomi_msm8953

export PATH="$HOME/Android/Sdk/ndk/29.0.14206865/toolchains/llvm/prebuilt/linux-x86_64/bin:$PATH"
export ARCH=arm64 LLVM=1 LLVM_IAS=1

# 1. Config (only needed once, or after changing config fragments).
#    Base perf defconfig + Xiaomi msm8953 fragment + tissot fragment.
make O=out vendor/msm8953-perf_defconfig vendor/mi8953.config vendor/tissot.config

# 2. Kernel + device trees
make O=out -j"$(nproc)" CC="ccache clang" Image dtbs
#    (or CC=clang without ccache)

# 3. Flashable kernel: gzip Image with the DTB appended (what tissot boots, §6.1)
make O=out -j"$(nproc)" CC="ccache clang" Image.gz-dtb
```

(The config command was checked to reproduce the existing `out/.config`
byte-for-byte, comments aside.)

### Outputs

| File | What |
| --- | --- |
| `out/arch/arm64/boot/Image` | Kernel |
| `out/arch/arm64/boot/dts/vendor/qcom/tissot-titanium.dtb` | Device tree with the OC tables |
| `out/arch/arm64/boot/Image.gz-dtb` | **What the phone boots**: gzip kernel + appended DTB (target `Image.gz-dtb`, see §6) |

Quick sanity check that the DTB really carries the new tables:

```sh
dtc -I dtb -O dts out/arch/arm64/boot/dts/vendor/qcom/tissot-titanium.dtb 2>/dev/null \
  | grep -A16 'qcom,cpufreq-table'
```

---

## 6. Flash and test

### 6.1 What the phone boots

Read from the device's `boot_a` partition (read-only, over adb):

| Item | Value |
| --- | --- |
| Partitions | A/B: `boot_a` / `boot_b` (no `dtbo`, no `vendor_boot`) |
| Boot image header | **v0**, page size 2048 |
| Kernel | gzip-compressed with the DTB **appended**: `Image.gz-dtb` |
| Separate DTB section | none, so the DTB must be inside the kernel file |

So the file to ship is `out/arch/arm64/boot/Image.gz-dtb`. Build it with:

```sh
make O=out -j"$(nproc)" CC="ccache clang" Image.gz-dtb
```

`Image.gz-dtb` is `Image.gz` plus **every** `.dtb` found under
`out/arch/arm64/boot/dts/` (`arch/arm64/boot/Makefile`). Make sure that
directory holds only `tissot-titanium.dtb`, or a stale DTB from another target
gets appended too:

```sh
find out/arch/arm64/boot/dts -name '*.dtb'
```

### 6.2 Test-boot first (no flashing)

An OC kernel that's unstable at boot frequencies can boot-loop.
`fastboot boot` runs a boot image once without writing it, so a reboot always
returns to the installed kernel.

```sh
# 1. Copy the current boot image off the phone (root)
adb shell su -c 'dd if=/dev/block/by-name/boot$(getprop ro.boot.slot_suffix) of=/sdcard/boot.img'
adb pull /sdcard/boot.img

# 2. Swap in the new kernel with magiskboot (from the Magisk APK: lib/x86_64/libmagiskboot.so)
magiskboot unpack boot.img
cp out/arch/arm64/boot/Image.gz-dtb kernel
magiskboot repack boot.img new-boot.img

# 3. Boot it once
adb reboot bootloader
fastboot boot new-boot.img
```

Because only `kernel` is replaced, the ramdisk (including Magisk, if
installed) stays as it was. Run the verification checklist below. Only when
it's stable, install permanently with `fastboot flash boot_a new-boot.img`
(the active slot), or use the zip from §6.3.

### 6.3 Flashable zip (AnyKernel3)

LuciferKernel did the same. Its `.circleci/build.sh` copies the kernel and
DTBs into its AnyKernel3 fork (`d4rk-lucif3r/Anykernel3-Tissot`) and runs
`zip -r9`. That fork shipped separate treble/non-treble DTBs for 4.9. Here a
single `Image.gz-dtb` is enough, so upstream AnyKernel3 is used as-is.

**One-time setup:**

```sh
cd ~/development/kernel
git clone --depth=1 https://github.com/osm0sis/AnyKernel3
```

Edit `AnyKernel3/anykernel.sh` and change only these fields in the template;
keep everything else as it is:

| Field | Value | Why |
| --- | --- | --- |
| `kernel.string` | e.g. `Titanium tissot OC/UC by <you>` | Shown while flashing |
| `do.devicecheck` | `1` | Refuse to flash on anything but tissot |
| `do.modules` | `0` | No `=m` drivers in this config |
| `do.systemless` | `0` | No modules to install |
| `device.name1` | `tissot` | Matches `ro.product.device` |
| `device.name2`… | empty | |
| `BLOCK` (`block=` in older templates) | `boot` | Boot partition by name |
| `IS_SLOT_DEVICE` (`is_slot_device=`) | `1` | A/B: flash the active slot |
| `RAMDISK_COMPRESSION` | `auto` | |

For the install step at the bottom of the template, use the **kernel-only**
variant: `split_boot;` then `flash_boot;`. It replaces just the kernel and
leaves the ramdisk (and Magisk) untouched. Don't use `dump_boot`/`write_boot`;
those unpack the ramdisk for patching, which isn't needed here.

**Each release:**

```sh
cd ~/development/kernel/kernel_xiaomi_msm8953
export PATH="$HOME/Android/Sdk/ndk/29.0.14206865/toolchains/llvm/prebuilt/linux-x86_64/bin:$PATH"
export ARCH=arm64 LLVM=1 LLVM_IAS=1

make O=out vendor/msm8953-perf_defconfig vendor/mi8953.config vendor/tissot.config
make O=out -j"$(nproc)" CC="ccache clang" Image.gz-dtb

AK=~/development/kernel/AnyKernel3
cp out/arch/arm64/boot/Image.gz-dtb "$AK/"
cd "$AK"
ZIP="tissot-oc-$(date +%Y%m%d-%H%M).zip"
zip -r9 "../$ZIP" * -x .git README.md '*placeholder'
ls -l "../$ZIP"
```

AnyKernel3 picks the kernel file from the zip root by name (`Image.gz-dtb`).
Remove an old `Image.gz-dtb` before copying, never keep two kernel files in
`$AK`.

**Install:** reboot to recovery (OrangeFox/TWRP for tissot) and flash the
zip, or use `adb sideload tissot-oc-*.zip`. AnyKernel3 writes to the
**current** slot only.
- After an OTA or ROM update (which switches slots and brings its own
  kernel), flash the zip again.
- Keep the previous zip, or the stock `boot.img` from §6.2, to roll back.

### Verification checklist

Undervolt control (`CONFIG_MSM8953_CPU_VOLTAGE_CONTROL`) needs the config
regenerated after pulling these changes:
`make O=out vendor/msm8953-perf_defconfig vendor/mi8953.config vendor/tissot.config`.

```sh
adb shell su -c '
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_available_frequencies
cat /sys/class/kgsl/kgsl-3d0/gpu_available_frequencies
cd /sys/kernel/debug/cpr3-regulator/apc/thread0/apc_corner
cat corner_count
n=$(cat corner_count); i=1
while [ $i -le $n ]; do echo $i > corner/index
  echo "c$i ol=$(cat corner/open_loop_volt) ce=$(cat corner/ceiling_volt) fl=$(cat corner/floor_volt) last=$(cat corner/last_volt)"
  i=$((i+1)); done
dmesg | grep -iE "cpr|clock-cpu|clock_cpu|gfx|kgsl" | grep -iE "err|fail|invalid"
'
```

Expected:

- CPU frequencies 480000 … 2400000; GPU 725000000 … 100000000.
- `corner_count` = 15. Corners 1–11 open-loop **≥** today's values in §1
  (650 … 955 mV) — that proves the driver fix kept the stock corners on their
  fuses. Corners 12–15 increasing and ≤ 1140 mV.
- No CPR / clock / KGSL errors.

Undervolt control:

```sh
adb shell su -c '
T=/sys/devices/system/cpu/cpu0/cpufreq/UV_mV_table
cat $T                                  # 15 lines, 2400mhz ... 480mhz
cur=$(sed "s/.*: \([0-9]*\) mV/\1/" $T | tr "\n" " ")
set -- $cur; top=$(( $1 - 10 )); shift
echo "$top $*" > $T                      # top step 10 mV lower
head -1 $T                               # shows the lowered value
echo "900" > $T; echo "rc=$?"            # too few values: rejected
echo "abc $*" > $T; echo "rc=$?"         # garbage: rejected
echo "$cur" > $T                         # restore
'
```

Cross-check with debugfs: corner 15's `ceiling_volt` follows the first
value, and `floor_volt` stays ≤ the ceiling.

### Stability testing

1. Pin the CPU to the top step:
   `echo 2400000 > /sys/devices/system/cpu/cpu0/cpufreq/scaling_min_freq`
   (and `cpu4`), run a CPU load (Geekbench loop, `stress-ng --cpu 8`,
   or a long compile) for 15+ minutes. Watch `last_volt` on corner 15 and
   temperatures (`/sys/class/thermal/thermal_zone*/temp`).
2. Repeat at 2304, 2208, 2150.4 MHz.
3. GPU: run 3DMark / a demanding game; check
   `cat /sys/class/kgsl/kgsl-3d0/gpuclk` hits 725000000.
4. Underclock: `scaling_max_freq` = 480000 and GPU `max_gpuclk` = 100000000;
   the UI must stay usable, no hangs.

If a step crashes: raise its value in `qcom,cpr-misc-fuse-voltage-adjustment`
(both rows) by 10–15 mV, staying under its ceiling — or remove the step from
all tables (cl, cci, cpufreq-table, corner-frequencies, ceilings, floors,
ranges, misc adjustment, mem-acc, corner counts) if it is already capped at
1140 mV.

---

## 7. Risks

- **Heat / throttling.** Thermal zones were left at stock trip points, so the
  device will throttle as before — just from a higher starting point. 2.4 GHz
  at ~1.1 V uses noticeably more power than 2.0 GHz at 0.93 V.
- **Silicon lottery.** The numbers above are for one bin-2 / rev-3 chip.
- **Rail limit.** 1140 mV is the hard maximum; do not raise any ceiling past
  it.
- **GPU 725 MHz** runs at the existing Turbo VDD_CX vote — no extra voltage —
  so it relies on the same headroom Qualcomm uses on SDM632.

## 8. Files touched

| File | Change |
| --- | --- |
| `drivers/regulator/cpr4-apss-regulator.c` | Extrapolation of corners above the Turbo fuse corner |
| `drivers/clk/msm/clock-cpu-8953.c` | HFPLL range 480 – 2400 MHz |
| `drivers/clk/msm/clock-gcc-8953.c` | 725 MHz GPU clock row |
| `arch/arm64/boot/dts/vendor/qcom/mi8953/tissot/oc.dtsi` | New: all tissot OC/UC tables and energy-model rows |
| `arch/arm64/boot/dts/vendor/qcom/mi8953/tissot/tissot.dtsi` | `#include "oc.dtsi"` |
| `drivers/regulator/cpr3-regulator.c`, `cpr3-regulator.h` | `cpr3_regulator_{get_corner_limits,set_corner_ceiling}()`, `uv_adjust_volt` |
| `include/linux/regulator/cpr3-uv.h` | New: declarations of the CPR3 helpers |
| `drivers/clk/msm/clock-cpu-8953.c` | `UV_mV_table` show/store (`msm8953_uv_mv_table`) |
| `include/linux/clk/msm8953-cpu-uv.h` | New: declaration of `msm8953_uv_mv_table` |
| `drivers/cpufreq/qcom-cpufreq.c` | Adds `UV_mV_table` to the msm cpufreq attributes |
| `drivers/clk/msm/Kconfig` | `CONFIG_MSM8953_CPU_VOLTAGE_CONTROL` |
| `arch/arm64/configs/vendor/tissot.config` | Enables `CONFIG_MSM8953_CPU_VOLTAGE_CONTROL` |
| `kernel/sched/cpufreq_schedutil.c` | WALT util + uclamp when schedtune is off (4.7) |
| `kernel/sched/fair.c` | Boost / prefer-idle checks go through `uclamp_*()` (4.7) |
| `arch/arm64/configs/vendor/tissot.config` | uclamp instead of schedtune; schedutil as default governor (4.7, 4.8) |
| `block/elevator.c` | kyber as default blk-mq scheduler (4.10) |
| `docs/oc-uc.md` | This document |
