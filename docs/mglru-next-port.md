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

## Deferred backports

### zswap as a zram frontswap — rejected, not a config change

The zswap in this tree is the v3.11-era implementation, not the modern one:
`mm/Kconfig:564` declares `ZSWAP` as `depends on FRONTSWAP && CRYPTO=y` with
help text that says "as of v3.11", and `mm/Kconfig:485` documents `FRONTSWAP`
as caching pages in "transcendent memory" (TMEM) — hardware this MSM8953 does
not have. `out-oc/.config` has `# CONFIG_FRONTSWAP is not set` and
`# CONFIG_ZPOOL is not set`, and no `ZSWAP` line at all.

There is also no layer to insert it behind: `drivers/block/zram/zram_drv.c`
contains no frontswap reference and compresses directly through
`zcomp_compress()` (line 1463) and `zcomp_decompress()` (line 1383).

The v5.19+ zswap is a rewrite (`zswap_pool`, `zswap_entry`, the `zslot`
allocator) that calls memcg interfaces a 4.19 `mem_cgroup` does not have.
Adopting it is a port, not a backport. What this tree can use for the same
problem — draining compressed pages back to the backing store instead of
leaving them in RAM — is already enabled: `CONFIG_ZRAM_WRITEBACK=y` and
`CONFIG_ZRAM_DEFAULT_COMP_ALGORITHM="lz4"` in `out-oc/.config`.

Deferred to the ACK 6.18 route, where a 6.18 zswap can be taken as-is.

### msm8953-mainline 7.1.3 vendor drivers — measured, then declined

Of the six drivers the fork documentation names, two exist here already, two
do not exist at all, and two exist but must stay disabled:

| fork driver | this tree | state |
| --- | --- | --- |
| camss | `drivers/media/platform/qcom/camss/` (17 files) | present, `# CONFIG_VIDEO_QCOM_CAMSS is not set` |
| venus | `drivers/media/platform/qcom/venus/` | present, no Kconfig symbol in `out-oc/.config` |
| qcom-smbchg | `drivers/power/supply/qcom/` (`qpnp-smbcharger.c`, `smb5-lib.c`, …) | present as CAF `qpnp-smb*`, `CONFIG_QPNP_SMBCHARGER=y` |
| pm8994-fg | `drivers/power/supply/qcom/qpnp-fg.c`, `qpnp-fg-gen3.c`, `qpnp-fg-gen4.c` | present as CAF `qpnp-fg`, `CONFIG_QPNP_FG=y` |
| s5k2xx | none — no `s5k2*` sensor under `drivers/media/i2c/` | absent |
| qcom-spmi-haptics | none — `drivers/input/misc/qti-haptics.c` binds `qcom,haptics`, `qcom,pm660-haptics`, `qcom,pm8150b-haptics` instead, and is `# CONFIG_INPUT_QTI_HAPTICS is not set` | no counterpart for the fork's binding |

camss and venus are declined, not flipped: the device tree is written for the
CAF stack — `arch/arm64/boot/dts/vendor/qcom/mi8953/tissot/camera.dtsi:1`
opens with `&cci {` and children such as `qcom,actuator@1` and
`qcom,eeprom@2` carrying `qcom,slave-addr`, `qcom,page0`,
`qcom,eeprom-name = "ofilm_s5k5e8"` — and that binding vocabulary plus the
ROM's vendor camera/video blobs are what the running system uses. Swapping in
the fork's camss means rewriting the DT vocabulary and would break camera on
this ROM.

Device-side evidence that the CAF video stack is the live path: on the
branch-tip kernel, `/sys/kernel/debug/wakeup_sources` reports active
`video1`, `video2` and `video3` sources, i.e. video4linux nodes are open.
The `ls /dev/video*` and `dumpsys media.camera` cross-checks from the
original plan have not been run yet; they remain open.

s5k2xx and qcom-spmi-haptics are not backports at all — there is nothing to
port from — they would be new drivers plus DT written against the fork's
binding, on a CAF 4.19 vendor stack. Out of scope. Haptics is the only one
with a plausible future home, and it belongs to the ACK 6.18 route where the
`msm8953-mainline` 7.1.3 line is an actual donor.
