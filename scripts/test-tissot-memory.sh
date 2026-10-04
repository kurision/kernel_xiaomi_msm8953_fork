#!/usr/bin/env bash
# Repeat the 14-launch memory test on an already booted, rooted tissot.
set -euo pipefail

if [[ $# -gt 2 || ${1:-} == --help ]]; then
    echo "Usage: $0 [SWAPPINESS [WATERMARK_SCALE_FACTOR]]"
    echo "Optional value: 0..200, restored after the test. No argument keeps current settings."
    echo "Optional watermark scale: 1..1000, also restored after the test."
    echo "Overrides: ANDROID_SERIAL, OUT_DIR"
    echo "For comparisons, boot the same kernel afresh and leave the phone idle during each run."
    if [[ ${1:-} == --help ]]; then exit 0; fi
    exit 2
fi
watermark=${2:-}
if [[ -n $watermark ]]; then
    if [[ ! $watermark =~ ^[0-9]{1,4}$ ]] || (( 10#$watermark < 1 || 10#$watermark > 1000 )); then
        echo "WATERMARK_SCALE_FACTOR must be an integer from 1 to 1000" >&2
        exit 2
    fi
    watermark=$((10#$watermark))
fi
target=${1:-}
if [[ -n $target ]]; then
    if [[ ! $target =~ ^[0-9]{1,3}$ ]] || (( 10#$target > 200 )); then
        echo "SWAPPINESS must be an integer from 0 to 200" >&2
        exit 2
    fi
    target=$((10#$target))
fi

repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
serial=${ANDROID_SERIAL:-2819f2320604}
adb_cmd=(adb -s "$serial")
"${adb_cmd[@]}" get-state >/dev/null
device=$("${adb_cmd[@]}" shell getprop ro.product.device | tr -d '\r')
if [[ $device != tissot ]]; then
    echo "Expected tissot, connected device is $device" >&2
    exit 1
fi
if [[ $("${adb_cmd[@]}" shell getprop sys.boot_completed | tr -d '\r') != 1 ]]; then
    echo "Wait for Android to finish booting before testing" >&2
    exit 1
fi
root_shell() { "${adb_cmd[@]}" shell "su -c '$1'"; }
original=$(root_shell 'cat /proc/sys/vm/swappiness' | tr -d '\r\n')
original_watermark=$(root_shell 'cat /proc/sys/vm/watermark_scale_factor' | tr -d '\r\n')
if [[ ! $original =~ ^[0-9]+$ || ! $original_watermark =~ ^[0-9]+$ ]]; then
    echo "Could not read memory settings; root access is required" >&2
    exit 1
fi

out_dir=${OUT_DIR:-$repo_dir/out}
mkdir -p -- "$out_dir/memory-tests"
result_dir=$(mktemp -d "$out_dir/memory-tests/$(date +%Y%m%d-%H%M%S)-swappiness-${target:-$original}-watermark-${watermark:-$original_watermark}-XXXXXX")
log_pid=
changed=0
watermark_changed=0
cleanup() {
    local status=$?
    trap - EXIT
    if [[ -n $log_pid ]]; then
        kill "$log_pid" 2>/dev/null || true
        wait "$log_pid" 2>/dev/null || true
    fi
    if (( watermark_changed )); then
        if root_shell "echo $original_watermark > /proc/sys/vm/watermark_scale_factor"; then
            echo "Restored watermark_scale_factor=$original_watermark"
        else
            echo "Could not restore watermark scale; reconnect and restore $original_watermark" >&2
            status=1
        fi
    fi
    if (( changed )); then
        if root_shell "echo $original > /proc/sys/vm/swappiness"; then
            echo "Restored swappiness=$original"
        else
            echo "Could not restore swappiness; reconnect and restore $original" >&2
            status=1
        fi
    fi
    echo "Results: $result_dir"
    exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
exec > >(tee "$result_dir/test.txt") 2>&1

if [[ -n $target && $target != "$original" ]]; then
    changed=1
    root_shell "echo $target > /proc/sys/vm/swappiness"
    actual=$(root_shell 'cat /proc/sys/vm/swappiness' | tr -d '\r\n')
    if [[ $actual != "$target" ]]; then
        echo "Requested swappiness=$target, read back $actual" >&2
        exit 1
    fi
fi
if [[ -n $watermark && $watermark != "$original_watermark" ]]; then
    watermark_changed=1
    root_shell "echo $watermark > /proc/sys/vm/watermark_scale_factor"
    actual=$(root_shell 'cat /proc/sys/vm/watermark_scale_factor' | tr -d '\r\n')
    if [[ $actual != "$watermark" ]]; then
        echo "Requested watermark scale=$watermark, read back $actual" >&2
        exit 1
    fi
fi
"${adb_cmd[@]}" logcat -b all -v monotonic -T 1 -s lowmemorykiller:I > "$result_dir/lmkd.txt" 2>&1 &
log_pid=$!
sleep 1
kill -0 "$log_pid" || { echo "Could not start continuous lmkd capture" >&2; exit 1; }

apps=(
    com.android.chrome/com.google.android.apps.chrome.Main
    com.android.vending/.AssetBrowserActivity
    org.lineageos.aperture/.CameraLauncher
    com.google.android.dialer/.extensions.GoogleDialtactsActivity
    com.google.android.contacts/com.android.contacts.activities.PeopleActivity
    com.android.messaging/.ui.conversationlist.ConversationListActivity
    com.google.android.apps.searchlite/.ui.SearchActivity
    com.google.android.calculator/com.android.calculator2.Calculator
    com.google.android.deskclock/com.android.deskclock.DeskClock
    com.topjohnwu.magisk/.ui.MainActivity
    flar2.devcheck/.MainActivity
    org.localsend.localsend_app/.MainActivity
    com.android.settings/.Settings
    com.android.chrome/com.google.android.apps.chrome.Main
)
snapshot() {
    "${adb_cmd[@]}" shell 'uname -r; echo UPTIME; cat /proc/uptime; grep -E "MemAvailable|SwapFree" /proc/meminfo; echo VMSTAT; grep -E "allocstall|pgscan_direct|pgsteal_direct|pswpin|pswpout|oom_kill" /proc/vmstat; echo BATTERY; dumpsys battery | grep -E "level:|temperature:"'
    echo SWAPPINESS
    root_shell 'cat /proc/sys/vm/swappiness'
    echo WATERMARK_SCALE_FACTOR
    root_shell 'cat /proc/sys/vm/watermark_scale_factor'
    echo ZRAM
    root_shell 'cat /sys/block/zram0/mm_stat'
    echo PSI
    root_shell 'cat /proc/pressure/memory'
    echo PROCESSES
    local pattern= activity
    for activity in "${apps[@]}"; do
        pattern+="${activity%%/*}$|"
    done
    "${adb_cmd[@]}" shell "ps -A -o PID,NAME | grep -E '${pattern%|}'" || true
}

echo BEFORE
snapshot
for activity in "${apps[@]}"; do
    echo "LAUNCH $activity"
    "${adb_cmd[@]}" shell "echo LAUNCH_UPTIME; cat /proc/uptime; echo PID_BEFORE; pidof ${activity%%/*}" || true
    launch=$("${adb_cmd[@]}" shell am start -W -n "$activity")
    printf '%s\n' "$launch"
    if [[ $launch != *"Status: ok"* || $launch == *"Error:"* ]]; then
        echo "App launch failed: $activity" >&2
        exit 1
    fi
    "${adb_cmd[@]}" shell "echo PID_AFTER; pidof ${activity%%/*}" || true
    sleep 4
done
"${adb_cmd[@]}" shell input keyevent HOME
sleep 5
echo AFTER
snapshot
kill -0 "$log_pid" || { echo "Continuous lmkd capture stopped early" >&2; exit 1; }
echo "Completed all 14 launches. Continuous lmkd log: $result_dir/lmkd.txt"
