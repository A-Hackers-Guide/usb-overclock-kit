# 04 — What "overclocking a USB drive" actually means

The headline question people ask: *"If I overclock my USB stick, do I
double its speed?"*

The honest answer: **almost never, but you can usually gain 10–40% on
sustained writes, and sometimes recover 2–10× if the drive was silently
dropping to USB 2.0.**

This chapter breaks down why.

---

## Where USB flash speed actually comes from

```
┌─────────────────────────────────────────────────────────────┐
│  Host  ◄────USB 3 (5 Gb/s)────►  USB bridge in controller   │
│                                   │                          │
│                                   ▼                          │
│                           ┌──────────────┐                   │
│                           │ Controller   │                   │
│                           │  SoC (CPU +  │                   │
│                           │  FTL + ECC)  │                   │
│                           └──────┬───────┘                   │
│                                  │ NAND bus (ONFI/Toggle)    │
│                                  ▼                           │
│                        ┌────────────────┐                    │
│                        │   NAND flash   │                    │
│                        │   (1–4 dies)   │                    │
│                        └────────────────┘                    │
└─────────────────────────────────────────────────────────────┘
```

A write command's lifetime:

1. **Host → USB bridge:** 5 Gb/s (SuperSpeed) or 480 Mb/s (HighSpeed).
2. **Bridge → Controller SRAM buffer:** typically 50–150 MB/s depending
   on bridge and SoC.
3. **Controller → NAND page:** ONFI/Toggle bus at e.g. 200–533 MT/s per
   channel, but a page program takes 200µs–3ms *regardless of bus speed*.
   This is the real bottleneck.
4. **NAND internal:** program + verify. QLC is slow (~3ms), TLC is
   middling (~800µs), pSLC is fast (~250µs).

The ceiling on a single-channel, single-die drive is set almost entirely
by step 3+4. **No firmware tweak changes the NAND program time.**

What firmware tweaks *do* change:

- Whether multiple NAND dies get interleaved (parallelism).
- Whether short bursts land in a fast pSLC cache first.
- Whether the controller stalls to do garbage collection.
- Whether the bus speed is high enough to actually feed the NAND.

---

## The real tunables, in order of impact

### 1. USB link mode — biggest potential gain, if it applies

Many cheap USB 3.0 drives negotiate down to HighSpeed (USB 2.0) on
marginal cables, old chipsets, or long cable runs. The drive silently
becomes a 30 MB/s device instead of a 100 MB/s device. A 3× hit, invisible
to the user.

**How to detect:** `recon.py` reports the negotiated link speed. If it
says `HighSpeed` on a drive marketed as USB 3.x, you have slack.

**How to fix:** force SuperSpeed in the controller firmware. Most Phison
PS2251-13+ and SMI SM32xx controllers have a `USB3Only=1` or equivalent
INI flag.

**Risk:** if the drive *couldn't* reliably SS on this hardware, forcing
it will give you enumeration failures. Keep a USB 2.0 fallback plan.

### 2. Over-provisioning (OP)

Flash drives advertise their capacity in units of ~1 billion bytes but
have NAND in units of 2^n. A "64 GB" drive has 64 × 10^9 bytes advertised
and typically 68.7 × 10^9 bytes (64 × 2^30) of NAND, with ~4.7 GB of
"natural OP."

Setting OP higher reserves more NAND as spare blocks. The controller uses
spare blocks to:
- Serve writes immediately without waiting for GC
- Keep a larger pool of pre-erased blocks
- Spread wear more evenly

**Trade:** advertised capacity drops. Set 20% OP on a 64 GB drive and it
appears as 51.2 GB to the host. In return, sustained write throughput
can jump 20–40%.

**How to set:** in the MPTool's INI, `OverProvision=20` (or similar).

### 3. pSLC cache sizing

TLC NAND stores 3 bits per cell. Writing all 3 bits precisely takes
~800µs–3ms. But if the controller treats a region of TLC as if it were
SLC (1 bit per cell), it can write that region at ~250µs — about 3–4×
faster.

Modern consumer drives use a **dynamic pSLC cache**: a sliding region of
NAND is operated in pSLC mode for incoming writes. When the cache fills,
sustained write speed drops to native TLC speed (the dreaded "SLC cliff").

**Tuning the cache size:**
- Larger cache → longer burst at peak speed, but worse sustained once
  cache is full (because flushing takes longer).
- Smaller cache → shorter burst, more consistent sustained.

Neither is strictly better. Depends on workload: large sequential writes
want small cache; many small bursts want large cache.

### 4. NAND interface timing (toggle mode / ONFI speed grade)

The NAND datasheet specifies which clock speeds a given die is rated for
(e.g. "Toggle 2.0 up to 400 MT/s"). Factory firmware often clocks the
NAND at a conservative grade to be safe across the entire lot.

**Bumping the grade** (e.g. `TogglePerf=1` in Phison INIs, or
`InterleaveMode=5` in SMI configs) can gain 10–20% if the NAND is
underclocked.

**Risk:** NAND bit error rate scales with clock. ECC *can* compensate up
to its budget; beyond that, you get read failures.

### 5. ECC strength

Error-correction codewords protect NAND pages against bit flips. Stronger
ECC = more bit errors tolerated = can push NAND harder = slower per-page
decode. The controller/NAND pairing is designed around one ECC level.

**Almost never user-tunable.** Skip.

### 6. Garbage collection aggressiveness

The controller does housekeeping (GC) in idle time. More aggressive GC =
drive is "fresh" when writes arrive = faster sustained. Less aggressive =
drive uses less power when idle.

Some SMI MPTool configs expose this. Phison usually doesn't.

---

## Expected outcomes

For a $8–$15 commodity 64 GB USB 3.0 drive, honest expected results:

| Starting state | After tuning | Likely gain |
|---|---|---|
| Negotiating down to HS silently | Forced SS | 2–10× |
| Default OP (0–3%) | OP = 20% | +20–40% sustained write |
| Default pSLC cache | Right-sized for workload | More consistent, not higher peak |
| Default NAND timing | Faster grade (if supported) | +10–20% peak |
| **All of the above combined** | Fully tuned | **+40–80% in good cases** |

A drive marketed as "150 MB/s write" might realistically become a 200
MB/s drive. Not a 500 MB/s drive. Physics.

---

## When tuning won't help

- **Drive is already at its NAND ceiling.** High-end drives (SanDisk
  Extreme Pro, Samsung Fit Plus) ship with aggressive factory tuning.
  Tuning gains are near-zero.
- **Workload is random 4K.** Random performance is dominated by FTL
  latency and GC behavior, which are deeply fused into the firmware.
  Not easily tunable.
- **NAND is at end-of-life.** A worn drive has slow pages. Tuning won't
  resurrect wear.

---

## When tuning *will* help

- Cheap retail drive marketed as 100+ MB/s that actually benchmarks at
  40 MB/s on sustained write.
- Drives that silently drop to USB 2.0.
- Workloads with lots of sequential writes (video capture, backups).

These are the three most common "stuck slow" scenarios, and they're
exactly where this project focuses.

---

Back to [README](../README.md).
