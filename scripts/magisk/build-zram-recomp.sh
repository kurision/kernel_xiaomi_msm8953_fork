#!/usr/bin/env bash
# Package the tissot-zram-recomp Magisk module.
set -euo pipefail
src=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/tissot-zram-recomp" && pwd)
out=${1:-$PWD/tissot-zram-recomp.zip}
rm -f -- "$out"
(cd -- "$src" && zip -qr -X "$out" module.prop post-fs-data.sh service.sh META-INF)
echo "$out"
