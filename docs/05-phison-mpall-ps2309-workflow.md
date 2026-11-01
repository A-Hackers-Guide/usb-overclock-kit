# 05 — Phison PS2309: pull + make workflow

> **Scope:** this chapter covers the **pull** (read current state) and
> **make** (prepare tuned INI) phases. The actual **flash** step is
> deferred by project convention — the drive is prepared, not written.

Target: the drive at VID:PID `13FE:5500` detected in Boot ROM mode by
`tools/recon.py`.

## Prerequisites

1. **Windows machine or Windows VM with USB passthrough.** Phison MPALL
   runs only on Windows. UTM / Parallels / VMware with USB passthrough
   all work; VirtualBox USB passthrough on Apple Silicon is unreliable.
2. **The drive plugged DIRECTLY** into the host — no hubs, no docks. The
   PS2309 Boot ROM state is fragile; hub glitches during the pull step
   can bump the controller out of the mode we want.
3. **MPALL build matching your IC version.** You don't know the version
   until `GetInfo` runs. Download a general pack from flashboot.ru first
   (search "Phison PS2309 MP" or "PhisonMPALL"; typical archive name:
   `MPALL_F1_7F00_DL07_v504_00.rar`), then if GetInfo reports a version
   that disagrees, grab a specific matching build.
4. **Antistatic workspace** — you'll be reseating a few times.

## Phase A: Pull

### A1. Launch MPALL

Extract the archive to a short Windows path like `C:\mpall\` (deep
nested paths break some MPALL builds). Run the executable
(`MPALL_F1_7F00_DL07_v504_00.exe` or similar).

Windows will complain about an unsigned binary. Click "More info" →
"Run anyway". This is normal for flashboot.ru redistributions.

### A2. GetInfo (read current controller state)

With the drive plugged in direct, MPALL's main window shows a row of
16 slots labeled "Port 1" through "Port 16". Your drive appears in
Port 1 as `[13FE:5500]` — the exact VID:PID `recon.py` reported.

Click **GetInfo** (sometimes labeled **Scan** or **扫描**). MPALL
queries the Boot ROM and populates each occupied slot with:

```
Port 1
  IC Version   : PS2309-AB         (example — yours may differ)
  FW Version   : 09.08.03          (example)
  Flash ID     : 0x98 0xDE 0x98 0x92 0x76 0x72    (6-byte NAND ID)
  Flash Vendor : Toshiba / KIOXIA  (decoded from Flash ID[0])
  Flash Gen    : 3D TLC BiCS4      (decoded from Flash ID[1..5])
  Capacity     : 64 GB advertised / 68.7 GB raw
  Loader       : <blank or ID string, depending on state>
```

**Save this output.** Screenshot the window, or copy-paste into
`reports/drive1-ps2309/getinfo.txt`. The IC Version suffix letter
(AB / AC / etc.) matters when picking the exact firmware pack later —
a PS2309-AB firmware will refuse to flash onto a PS2309-AC and vice
versa.

### A3. Dump firmware (recommended)

Right-click the port row → **Dump** → **Dump Firmware** (menu text
varies by MPALL build; alternate labels: **ReadFW**, **固件备份**).

MPALL reads the firmware region of NAND back to a `.bin` file in the
MPALL directory. Save it as `reports/drive1-ps2309/fw-stock.bin`.

If the drive has a blank or erased firmware region (plausible for a
drive currently in Boot ROM mode), the dump will be mostly 0xFF. That
is useful information — it confirms the drive is in a factory /
unfinalized state rather than a corrupted-firmware state.

### A4. Dump settings (if available)

Some MPALL builds expose **Dump Settings** or **Dump CFG** — this
saves the stock INI config. More useful than the firmware dump; gives
you a factory baseline to diff against.

Save as `reports/drive1-ps2309/cfg-stock.ini`.

### A5. Record the state in reports/

By the end of phase A you should have:

```
reports/drive1-ps2309/
├── getinfo.txt            # text/screenshot of MPALL GetInfo output
├── fw-stock.bin           # dumped firmware (may be mostly 0xFF)
├── cfg-stock.ini          # dumped INI (if MPALL supports it)
└── recon-output.json      # tools/recon.py --json output from before
```

## Phase B: Make

### B1. Locate the base INI

The MPALL archive contains an `.INI` file next to the `.exe`. Name
varies: `MPALL.INI`, `cfg.ini`, `F1_7F00_V503.INI`. Open it in a text
editor (plain ASCII, Windows CRLF line endings).

### B2. Generate the swap-tuned overlay

From this project:

```bash
./tools/swap_optimizer.py \
    --vid-pid 13fe:5500 \
    --profile swap-aggressive \
    --host linux \
    --out-dir reports/drive1-ps2309
```

This writes two files:
- `reports/drive1-ps2309/swap-ini-13fe-5500.ini` — the overlay for MPALL
- `reports/drive1-ps2309/swap-host-linux-13fe-5500.sh` — Linux swapon setup

### B3. Merge the overlay into the base INI

The overlay is **not a complete INI** — it only contains the lines you
need to change. Open both files side by side. For each line in the
overlay:
- Find the matching section in the base INI (`[MP]`, `[Preformat]`, …)
- Replace the factory value with the overlay value
- Keep every other line in the base INI unchanged

Save the merged file as `reports/drive1-ps2309/mpall-ps2309-swap.ini`.

If your base INI doesn't have a line for a given overlay setting, add
it in the right section. If a line in the overlay doesn't apply to
your IC version, your MPALL will flag it in the Check step (B4) and
you can drop it.

### B4. Verify with Check (dry-run — no write)

Load the merged INI into MPALL (**File → Load Config** or point MPALL
at the merged file via its launch INI arg, depending on build). Then
click **Check** (sometimes **Validate**).

Expected output:
```
Port 1 Check OK
```

If instead you see:
- `FW Mismatch` → wrong MPALL build. Go back to A2, record the IC
  Version suffix letter exactly, pick a matching pack.
- `Not Support` → the overlay references a key your MPALL build
  doesn't know. Comment out the offending line and re-check.
- `Flash Vendor Mismatch` → the NAND ID doesn't match what this INI
  expects. Look for a MPALL build keyed to your NAND vendor.

### B5. Diff against stock

```bash
diff reports/drive1-ps2309/cfg-stock.ini \
     reports/drive1-ps2309/mpall-ps2309-swap.ini
```

The diff should be concentrated in `[MP]` and `[Preformat]`. If you
see diffs in sections you didn't intend to change (`[Serial]`,
`[VPD]`, `[Chip]`), stop and compare — don't flash a config with
unintended diffs.

### B6. Stop here (per project convention)

At the end of phase B you have:
- A verified-OK tuned INI (`mpall-ps2309-swap.ini`)
- A dumped stock firmware (`fw-stock.bin`)
- A dumped stock INI (`cfg-stock.ini`) for rollback
- A Linux host script ready to turn the drive into a swap partition
  once it's flashed

**Nothing has been written to the drive.** The drive is still in Boot
ROM mode, as `recon.py` originally found it.

## Phase C: Flash — DEFERRED

Not covered this turn by project convention. When you are ready to
flash later:

1. Backups off the Windows host (cloud / another computer / external
   disk) for `fw-stock.bin` and both INIs.
2. Drive plugged DIRECTLY into the host (no hub, no dock).
3. Host plugged into wall power — never run the flash on battery.
4. Click **Start** in MPALL.
5. Wait for the drive to disappear and reappear (30-120 seconds).
6. Confirm the drive now appears as mass storage at the configured
   capacity (~34 GB on a 64 GB drive after this profile).
7. Move to Linux. Run `swap-host-linux-13fe-5500.sh /dev/sdX`.
8. Benchmark with `tools/bench.sh bench-rw` once a backup partition is
   created.

## Troubleshooting

### "Can't find device"
- Hub? Direct connect it.
- USB 2.0 vs 3.0 port? Boot ROM mode is HS; either works, but USB 3
  port is more reliable for the POST-flash enumeration.
- Drive dropped out of Boot ROM? Replug. Verify with
  `./tools/recon.py` on macOS — should still report Boot ROM.

### MPALL hangs on Scan / GetInfo
- Try a different USB port on the Windows host.
- Try a different cable (if drive is on a cable at all).
- Reboot the Windows host — some MPALL builds leak USB handles.

### Preformat failed
- NAND is reporting too many bad blocks. Try a lower OP in the
  overlay (20 or 25% instead of 30) and re-generate. If still
  failing, the drive may have end-of-life NAND.

### Drive invisible after a flash attempt (hard brick)
- See [`03-safety.md`](03-safety.md) → "Boot ROM corrupted".
- First try: unplug, wait 30 s, replug into a different USB controller
  on the host. Boot ROM mode may re-arm after a cold cycle.
