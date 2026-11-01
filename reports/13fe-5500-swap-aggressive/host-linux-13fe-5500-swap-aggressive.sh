#!/usr/bin/env bash
# usb-overclock-kit — Linux host setup, SWAP profile (profile=swap-aggressive).
# Run AFTER the drive has been flashed with the matching MPTool config.
# Usage: ./swap-host-linux-13fe-5500.sh /dev/sdX
set -euo pipefail

DEV="${1:-}"
LABEL="usb-oc-swap-13fe-5500"

[[ -b "$DEV" ]] || { echo "pass block device as arg 1, e.g. /dev/sdc" >&2; exit 1; }

echo "You are about to WIPE $DEV and set it up as swap."
echo "Type the device's basename to confirm (e.g. 'sdc'):"
read -r confirm
[[ "/dev/$confirm" == "$DEV" ]] || { echo "aborted"; exit 1; }

sudo sgdisk --zap-all "$DEV"
sudo sgdisk --new=1:0:0 --typecode=1:8200 --change-name=1:"$LABEL" "$DEV"
sudo partprobe "$DEV"
sudo mkswap --label "$LABEL" "${DEV}1"
sudo swapon --priority 100 --discard=once "${DEV}1"
swapon --show
free -h
