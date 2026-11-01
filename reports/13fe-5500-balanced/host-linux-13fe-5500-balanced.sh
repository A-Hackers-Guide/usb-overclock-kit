#!/usr/bin/env bash
# usb-overclock-kit — Linux host setup, generic profile (profile=balanced).
# Partitions as GPT with a single exFAT partition. Edit if you want a
# different filesystem (ext4 for Linux-only, NTFS for Windows cross-use).
# Usage: ./host-linux-13fe-5500.sh /dev/sdX
set -euo pipefail

DEV="${1:-}"
LABEL="usb-oc-balanced"

[[ -b "$DEV" ]] || { echo "pass block device as arg 1, e.g. /dev/sdc" >&2; exit 1; }

echo "You are about to WIPE $DEV."
echo "Type the device's basename to confirm (e.g. 'sdc'):"
read -r confirm
[[ "/dev/$confirm" == "$DEV" ]] || { echo "aborted"; exit 1; }

sudo sgdisk --zap-all "$DEV"
sudo sgdisk --new=1:0:0 --typecode=1:0700 --change-name=1:"$LABEL" "$DEV"
sudo partprobe "$DEV"
sudo mkfs.exfat -n "${LABEL::15}" "${DEV}1"
lsblk "$DEV"
