# 02 — Controller families and their tools

The USB flash controller world is dominated by five vendors. Each ships
many SKUs; each SKU has multiple firmware versions; each firmware version
pairs with one specific MPTool version. **Mismatch = brick.**

This chapter is a field guide, not an exhaustive catalog. The authoritative
up-to-date references are:

- https://flashboot.ru/ (Russian; use browser translation)
- https://usbdev.ru/ (Russian; use browser translation)

Both run forums where people share tool versions, firmware dumps, and
"revival" stories. Downloads there come as `.rar` or `.7z` archives often
from file-sharing services. Scan everything you download; the ecosystem is
unavoidably trust-us-bro.

---

## Phison (台湾 / Taiwan)

The 800-pound gorilla. Phison controllers power the majority of commodity
retail USB sticks sold under names like Kingston DataTraveler, PNY
Attaché, Verbatim Store 'n' Go, SanDisk Cruzer (some SKUs), Lexar JumpDrive
(some SKUs).

### Family tree

| SoC | USB | Peak advertised | Common in |
|---|---|---|---|
| PS2251-03 | USB 2.0 HS | 25 MB/s | legacy drives |
| PS2251-07 | USB 2.0 HS | 30 MB/s | ~2012 drives |
| PS2251-09 | USB 2.0 HS | 30 MB/s | lots of swag drives |
| PS2251-11 | USB 3.0 SS | 60 MB/s | mid-tier USB 3.0 |
| PS2251-13 | USB 3.0 SS | 100 MB/s | DT100 G3, lots of retail |
| PS2251-50 | USB 3.0 SS | 150 MB/s | newer DT, SanDisk Ultra Fit (some) |

### Tool

**Phison MPALL** (sometimes "UPTool"). You need the version matching your
controller's `IC version` and your NAND vendor.

Workflow:
1. Run `GetInfo` to read `IC version` and `firmware version`.
2. Download the matching MPALL bundle (contains firmware `.BIN`, config
   `.INI`, loader `.BIN`).
3. Edit the `.INI`:
   - `Preformat=1` → full erase (destroys data; must have backup).
   - `OverProvision=XX` (percent) → the main overclock knob.
   - `BurnerFile=` → NAND-specific burner `.BIN`.
4. Run MPALL. The drive disappears and reappears as a differently-sized
   mass storage device. If it reappears at the configured capacity, you
   won. If it stays in "Device Mode 03" or similar, you've got a brick to
   revive.

### What's actually tunable

- **Over-provisioning:** biggest honest gain. 10–20% OP typically yields
  20–40% better sustained write.
- **pSLC cache size:** `SLCCacheSize=` in the INI. Can grow or shrink.
- **USB mode:** PS2251-13 and up can be forced SS-only, which prevents
  the drive from dropping to HS on marginal cables.
- **NAND timing mode:** `TogglePerf=1` enables toggle-mode on compatible
  NAND. Can hang the drive if NAND doesn't actually support the grade.

### Revival (brick recovery)

Short the two test pads near the controller (TP1/TP2 on most Phison PCBs)
while plugging the drive in. The controller enters mass-production mode
and ignores its current firmware. MPALL can then overwrite.

Locating the test pads: photograph the PCB and compare to flashboot.ru
threads for your controller. Pads are usually marked "TP" or appear as
two bare pads side-by-side near the SoC.

---

## Silicon Motion (SMI)

Second biggest. Found in a lot of SanDisk, ADATA, Patriot, Transcend
drives.

### Family tree

| SoC | USB | Common in |
|---|---|---|
| SM3252 | USB 3.0 SS | mid-tier |
| SM3267 | USB 3.0 SS | ADATA UV150 |
| SM3268 | USB 3.0 SS | Transcend JetFlash 790 |
| SM3271 | USB 3.1 Gen1 | modern USB-A sticks |
| SM3281 | USB 3.2 Gen1 | 2020+ drives |
| SM3350 | USB 3.2 Gen2 | high-end |

### Tool

**SMI MPTool** ("Mass Production Tool"). Version must match SoC.

Workflow is similar to Phison but SMI uses a GUI-heavy flow:
1. Load the config `.ini`.
2. Set NAND auto-detect or pick the exact NAND SKU from a dropdown.
3. Hit "Start" and all plugged SMI drives are flashed in parallel.

### Tunables

- **Over-provisioning:** set in config INI, same idea as Phison.
- **ChannelMode / InterleaveMode:** SMI exposes NAND bus timing more
  directly. Values 0..5 for different speed grades.
- **DisableS/C** (static/dynamic SLC cache behavior).
- **USB SuperSpeed forcing:** `USB3Only=1`.

### Revival

SMI boot ROMs usually re-enumerate as `VID:090C PID:1000` when firmware is
corrupt. Plug in; MPTool should see it immediately. No pin-shorting needed
on most SMI SoCs — they fall back to boot mode on their own.

---

## Alcor Micro

Smaller share, but widespread in cheap no-name drives from Shenzhen.

### Family

- AU6981, AU6983, AU6989: USB 2.0 era.
- AU6998: USB 3.0 era.

### Tool

**AlcorMP** (Chinese: 安国量产工具). Interface is Chinese by default; a
Japanese translation floats around; no official English build.

Tunables are similar in spirit to the others: OP, NAND strap, USB mode.

### Revival

Alcor controllers often fall back to a boot mode VID of `058F:6387`. Plug
in blind; AlcorMP recognizes.

---

## Innostor (Phison subsidiary)

- IS916: USB 3.0, lightweight, found in cheap sticks.
- IS917: USB 3.0, slightly higher spec.

Tool: **Innostor MP Tool**. Similar flow to Phison (they're the same
company upstream).

---

## Chipsbank / Realtek / USBest

Lower volume. Chipsbank CBM2199E is common in no-name 2020-ish drives.
Realtek RTS5321 appears in some older USB 3.0 sticks.

Tools: **UMPTool** (Chipsbank), **Realtek USB Mass Production Tool**.

Documentation is thinner. flashboot.ru has threads but expect to search
hard.

---

## Decision tree

```
         ┌──────────────────────┐
         │  Marking on SoC?     │
         └──────────┬───────────┘
                    │
     ┌──────────────┼──────────────┐
     │              │              │
     ▼              ▼              ▼
   PS2251-xx     SM32xx         AU69xx
   → Phison      → Silicon      → Alcor
     MPALL         Motion         AlcorMP
                   MPTool

     ┌─ IS91x    ─ Innostor MP Tool  (Phison-family flow)
     ├─ CBM21xx  ─ UMPTool
     └─ Marking unreadable → ChipGenius → identify first
```

---

Next: [`03-safety.md`](03-safety.md) — don't skip this one.
