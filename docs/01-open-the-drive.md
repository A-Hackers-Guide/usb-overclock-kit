# 01 — Opening the drive and identifying the chips

The VID:PID the host sees belongs to the **USB bridge mode** of the
controller. A single controller family can expose many different VID:PIDs
depending on how the drive was flashed at the factory, and multiple
controller families can share VID:PIDs with each other via rebranding. The
only reliable way to know what's inside is to **open the case and read the
chip markings**.

This is destructive to the case. The PCB and the NAND survive fine.

---

## 1. Open the case

USB flash drive cases come in three common constructions:

| Construction | How to open | Reusable? |
|---|---|---|
| **Snap-fit plastic** (most retail drives) | Pry along the seam with a thin plastic spudger or a guitar pick. Start from the USB-connector end. | Usually yes, if careful. |
| **Ultrasonically welded plastic** (many promotional / "swag" drives) | No seam. Score around the midline with a hobby knife, snap. | No — case is dead. |
| **Potted / epoxy-filled** (rugged, "indestructible" drives) | Dremel or heat gun to soften epoxy. Expect PCB damage risk. | No. |

**Caution:** some drives have the NAND flash **underneath** the USB
connector shell, not under the plastic case. Don't pry near the connector
without checking seams.

**Preserve orientation:** once open, photograph the PCB before you handle
it. Note which side faces up when inserted into a port — ground pin
locations are much easier to find if you keep orientation.

---

## 2. Identify the chips

A commodity USB flash PCB has **two to four chips**:

```
┌────────────────────────────────────┐
│                                    │
│   [NAND flash]      [NAND flash]   │  ← big rectangular chips, TSOP48 or BGA
│                                    │
│          [CONTROLLER SoC]          │  ← medium square chip
│                                    │
│   [25xx EEPROM?]      [XTAL]       │  ← optional: config EEPROM, oscillator
│                                    │
│         [USB connector]            │
└────────────────────────────────────┘
```

### 2a. The controller

**Appearance:** square or near-square. Usually 6×6 mm to 8×8 mm. QFN or TSOP
package. Laser-etched text.

**What you're looking for in the marking:**

| Vendor | Marking prefix | Example |
|---|---|---|
| Phison | `PS` | `PS2251-09-V`, `PS2251-13`, `PS2251-50` |
| Silicon Motion (SMI) | `SM` | `SM3252AB`, `SM3267AB`, `SM3271G`, `SM3281` |
| Alcor Micro | `AU` | `AU6981`, `AU6989SN-GT`, `AU6998SN` |
| Innostor (Phison subsidiary) | `IS` | `IS916`, `IS917` |
| Chipsbank | `CBM` | `CBM2199A`, `CBM2199E` |
| Realtek | `RTS` | `RTS5301`, `RTS5321` |
| USBest / Afa Technologies | `UT` | `UT165`, `UT190` |

The marking may be partially worn or have a date/lot code suffix. The
family prefix is what matters. **Photograph it.** A 10× magnifier or your
phone's camera on macro helps.

If the marking has been sanded off (counterfeit drive), you can usually
still ID the controller by VID:PID + physical observations (chip size,
pin count, EEPROM presence). See `docs/02-controller-families.md`.

### 2b. The NAND

**Appearance:** large rectangle, often TSOP48 (48-pin, visible pins on two
long edges) or BGA (no visible pins, soldered to pads underneath).

**Marking format (common vendors):**

| Vendor | Marking prefix | Example |
|---|---|---|
| Toshiba / KIOXIA | `TC58`, `TH58` | `TC58NVG6D2HTA00` |
| Micron / IMFT | `MT29F`, `NW` | `MT29F256G08CECAB` |
| SK hynix | `H27U`, `H2JTDG` | `H27UCG8T2ETR` |
| Samsung | `K9GB`, `K9CF` | `K9GBG08U0A` |
| SanDisk / WD | `SDTN`, `05124` | `SDTNRGAMA-008G` (SanDisk raw) |
| Intel (legacy) | `29F` | — |

Decoding the full part number (density, process, dies-per-package) is a
rabbit hole. The vendor + rough generation (3D TLC vs 3D QLC vs planar
MLC) is what matters for tuning decisions.

### 2c. Optional: config EEPROM

Some controllers (older SMI, Alcor) store firmware parameters in a
separate serial EEPROM (`24C02`, `24C64`, etc.). This matters because:

- The parameter EEPROM can sometimes be read/written with a cheap
  CH341-based programmer — no MPTool needed.
- A bricked drive can occasionally be revived by clearing the EEPROM.

If you see a tiny 8-pin SOIC chip near the controller labeled `24xx`,
that's it.

---

## 3. Record the findings

For each drive, create `reports/<vendor>-<model>-<capacity>.json`:

```json
{
  "label": "Kingston DataTraveler 100 G3 64GB",
  "purchase": {
    "vendor_sticker": "Kingston",
    "model_sticker": "DT100G3/64GB",
    "capacity_advertised_gb": 64
  },
  "host_sees": {
    "vid_pid": "0951:1666",
    "scsi_inquiry": "Kingston DataTraveler 3.0 PMAP"
  },
  "pcb": {
    "controller_marking": "PS2251-09-V",
    "controller_family": "Phison PS2251-09",
    "nand_marking": "TC58TEG6DDKTA00",
    "nand_vendor": "Toshiba",
    "nand_gen_guess": "3D TLC BiCS3",
    "eeprom_present": false,
    "crystal_mhz": 12
  },
  "photos": [
    "reports/photos/kingston-dt100g3-64g-pcb-top.jpg",
    "reports/photos/kingston-dt100g3-64g-pcb-bot.jpg"
  ]
}
```

Photo discipline: top of PCB, bottom of PCB, close-up of controller
marking, close-up of NAND marking. Even phone-camera-on-macro is enough.

---

## 4. What to do if you can't read the markings

Common reasons: counterfeit drives sand the markings; some vendors use
blank-top packages; some are under a thermal pad.

Fallback ID path, in order of reliability:

1. **VID:PID** → consult `data/controllers.json`. (Not conclusive — a VID:PID
   can belong to many controller SKUs.)
2. **ChipGenius** (Windows, free, from usbdev.ru). It queries the
   controller directly and often reports the family even without a visible
   marking.
3. **Vendor MPTool "scan" mode**. If you suspect Phison, run Phison
   UPTool's scan; if it recognizes the drive, you've got your answer.
4. **Pin-count + EEPROM presence + crystal frequency**: narrow by physical
   properties. 12 MHz crystal + no EEPROM + 48-pin NAND often indicates
   Phison PS2251. 24 MHz + EEPROM often indicates SMI or Alcor.

---

Next: [`02-controller-families.md`](02-controller-families.md).
