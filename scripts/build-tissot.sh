#!/usr/bin/env bash
# Build the tissot kernel and package a flashable AnyKernel3 zip.
set -euo pipefail

# 12 is the sweet spot on this host (32 cores, but wider builds thrash;
# see docs/HANDOFF.md).
default_jobs=12

usage() {
   echo "Usage: $0 [-j THREADS]"
   echo "Options:"
   echo "  -j, --jobs THREADS   parallel make jobs (default: $default_jobs)"
   echo "Overrides: OUT_DIR, ANYKERNEL_DIR, LLVM_BIN, JOBS"
}

jobs=${JOBS:-$default_jobs}
while [[ $# -gt 0 ]]; do
   case "$1" in
      -j|--jobs)
         [[ $# -ge 2 ]] || { echo "Missing value for $1" >&2; exit 2; }
         jobs=$2
         shift 2
         ;;
      -j*) jobs=${1#-j}; shift ;;
      --jobs=*) jobs=${1#*=}; shift ;;
      -h|--help) usage; exit 0 ;;
      *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
   esac
done

[[ $jobs =~ ^[0-9]+$ ]] && (( jobs >= 1 )) || {
   echo "Invalid thread count: $jobs" >&2; exit 2; }

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
# Ensure md5 file exists (kernel/gen_kheaders.sh, CONFIG_IKHEADERS)
touch "$repo_dir/kernel/kheaders.md5"
# Build the kernel image
make O="$out_dir" -j"$jobs" CC="$compiler" Image.gz-dtb
OUT_DIR="$out_dir" "$repo_dir/scripts/package-tissot.sh"
