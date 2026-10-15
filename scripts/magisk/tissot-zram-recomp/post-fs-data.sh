#!/system/bin/sh
# SPDX-License-Identifier: GPL-2.0
# Register zstd as zram0's secondary (recompression) algorithm. It must be
# set before init sizes the device (swapon_all at ~45 s); post-fs-data runs
# well before that. LZ4 stays the primary algorithm for fast swap-in.
echo algo=zstd > /sys/block/zram0/recomp_algorithm
