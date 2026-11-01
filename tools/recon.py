#!/usr/bin/env python3
"""
usb-overclock-kit — recon.py

Enumerate USB mass-storage devices on macOS (primary) and Linux (fallback),
report what the host sees, and cross-reference against the controller
VID:PID database.

Usage:
    ./recon.py              # pretty-print to stdout
    ./recon.py --json       # JSON output
    ./recon.py --report     # JSON report suitable for reports/*.json

No third-party dependencies. Pure stdlib.
"""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
CONTROLLER_DB_PATH = SCRIPT_DIR.parent / "data" / "controllers.json"


# ─── Platform-specific enumeration ──────────────────────────────────────

def enumerate_macos(db: dict | None = None) -> list[dict]:
    """Walk `system_profiler SPUSBDataType -json` for storage devices AND
    for controllers appearing in boot/non-storage mode (where the VID
    matches a known flash-controller vendor but no mass-storage media is
    exposed). Boot-mode detection requires the controller DB."""
    out = subprocess.check_output(
        ["system_profiler", "SPUSBDataType", "-json"],
        stderr=subprocess.DEVNULL,
    )
    data = json.loads(out)
    db = db or {}
    known_vids = set((db.get("vendors") or {}).keys())
    known_pairs = set((db.get("entries") or {}).keys())
    devices: list[dict] = []

    def walk(nodes):
        for node in nodes or []:
            vid = _normalize_id(node.get("vendor_id"))
            pid = _normalize_id(node.get("product_id"))
            has_media = "Media" in node
            if has_media:
                for m in node.get("Media", []):
                    devices.append({
                        "mode": "mass_storage",
                        "name": node.get("_name"),
                        "manufacturer": node.get("manufacturer"),
                        "product_id": pid,
                        "vendor_id": vid,
                        "serial_num": node.get("serial_num"),
                        "speed": node.get("device_speed"),
                        "bcd_device": node.get("bcd_device"),
                        "media_name": m.get("_name"),
                        "size_bytes": m.get("size_in_bytes"),
                        "bsd_name": m.get("bsd_name"),
                        "removable": m.get("removable_media"),
                        "partitions": [
                            {
                                "bsd_name": v.get("bsd_name"),
                                "mount_point": v.get("mount_point"),
                                "file_system": v.get("file_system"),
                                "size_bytes": v.get("size_in_bytes"),
                            }
                            for v in m.get("volumes", [])
                        ],
                    })
            elif vid and pid and f"{vid}:{pid}" in known_pairs:
                # Known controller VID:PID present but no mass-storage
                # media → boot ROM / mass-production mode / HID masquerade.
                # This is the state vendor MPTools talk to directly.
                # (VID-only matches live in the identify_controller hint,
                # not in device discovery, to avoid false positives on
                # multi-purpose vendor VIDs like Realtek's.)
                devices.append({
                    "mode": "controller_boot_or_non_storage",
                    "name": node.get("_name"),
                    "manufacturer": node.get("manufacturer"),
                    "product_id": pid,
                    "vendor_id": vid,
                    "serial_num": node.get("serial_num"),
                    "speed": node.get("device_speed"),
                    "bcd_device": node.get("bcd_device"),
                    "size_bytes": None,
                    "bsd_name": None,
                    "removable": None,
                    "partitions": [],
                })
            walk(node.get("_items"))

    walk(data.get("SPUSBDataType", []))

    # ioreg fallback: catches boot-mode controllers AND mass-storage
    # drives that system_profiler missed. On recent macOS builds the
    # whole SPUSBDataType query sometimes returns empty — ioreg is the
    # authoritative source. Dedupe by (vid, pid, serial) because a VID:PID
    # pair can describe multiple drives (same OEM hardware, different serials).
    seen = {(d.get("vendor_id"), d.get("product_id"), d.get("serial_num")) for d in devices}
    for d in _enumerate_macos_ioreg_controllers(known_vids, known_pairs):
        key = (d.get("vendor_id"), d.get("product_id"), d.get("serial_num"))
        if key not in seen:
            devices.append(d)
            seen.add(key)

    return devices


def _enumerate_macos_ioreg_controllers(known_vids: set, known_pairs: set) -> list[dict]:
    """Walk `ioreg -r -c IOUSBHostDevice -l -a` and emit:
      - mass_storage: USB devices that have an IOMedia descendant
      - controller_boot_or_non_storage: known controllers in boot/MP mode
    Hubs and non-storage devices (keyboards, cameras, etc.) are skipped.
    Each physical USB device is reported once; interface-duplicate nodes
    with the same vid:pid are collapsed. Media found through downstream
    hub ports are attributed to the downstream device, not the hub."""
    import plistlib
    try:
        raw = subprocess.check_output(
            ["ioreg", "-r", "-c", "IOUSBHostDevice", "-l", "-a"],
            stderr=subprocess.DEVNULL,
        )
        tree = plistlib.loads(raw)
    except Exception:
        return []
    devices: list[dict] = []

    def hexid(x):
        try:
            return f"{int(x):04x}"
        except (ValueError, TypeError):
            return None

    def find_media(node, out, pvp):
        """IOMedia descendants belonging to this USB device.
        Stop at any child whose vid:pid differs from pvp — that's a
        downstream USB device, its media belongs to it."""
        cvid = node.get("idVendor")
        cpid = node.get("idProduct")
        if cvid is not None and cpid is not None and (cvid, cpid) != pvp:
            return
        if node.get("BSD Name") and node.get("Whole"):
            out.append(node)
        for c in node.get("IORegistryEntryChildren") or []:
            find_media(c, out, pvp)

    def collect_partitions(media_node):
        parts: list[dict] = []
        def rec(n):
            for c in n.get("IORegistryEntryChildren") or []:
                if c.get("BSD Name") and not c.get("Whole"):
                    parts.append({
                        "bsd_name": "/dev/" + c["BSD Name"],
                        "size_bytes": c.get("Size"),
                        "mount_point": None,
                        "file_system": c.get("Content"),
                    })
                rec(c)
        rec(media_node)
        return parts

    def walk(nodes, parent_vp=None):
        for n in nodes or []:
            vid_int = n.get("idVendor")
            pid_int = n.get("idProduct")
            is_new_device = (
                vid_int is not None
                and pid_int is not None
                and (vid_int, pid_int) != parent_vp
            )
            if is_new_device:
                vid = hexid(vid_int)
                pid = hexid(pid_int)
                media: list[dict] = []
                find_media(n, media, (vid_int, pid_int))
                if media:
                    for m in media:
                        bsd = m.get("BSD Name") or ""
                        devices.append({
                            "mode": "mass_storage",
                            "name": n.get("USB Product Name") or bsd,
                            "manufacturer": n.get("USB Vendor Name"),
                            "product_id": pid,
                            "vendor_id": vid,
                            "serial_num": n.get("USB Serial Number"),
                            "speed": n.get("Device Speed"),
                            "bcd_device": n.get("bcdDevice"),
                            "size_bytes": m.get("Size"),
                            "bsd_name": "/dev/" + bsd if bsd else None,
                            "removable": m.get("Removable"),
                            "partitions": collect_partitions(m),
                        })
                elif f"{vid}:{pid}" in known_pairs:
                    devices.append({
                        "mode": "controller_boot_or_non_storage",
                        "name": n.get("USB Product Name") or "unknown",
                        "manufacturer": n.get("USB Vendor Name"),
                        "product_id": pid,
                        "vendor_id": vid,
                        "serial_num": n.get("USB Serial Number"),
                        "speed": n.get("Device Speed"),
                        "bcd_device": n.get("bcdDevice"),
                        "size_bytes": None,
                        "bsd_name": None,
                        "removable": None,
                        "partitions": [],
                    })
                walk(n.get("IORegistryEntryChildren") or [], parent_vp=(vid_int, pid_int))
            else:
                walk(n.get("IORegistryEntryChildren") or [], parent_vp=parent_vp)

    walk(tree if isinstance(tree, list) else [tree])
    return devices


def enumerate_linux() -> list[dict]:
    """Use lsusb + lsblk; keep it minimal."""
    devices: list[dict] = []
    try:
        lsblk = json.loads(subprocess.check_output(
            ["lsblk", "-J", "-O"], stderr=subprocess.DEVNULL
        ))
    except (subprocess.CalledProcessError, FileNotFoundError):
        return devices
    for d in lsblk.get("blockdevices", []):
        if d.get("tran") != "usb":
            continue
        devices.append({
            "name": d.get("model"),
            "manufacturer": d.get("vendor"),
            "vendor_id": None,  # lsblk doesn't expose; cross-reference with lsusb if desired
            "product_id": None,
            "serial_num": d.get("serial"),
            "speed": None,
            "size_bytes": d.get("size"),
            "bsd_name": f"/dev/{d.get('name')}",
            "removable": d.get("rm"),
            "partitions": [
                {
                    "bsd_name": f"/dev/{c.get('name')}",
                    "mount_point": c.get("mountpoint"),
                    "file_system": c.get("fstype"),
                    "size_bytes": c.get("size"),
                }
                for c in (d.get("children") or [])
            ],
        })
    return devices


# ─── Controller DB lookup ───────────────────────────────────────────────

def load_controller_db() -> dict:
    if not CONTROLLER_DB_PATH.exists():
        return {}
    return json.loads(CONTROLLER_DB_PATH.read_text())


def _normalize_id(x: str | None) -> str | None:
    if not x:
        return None
    s = str(x).lower().replace("0x", "").strip()
    # system_profiler returns "0x058f" style; normalize to "058f"
    return s.zfill(4)


def identify_controller(dev: dict, db: dict) -> dict:
    vid = _normalize_id(dev.get("vendor_id"))
    pid = _normalize_id(dev.get("product_id"))
    if not vid or not pid:
        return {"identified": False, "reason": "no VID:PID"}
    key = f"{vid}:{pid}"
    hit = db.get("entries", {}).get(key)
    if hit:
        return {"identified": True, "vid_pid": key, **hit}
    # Fall back to VID-only
    vid_entries = [
        {"vid_pid": k, **v}
        for k, v in db.get("entries", {}).items()
        if k.startswith(f"{vid}:")
    ]
    return {
        "identified": False,
        "vid_pid": key,
        "vendor_only_hint": db.get("vendors", {}).get(vid),
        "other_known_pids_for_vendor": vid_entries,
    }


# ─── Pretty printing ────────────────────────────────────────────────────

def pretty_print(devices: list[dict], db: dict) -> None:
    if not devices:
        print("No USB mass-storage devices detected.")
        print("Make sure your drive is plugged in and shows in `diskutil list`.")
        return
    for i, dev in enumerate(devices):
        mode = dev.get("mode", "mass_storage")
        if mode == "controller_boot_or_non_storage":
            print(f"\n═══ Device {i+1}  ⚠ CONTROLLER IN BOOT / NON-STORAGE MODE ═══")
            print(f"  (device on USB bus but exposes no mass-storage LUN —")
            print(f"   this is the state vendor MPTools R/W firmware against)")
        else:
            print(f"\n═══ Device {i+1} ═══")
        print(f"  Label       : {dev.get('name')}")
        print(f"  Mfr sticker : {dev.get('manufacturer')}")
        print(f"  VID:PID     : {_normalize_id(dev.get('vendor_id'))}:{_normalize_id(dev.get('product_id'))}")
        print(f"  Serial      : {dev.get('serial_num')}")
        print(f"  USB speed   : {dev.get('speed')}  ← force SS if this is HighSpeed on a '3.0' drive")
        print(f"  Device rev  : {dev.get('bcd_device')}")
        print(f"  BSD name    : {dev.get('bsd_name')}")
        size = dev.get("size_bytes")
        if isinstance(size, int):
            print(f"  Capacity    : {size:,} bytes  ({size/1e9:.1f} GB advertised)")
        print(f"  Removable   : {dev.get('removable')}")
        for p in dev.get("partitions", []):
            print(f"    └─ part: {p.get('bsd_name')}  {p.get('file_system')}  mounted at {p.get('mount_point')}")
        ctl = identify_controller(dev, db)
        print(f"\n  Controller guess:")
        if ctl.get("identified"):
            print(f"    ✓ {ctl.get('family')}  ({ctl.get('vid_pid')})")
            print(f"      Tool  : {ctl.get('tool')}")
            print(f"      Notes : {ctl.get('notes')}")
        else:
            print(f"    ✗ no exact match for {ctl.get('vid_pid')}")
            if ctl.get("vendor_only_hint"):
                print(f"      Vendor-level hint: {ctl.get('vendor_only_hint')}")
            if ctl.get("other_known_pids_for_vendor"):
                print(f"      Other PIDs under this VID in DB:")
                for e in ctl["other_known_pids_for_vendor"]:
                    print(f"        {e['vid_pid']} → {e.get('family')}")


# ─── Main ───────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="USB mass-storage recon.")
    ap.add_argument("--json", action="store_true", help="JSON output")
    ap.add_argument("--report", action="store_true", help="single-device report JSON")
    args = ap.parse_args()

    db = load_controller_db()
    sysname = platform.system()
    if sysname == "Darwin":
        devices = enumerate_macos(db)
    elif sysname == "Linux":
        devices = enumerate_linux()
    else:
        print(f"Unsupported platform: {sysname}", file=sys.stderr)
        return 2

    if args.json or args.report:
        enriched = [{**d, "controller_guess": identify_controller(d, db)} for d in devices]
        if args.report and len(enriched) == 1:
            print(json.dumps(enriched[0], indent=2))
        else:
            print(json.dumps(enriched, indent=2))
        return 0

    pretty_print(devices, db)
    return 0


if __name__ == "__main__":
    sys.exit(main())
