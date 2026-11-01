#!/usr/bin/env bash
# usb-overclock-kit — REVERT runbook for 13fe:5500
# Generated: this script describes HOW to revert; the actual revert
# runs in the vendor MPTool on Windows.
#
# INPUTS (set these to your actual backup paths before running):
STOCK_FW="reports/drive1-ps2309/fw-stock.bin"
STOCK_INI="reports/drive1-ps2309/cfg-stock.ini"
cat <<EOF
───────────────────────────────────────────────────────────────────────
 REVERT PROCEDURE for drive 13fe:5500  (Phison PS2309 Boot ROM)
───────────────────────────────────────────────────────────────────────

Prerequisites:
  1. Drive plugged DIRECTLY into a Windows host (no hub, no dock).
  2. Backup files from the original pull phase:
       stock firmware:  $STOCK_FW
       stock INI     :  $STOCK_INI

Steps (Phison MPALL / UPTool):

  1. Launch MPALL on Windows (same build you used to flash).
  2. If this build supports "Restore" / "Reflash":
       File → Load Firmware → point at $STOCK_FW
       File → Load Config   → point at $STOCK_INI
       Click Start.
  3. If this build does NOT support firmware restore directly:
       Launch the MPALL build that MATCHES $STOCK_FW's IC version.
       Load $STOCK_INI and Click Start — this reflashes the stock
       config but regenerates firmware fresh; identical in behaviour
       to the stock drive.
  4. Confirm the drive re-enumerates at the original capacity:
       diskutil list      (macOS, after unplug/replug)
       lsblk              (Linux)

Rollback-of-rollback:
  Keep your TUNED INI and firmware dump around after reverting — you
  may want to re-apply the tune later. See docs/07-profiles-and-reverting.md.

If the drive is bricked after revert attempt:
  See docs/03-safety.md section "Boot ROM corrupted" for recovery.
───────────────────────────────────────────────────────────────────────
EOF
