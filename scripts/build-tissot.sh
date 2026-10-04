#!/usr/bin/env bash
# Build the tissot kernel and package a flashable AnyKernel3 zip.
set -euo pipefail

if [[ $# != 0 ]]; then
    echo "Usage: $0"
    echo "Overrides: OUT_DIR, ANYKERNEL_DIR, LLVM_BIN, JOBS"
    if [[ ${1:-} == --help ]]; then exit 0; fi
    exit 2
fi

repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
out_dir=${OUT_DIR:-$repo_dir/out}
llvm_bin=${LLVM_BIN:-$HOME/Android/Sdk/ndk/29.0.14206865/toolchains/llvm/prebuilt/linux-x86_64/bin}
export PATH="$llvm_bin:$PATH"
export ARCH=arm64 LLVM=1 LLVM_IAS=1

for tool in clang make python3; do
    command -v "$tool" >/dev/null || { echo "Missing tool: $tool" >&2; exit 1; }
done
compiler=clang
if command -v ccache >/dev/null; then
    compiler="ccache clang"
fi

cd -- "$repo_dir"
make O="$out_dir" vendor/msm8953-perf_defconfig vendor/mi8953.config vendor/tissot.config
make O="$out_dir" -j"${JOBS:-$(nproc)}" CC="$compiler" Image.gz-dtb
OUT_DIR="$out_dir" "$repo_dir/scripts/package-tissot.sh"
