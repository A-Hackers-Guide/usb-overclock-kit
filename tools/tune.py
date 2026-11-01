#!/usr/bin/env python3
"""
usb-overclock-kit — tune.py

Generalized USB flash drive tuner. Reads a profile JSON, dispatches to a
per-controller-family renderer, emits:
  - a per-profile INI overlay for the vendor MPTool
  - a host-side setup script
  - a human-readable report of each setting applied

Does NOT flash the drive. The output files are inputs to the vendor
MPTool, which runs separately (Windows-only for Phison/SMI/Alcor).

Usage:
  tune.py --list-profiles
  tune.py --list-drives
  tune.py apply   --vid-pid 13fe:5500 --profile swap-aggressive --host linux
  tune.py apply   --from-recon        --profile balanced
  tune.py revert  --vid-pid 13fe:5500 --stock-fw reports/drive1-ps2309/fw-stock.bin

  tune.py apply   --vid-pid <V:P> --profile <name> [--host linux|macos]
                  [--out-dir <path>]   # default: reports/<vid>-<pid>-<profile>/

  tune.py revert  --vid-pid <V:P> --stock-fw <path> [--stock-ini <path>]
                  [--out-dir <path>]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
KIT_ROOT = SCRIPT_DIR.parent
PROFILES_DIR = KIT_ROOT / "data" / "profiles"


# ─── Loaders ────────────────────────────────────────────────────────────

def load_controllers() -> dict:
    return json.loads((KIT_ROOT / "data" / "controllers.json").read_text())


def load_profile(name: str) -> dict:
    p = PROFILES_DIR / f"{name}.json"
    if not p.exists():
        print(f"profile not found: {p}", file=sys.stderr)
        print(f"available: {', '.join(sorted(x.stem for x in PROFILES_DIR.glob('*.json')))}",
              file=sys.stderr)
        sys.exit(2)
    return json.loads(p.read_text())


def list_profiles() -> list[dict]:
    result = []
    for p in sorted(PROFILES_DIR.glob("*.json")):
        try:
            d = json.loads(p.read_text())
            result.append({
                "name": d.get("name", p.stem),
                "description": d.get("description", ""),
                "path": str(p.relative_to(KIT_ROOT)),
            })
        except Exception as e:
            result.append({"name": p.stem, "description": f"<broken: {e}>", "path": str(p)})
    return result


def run_recon() -> list[dict]:
    out = subprocess.check_output([str(SCRIPT_DIR / "recon.py"), "--json"])
    return json.loads(out)


# ─── Per-family INI mappers ─────────────────────────────────────────────
#
# Each mapper takes a profile.targets dict and returns a dict of INI
# {section: {key: value}} that the renderer serializes.

def map_phison(targets: dict) -> dict:
    sections: dict = {"Preformat": {}, "MP": {}}

    sections["Preformat"]["Preformat"] = "1"

    if "over_provisioning_percent" in targets:
        sections["MP"]["OverProvision"] = str(targets["over_provisioning_percent"])
    if "pslc_cache_size_percent" in targets:
        sections["MP"]["SLCCacheSize"] = str(targets["pslc_cache_size_percent"])
    if "pslc_cache_mode" in targets:
        m = targets["pslc_cache_mode"]
        sections["MP"]["SLCCacheMode"] = "Static" if "static" in m else "Dynamic"
    if "usb_mode" in targets:
        sections["MP"]["USB3Only"] = "1" if targets["usb_mode"] == "superspeed_force" else "0"
    if "usb_lpm_enabled" in targets:
        sections["MP"]["USBLPM"] = "1" if targets["usb_lpm_enabled"] else "0"
    if "nand_timing_grade" in targets:
        g = targets["nand_timing_grade"]
        sections["MP"]["TogglePerf"] = "1" if g == "rated_max" else "0"
        sections["MP"]["NANDTimingGrade"] = g
    if "gc_aggressiveness" in targets:
        gc_map = {
            "minimal_idle": "Minimal",
            "moderate": "Normal",
            "aggressive": "Aggressive",
            "idle_only": "IdleOnly",
        }
        sections["MP"]["IdleGC"] = gc_map.get(targets["gc_aggressiveness"], targets["gc_aggressiveness"])
    if "ecc_strength" in targets:
        ecc_map = {"max_rated": "Max", "rated_standard": "Standard"}
        sections["MP"]["ECC"] = ecc_map.get(targets["ecc_strength"], targets["ecc_strength"])
    if "write_buffer_mode" in targets:
        wb_map = {
            "low_latency": "LowLatency",
            "adaptive": "Adaptive",
            "coalesce_standard": "Coalesce",
            "high_throughput_coalesce": "HighThroughput",
        }
        sections["MP"]["WriteBufferMode"] = wb_map.get(targets["write_buffer_mode"], targets["write_buffer_mode"])
    if "thermal_throttle_c" in targets:
        sections["MP"]["ThermalThrottle"] = f"{targets['thermal_throttle_c']}C"

    return sections


FAMILY_MAPPERS = {
    "phison": map_phison,
    # TODO: smi, alcor, innostor, chipsbank — contributions welcome.
    # SMI and Alcor INIs are structurally similar but use different key
    # names (ChannelMode / InterleaveMode / etc.). See docs/02-controller-families.md.
}


def pick_mapper(dev: dict):
    family = (
        dev.get("family")
        or (dev.get("controller_guess") or {}).get("family", "")
        or ""
    ).lower()
    for key, fn in FAMILY_MAPPERS.items():
        if key in family:
            return key, fn
    return None, None


# ─── INI serialization ──────────────────────────────────────────────────

def serialize_ini(sections: dict, header: str) -> str:
    lines = [header]
    for section, kvs in sections.items():
        if not kvs:
            continue
        lines.append(f"\n[{section}]")
        key_width = max((len(k) for k in kvs), default=1)
        for k, v in kvs.items():
            lines.append(f"{k:<{key_width}} = {v}")
    lines.append("")
    return "\n".join(lines)


# ─── Host scripts ───────────────────────────────────────────────────────

LINUX_SWAP_SETUP = """\
#!/usr/bin/env bash
# usb-overclock-kit — Linux host setup, SWAP profile (profile={profile_name}).
# Run AFTER the drive has been flashed with the matching MPTool config.
# Usage: ./swap-host-linux-{vid}-{pid}.sh /dev/sdX
set -euo pipefail

DEV="${{1:-}}"
LABEL="usb-oc-swap-{vid}-{pid}"

[[ -b "$DEV" ]] || {{ echo "pass block device as arg 1, e.g. /dev/sdc" >&2; exit 1; }}

echo "You are about to WIPE $DEV and set it up as swap."
echo "Type the device's basename to confirm (e.g. 'sdc'):"
read -r confirm
[[ "/dev/$confirm" == "$DEV" ]] || {{ echo "aborted"; exit 1; }}

sudo sgdisk --zap-all "$DEV"
sudo sgdisk --new=1:0:0 --typecode=1:8200 --change-name=1:"$LABEL" "$DEV"
sudo partprobe "$DEV"
sudo mkswap --label "$LABEL" "${{DEV}}1"
sudo swapon --priority 100 --discard=once "${{DEV}}1"
swapon --show
free -h
"""


LINUX_GENERIC_SETUP = """\
#!/usr/bin/env bash
# usb-overclock-kit — Linux host setup, generic profile (profile={profile_name}).
# Partitions as GPT with a single exFAT partition. Edit if you want a
# different filesystem (ext4 for Linux-only, NTFS for Windows cross-use).
# Usage: ./host-linux-{vid}-{pid}.sh /dev/sdX
set -euo pipefail

DEV="${{1:-}}"
LABEL="usb-oc-{profile_name}"

[[ -b "$DEV" ]] || {{ echo "pass block device as arg 1, e.g. /dev/sdc" >&2; exit 1; }}

echo "You are about to WIPE $DEV."
echo "Type the device's basename to confirm (e.g. 'sdc'):"
read -r confirm
[[ "/dev/$confirm" == "$DEV" ]] || {{ echo "aborted"; exit 1; }}

sudo sgdisk --zap-all "$DEV"
sudo sgdisk --new=1:0:0 --typecode=1:0700 --change-name=1:"$LABEL" "$DEV"
sudo partprobe "$DEV"
sudo mkfs.exfat -n "${{LABEL::15}}" "${{DEV}}1"
lsblk "$DEV"
"""


MACOS_NOTE = """\
#!/usr/bin/env bash
# usb-overclock-kit — macOS host script (profile={profile_name}).
#
# macOS cannot redirect kernel swap to external devices. For the
# swap-aggressive profile, move the drive to Linux.
#
# For other profiles, standard diskutil erase works:
#   diskutil eraseDisk ExFAT USB-OC-{profile_name} GPT /dev/diskN
echo "macOS: use diskutil eraseDisk to format once flashed."
echo "  example: diskutil eraseDisk ExFAT USB-OC-{profile_name} GPT /dev/diskN"
"""


REVERT_RUNBOOK = """\
#!/usr/bin/env bash
# usb-overclock-kit — REVERT runbook for {vid}:{pid}
# Generated: this script describes HOW to revert; the actual revert
# runs in the vendor MPTool on Windows.
#
# INPUTS (set these to your actual backup paths before running):
STOCK_FW="{stock_fw}"
STOCK_INI="{stock_ini}"
cat <<EOF
───────────────────────────────────────────────────────────────────────
 REVERT PROCEDURE for drive {vid}:{pid}  ({family})
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
"""


# ─── Report ─────────────────────────────────────────────────────────────

REPORT_TEMPLATE = """\
═══════════════════════════════════════════════════════════════════════
 tune.py — build report
═══════════════════════════════════════════════════════════════════════

Drive              : {vid}:{pid}   ({family})
Profile            : {profile_name}
Description        : {profile_description}
Capacity impact    : {capacity_note}

Settings applied (profile → vendor-INI keys):

{settings_rendered}

Output files:
  INI overlay      : {ini_path}
  Host setup       : {host_path}

Nothing has been written to the drive. The INI is prepared.
See docs/05, docs/06, docs/07 for how to apply, why these numbers,
and how to revert.
═══════════════════════════════════════════════════════════════════════
"""


def render_settings(sections: dict) -> str:
    lines = []
    for sec, kvs in sections.items():
        if not kvs:
            continue
        lines.append(f"  [{sec}]")
        for k, v in kvs.items():
            lines.append(f"    {k:<20} = {v}")
    return "\n".join(lines) if lines else "  (no settings mapped — check profile vs. family support)"


# ─── Subcommands ────────────────────────────────────────────────────────

def resolve_device(vid_pid: str | None, from_recon: bool, controllers: dict) -> dict:
    if vid_pid:
        try:
            vid, pid = vid_pid.lower().split(":")
        except ValueError:
            print(f"--vid-pid must be VID:PID, got {vid_pid!r}", file=sys.stderr)
            sys.exit(2)
        entry = controllers.get("entries", {}).get(f"{vid}:{pid}")
        if not entry:
            print(f"VID:PID {vid}:{pid} not in data/controllers.json — add it first", file=sys.stderr)
            sys.exit(2)
        return {"vendor_id": vid, "product_id": pid, **entry}
    elif from_recon:
        devs = run_recon()
        if not devs:
            print("recon.py returned no devices; use --vid-pid instead", file=sys.stderr)
            sys.exit(2)
        if len(devs) > 1:
            first = devs[0]
            print(f"multiple drives detected; using the first "
                  f"({first.get('vendor_id')}:{first.get('product_id')}) — "
                  f"pass --vid-pid to pick explicitly", file=sys.stderr)
        dev = devs[0]
        cg = dev.get("controller_guess") or {}
        dev.setdefault("family", cg.get("family"))
        return dev
    else:
        print("provide --vid-pid or --from-recon", file=sys.stderr)
        sys.exit(2)


def cmd_apply(args) -> int:
    profile = load_profile(args.profile)
    controllers = load_controllers()
    dev = resolve_device(args.vid_pid, args.from_recon, controllers)

    _, mapper = pick_mapper(dev)
    if mapper is None:
        family = dev.get("family") or "unknown"
        print(f"no tuning template yet for family: {family}", file=sys.stderr)
        print(f"supported: {', '.join(FAMILY_MAPPERS.keys())}", file=sys.stderr)
        return 3

    sections = mapper(profile["targets"])
    cap = profile.get("capacity_impact", {})
    cap_note = (
        f"{cap.get('advertised_gb','?')} GB advertised → "
        f"~{cap.get('estimated_usable_gb','?')} GB usable"
    )
    header = (
        f"; usb-overclock-kit INI OVERLAY — profile '{profile['name']}'\n"
        f"; Drive VID:PID : {dev['vendor_id']}:{dev['product_id']}\n"
        f"; Detected family: {dev.get('family') or 'unknown'}\n"
        f"; {profile.get('description', '')}\n"
        f"; Capacity impact: {cap_note}\n"
        f";\n"
        f"; THIS IS AN OVERLAY — merge each line below into the SAME\n"
        f"; section of your real MPTool base INI. Keep every other line\n"
        f"; at the factory value. Then run the MPTool's Check / Validate\n"
        f"; before flashing. See docs/05-phison-mpall-ps2309-workflow.md."
    )
    ini_text = serialize_ini(sections, header)

    # Pick host script
    if args.host == "linux":
        host_text = (LINUX_SWAP_SETUP if profile["name"] == "swap-aggressive" else LINUX_GENERIC_SETUP)
    else:
        host_text = MACOS_NOTE
    host_text = host_text.format(
        vid=dev["vendor_id"], pid=dev["product_id"], profile_name=profile["name"]
    )

    out_dir = Path(args.out_dir or f"reports/{dev['vendor_id']}-{dev['product_id']}-{profile['name']}")
    out_dir.mkdir(parents=True, exist_ok=True)
    tag = f"{dev['vendor_id']}-{dev['product_id']}-{profile['name']}"
    ini_path = out_dir / f"ini-{tag}.ini"
    host_path = out_dir / f"host-{args.host}-{tag}.sh"
    ini_path.write_text(ini_text)
    host_path.write_text(host_text)
    host_path.chmod(0o755)

    print(REPORT_TEMPLATE.format(
        vid=dev["vendor_id"],
        pid=dev["product_id"],
        family=dev.get("family") or "unknown",
        profile_name=profile["name"],
        profile_description=profile.get("description", ""),
        capacity_note=cap_note,
        settings_rendered=render_settings(sections),
        ini_path=ini_path,
        host_path=host_path,
    ))
    return 0


def cmd_revert(args) -> int:
    controllers = load_controllers()
    dev = resolve_device(args.vid_pid, False, controllers)

    out_dir = Path(args.out_dir or f"reports/{dev['vendor_id']}-{dev['product_id']}-revert")
    out_dir.mkdir(parents=True, exist_ok=True)
    tag = f"{dev['vendor_id']}-{dev['product_id']}"
    path = out_dir / f"revert-{tag}.sh"
    text = REVERT_RUNBOOK.format(
        vid=dev["vendor_id"],
        pid=dev["product_id"],
        family=dev.get("family") or "unknown",
        stock_fw=args.stock_fw,
        stock_ini=args.stock_ini or "<not provided — specify with --stock-ini>",
    )
    path.write_text(text)
    path.chmod(0o755)
    print(f"Revert runbook written to {path}")
    print(f"Run it (./{path.name}) to print the full step-by-step procedure.")
    return 0


def cmd_list_profiles(_args) -> int:
    for p in list_profiles():
        print(f"{p['name']:20s}  {p['description'][:100]}")
    return 0


def cmd_list_drives(_args) -> int:
    for d in run_recon():
        mode = d.get("mode", "?")
        vid = d.get("vendor_id")
        pid = d.get("product_id")
        name = d.get("name") or "?"
        family = (d.get("controller_guess") or {}).get("family") or "?"
        print(f"{vid}:{pid}  {mode:30s}  {name:25s}  {family}")
    return 0


# ─── Main ───────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(prog="tune.py", description="USB flash drive tuner (does NOT flash).")
    sub = ap.add_subparsers(dest="cmd", required=False)

    pa = sub.add_parser("apply", help="generate INI overlay + host script for a profile")
    g = pa.add_mutually_exclusive_group(required=True)
    g.add_argument("--vid-pid", help="VID:PID like 13fe:5500")
    g.add_argument("--from-recon", action="store_true", help="read tools/recon.py --json")
    pa.add_argument("--profile", default="balanced", help="profile under data/profiles/")
    pa.add_argument("--host", choices=["linux", "macos"], default="linux")
    pa.add_argument("--out-dir", default=None, help="output dir (default: reports/<vid>-<pid>-<profile>/)")
    pa.set_defaults(func=cmd_apply)

    pr = sub.add_parser("revert", help="generate a revert runbook pointing at your stock backup files")
    pr.add_argument("--vid-pid", required=True)
    pr.add_argument("--stock-fw", required=True, help="path to firmware dump from pull phase")
    pr.add_argument("--stock-ini", help="path to stock INI dump (optional)")
    pr.add_argument("--out-dir", default=None)
    pr.set_defaults(func=cmd_revert)

    sub.add_parser("list-profiles", help="list available profiles").set_defaults(func=cmd_list_profiles)
    sub.add_parser("list-drives", help="list detected drives via recon.py").set_defaults(func=cmd_list_drives)

    args = ap.parse_args()
    if not args.cmd:
        ap.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
