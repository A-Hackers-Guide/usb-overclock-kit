# 03 — Safety: back up first, understand the brick risk

This chapter is boring and non-negotiable. Read it before you touch an
MPTool.

---

## The three failure modes

### 1. "Full erase during reflash" — expected, planned for

Every MPTool firmware-flash operation **erases all user data** on the
drive. This is not a bug or a worst case; this is the normal path. The
controller rewrites the FTL translation table and partition structures
from scratch.

**Mitigation:** raw-image backup *before* flashing. See `tools/bench.sh
backup`.

### 2. "Mismatched firmware for NAND / IC version" — recoverable brick

Flash the wrong firmware blob and the controller ends up with a working
boot ROM but no usable FTL. Device enumerates in mass-production mode
only (often VID `058F:6387` for Alcor, `090C:1000` for SMI, no device for
Phison without TP pin shorting).

**Symptom:** drive doesn't show in Finder / File Explorer / `lsblk`, but
MPTool "sees" it.

**Mitigation:** re-run the correct firmware. Usually 100% recoverable
once you've found the right version.

### 3. "Boot ROM corrupted" — hard brick

Rare. Happens if the flash operation is interrupted mid-write
(unplugging the drive during flashing, power cut) *and* the controller's
boot sector is in rewritable flash rather than mask ROM.

**Symptom:** drive is invisible to the host entirely. No MPTool sees it.
Not even in boot mode.

**Recovery:** usually requires removing the NAND from the PCB and
reprogramming it on a dedicated NAND reader (RT-809H etc.). Possible but
expensive. **For a $6 USB stick, don't bother.**

**Mitigation:** don't unplug during a flash. Use a desktop (not laptop
battery mid-sag). Avoid USB hubs for the actual flash step.

---

## The backup discipline

Before any firmware-level operation:

```bash
# Find the device
diskutil list                       # macOS
lsblk                               # Linux

# Unmount all its partitions
diskutil unmountDisk /dev/diskN     # macOS
sudo umount /dev/sdX*               # Linux

# Dump raw
sudo dd if=/dev/rdiskN of=~/usb-backup.img bs=4m status=progress
# macOS: use /dev/rdiskN not /dev/diskN for raw unbuffered

# Verify
sha256sum ~/usb-backup.img
ls -lh ~/usb-backup.img
```

To restore:

```bash
sudo dd if=~/usb-backup.img of=/dev/rdiskN bs=4m status=progress
```

The raw image contains:
- Partition table
- All partitions and their contents
- Any slack between partitions

What it does **NOT** contain:
- Controller firmware
- The controller's FTL metadata (that lives in NAND regions the host
  can't address)
- Vendor-specific "service area" sectors

In other words: `dd` backup gets your files back but doesn't let you
rebuild a bricked controller.

---

## The "two drives" rule

**Never experiment on your only copy of your data.** The project's drives
should be:

- Empty, or
- Containing only data you also have elsewhere.

Treat these drives as destroyable until proven otherwise. One of the
three test drives will probably get bricked permanently during this
project. That is normal.

---

## Known-dangerous operations

| Operation | Risk | When OK |
|---|---|---|
| MPTool flash with correct firmware | Erases user data (recoverable from backup) | Always, with backup |
| MPTool flash with wrong firmware | Recoverable brick | Last-resort only |
| Setting NAND timing to unsupported grade | Drive hangs on first read | After researching your NAND |
| Shorting TP pins on wrong pads | Short-circuit, PCB damage | Only if pads are confirmed |
| USB mode forcing on marginal cable/hub | Drive won't enumerate | Only with known-good USB 3 port |
| Benchmarking with `--bench-rw` without backup | Overwrites user data | Never. Backup first. |

---

## Static discipline

The PCB will survive casual handling, but a dry-air day + a woolly rug +
your hand near the controller pins can zap it. If you work on wall-to-wall
carpet in winter: touch something grounded first every time you pick up
the PCB. An anti-static wristband is $8 and worth it.

---

Next: [`04-what-overclocking-means.md`](04-what-overclocking-means.md).
