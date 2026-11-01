#!/usr/bin/env bash
# usb-overclock-kit — bench.sh
#
# Backup, restore, and benchmark raw USB drives. macOS primary, Linux
# fallback. Uses dd for raw I/O and fio if available for queue/latency.
#
# USAGE
#   bench.sh backup       <device>  <out.img>
#   bench.sh restore      <in.img>  <device>
#   bench.sh bench-ro     <device>                 # read-only, safe
#   bench.sh bench-rw     <device>  <backup.img>   # destructive; requires backup
#
# <device> on macOS is like /dev/disk4, which we auto-convert to /dev/rdisk4
#          for raw unbuffered I/O. On Linux /dev/sdX.
#
# Set BLOCK_SIZE=4m or similar to tune dd block size. Default 4m on macOS,
# 1M on Linux.

set -euo pipefail

die() { echo "error: $*" >&2; exit 1; }

usage() {
    sed -n '2,16p' "$0" | sed 's/^# \?//'
    exit 1
}

OS="$(uname -s)"
case "$OS" in
    Darwin) BLOCK_SIZE_DEFAULT="4m" ;;
    Linux)  BLOCK_SIZE_DEFAULT="1M" ;;
    *)      die "unsupported OS: $OS" ;;
esac
BLOCK_SIZE="${BLOCK_SIZE:-$BLOCK_SIZE_DEFAULT}"

# ─── helpers ──────────────────────────────────────────────────────────

raw_device() {
    # On macOS, convert /dev/diskN → /dev/rdiskN for unbuffered I/O.
    local dev="$1"
    if [[ "$OS" == "Darwin" && "$dev" =~ ^/dev/disk[0-9]+$ ]]; then
        echo "/dev/r${dev#/dev/}"
    else
        echo "$dev"
    fi
}

unmount_device() {
    local dev="$1"
    case "$OS" in
        Darwin) diskutil unmountDisk "$dev" >/dev/null 2>&1 || true ;;
        Linux)  for p in "${dev}"?*; do sudo umount "$p" 2>/dev/null || true; done ;;
    esac
}

device_size_bytes() {
    local dev="$1"
    case "$OS" in
        Darwin)
            diskutil info "$dev" | awk -F':' '/Disk Size/ {gsub(/[^0-9]/,"",$2); print $2; exit}'
            ;;
        Linux)
            sudo blockdev --getsize64 "$dev"
            ;;
    esac
}

confirm_destructive() {
    local dev="$1"
    local size="$(device_size_bytes "$dev" || echo "?")"
    echo
    echo "⚠️  Destructive operation on $dev (${size} bytes)"
    echo "    This will overwrite everything on the device."
    echo "    Have you run 'bench.sh backup $dev ...' first? [type YES to continue]"
    read -r reply
    [[ "$reply" == "YES" ]] || die "aborted (did not type YES)"
}

# ─── commands ─────────────────────────────────────────────────────────

cmd_backup() {
    local dev="$1" out="$2"
    [[ -b "$dev" || -c "$dev" ]] || die "$dev is not a block/char device"
    unmount_device "$dev"
    local raw; raw="$(raw_device "$dev")"
    echo "Dumping $raw → $out (block size $BLOCK_SIZE)"
    sudo dd if="$raw" of="$out" bs="$BLOCK_SIZE" conv=sync,noerror status=progress
    echo
    echo "SHA-256:"
    shasum -a 256 "$out" 2>/dev/null || sha256sum "$out"
    echo "Size: $(ls -lh "$out" | awk '{print $5}')"
}

cmd_restore() {
    local img="$1" dev="$2"
    [[ -f "$img" ]] || die "image $img not found"
    confirm_destructive "$dev"
    unmount_device "$dev"
    local raw; raw="$(raw_device "$dev")"
    echo "Restoring $img → $raw"
    sudo dd if="$img" of="$raw" bs="$BLOCK_SIZE" conv=sync,noerror status=progress
    sync
    echo "Done. Re-plug the drive to let the OS re-read partition table."
}

cmd_bench_ro() {
    local dev="$1"
    [[ -b "$dev" || -c "$dev" ]] || die "$dev is not a block/char device"
    unmount_device "$dev"
    local raw; raw="$(raw_device "$dev")"
    local total="${BENCH_MB:-1024}"
    local bs_small="${BENCH_RANDOM_BS:-4k}"

    echo "=== Sequential read, bs=$BLOCK_SIZE, count=$(( total / 4 )) ($total MB total) ==="
    sudo dd if="$raw" of=/dev/null bs="$BLOCK_SIZE" count=$(( total / 4 )) status=progress

    if command -v fio >/dev/null 2>&1; then
        echo
        echo "=== fio: random 4K read, QD=1 and QD=32 ==="
        sudo fio --name=rr-qd1  --filename="$raw" --rw=randread --bs=4k --iodepth=1  --runtime=20 --time_based --direct=1 --group_reporting | tail -20
        echo
        sudo fio --name=rr-qd32 --filename="$raw" --rw=randread --bs=4k --iodepth=32 --runtime=20 --time_based --direct=1 --group_reporting | tail -20
    else
        echo
        echo "(fio not installed; skipping random IOPS test. 'brew install fio' or 'apt install fio' to enable.)"
    fi
}

cmd_bench_rw() {
    local dev="$1" backup="$2"
    [[ -f "$backup" ]] || die "backup $backup not found — refuse to run destructive bench without a backup"
    confirm_destructive "$dev"
    unmount_device "$dev"
    local raw; raw="$(raw_device "$dev")"
    local total="${BENCH_MB:-1024}"

    echo "=== Sequential write, bs=$BLOCK_SIZE, count=$(( total / 4 )) ==="
    sudo dd if=/dev/zero of="$raw" bs="$BLOCK_SIZE" count=$(( total / 4 )) status=progress conv=fsync

    if command -v fio >/dev/null 2>&1; then
        echo
        echo "=== fio: random 4K write, QD=1 and QD=32 ==="
        sudo fio --name=rw-qd1  --filename="$raw" --rw=randwrite --bs=4k --iodepth=1  --runtime=20 --time_based --direct=1 --group_reporting | tail -20
        echo
        sudo fio --name=rw-qd32 --filename="$raw" --rw=randwrite --bs=4k --iodepth=32 --runtime=20 --time_based --direct=1 --group_reporting | tail -20
    fi

    echo
    echo "Done. Restore your data with: $0 restore $backup $dev"
}

# ─── dispatch ─────────────────────────────────────────────────────────

[[ $# -ge 1 ]] || usage
cmd="$1"; shift
case "$cmd" in
    backup)     [[ $# -eq 2 ]] || usage; cmd_backup   "$1" "$2" ;;
    restore)    [[ $# -eq 2 ]] || usage; cmd_restore  "$1" "$2" ;;
    bench-ro)   [[ $# -eq 1 ]] || usage; cmd_bench_ro "$1" ;;
    bench-rw)   [[ $# -eq 2 ]] || usage; cmd_bench_rw "$1" "$2" ;;
    -h|--help)  usage ;;
    *)          usage ;;
esac
