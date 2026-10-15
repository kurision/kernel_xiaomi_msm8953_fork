#!/system/bin/sh
# SPDX-License-Identifier: GPL-2.0
# Recompress zram pages that stayed untouched for a whole interval with the
# secondary algorithm (zstd, see post-fs-data.sh). Any access
# clears a page's idle mark, so only cold pages pay zstd's slower swap-in.
# ponytail: fixed 10 min interval, runs whether or not the screen is on.
# No threshold: in this zram, threshold= also rejects any result that is
# not below it, which skipped nearly every swap page (measured: nothing
# recompressed with threshold=1024; 280 -> 182 MB compressed without).
Z=/sys/block/zram0
INTERVAL=600

until [ "$(getprop sys.boot_completed)" = 1 ]; do sleep 5; done
grep -q zstd $Z/recomp_algorithm 2>/dev/null || exit 0

echo all > $Z/idle
while sleep $INTERVAL; do
	echo type=idle > $Z/recompress
	echo all > $Z/idle
done
