# 06 — Optimizing a USB drive for swap

Swap is a workload like no other. Tune a drive the way reviewers tune
for benchmarks (big sequential files), the drive is slow at swap. Tune
for swap, the drive is slow at reviewers' benchmarks. This chapter is
about the swap case — the profile `swap-aggressive` implements it.

---

## What swap actually looks like at the device level

Linux swap under memory pressure fingerprints like this:

```
  IO size              : 4 KB (page size — occasionally 2 MB huge pages,
                         but ≥95% is 4 KB small IO)
  Pattern              : random (anonymous pages are swapped in demand
                         order; no locality)
  Read/write mix       : 40–70% read, 30–60% write, both in flight
  Queue depth typical  : 1 (synchronous page-in)
  Queue depth burst    : 32+ (readahead windows, writeback)
  Burstiness           : very high — minute-long idle, then saturate
  Latency sensitivity  : extreme — swap latency IS the user's lag
  Throughput priority  : low — few workloads actually need >200 MB/s swap
  Endurance            : high — swap writes nearly continuously
```

Contrast with "USB stick for photo backup":
- Sequential 1 MB IO, QD=1, write-heavy, low endurance need, low
  latency sensitivity.

Those two workloads want OPPOSITE tunings. A drive tuned for photo
backup is slow at swap. A drive tuned for swap is slow at photo backup.
Pick one.

---

## The 7 tunables that matter for swap

### 1. Over-provisioning (OP)

**For swap: 25–35%.** (profile: 30%)

OP is the fraction of NAND reserved as spare. Spare blocks exist so the
controller can:
- Serve a write immediately (grab a pre-erased spare block)
- Do garbage collection without having to pause writes
- Keep wear leveling spread evenly

For sequential workloads, 5% OP is enough. For random mixed read/write
at QD=1, OP correlates strongly with sustained performance. 30% OP
roughly doubles sustained random write on commodity controllers.

**Trade:** usable capacity drops. 64 GB × 0.70 = 44.8 GB usable before
you also carve out the pSLC region (next).

### 2. pSLC cache mode and size

**For swap: static large, 20–30% of raw capacity.** (profile: 25%)

TLC NAND stores 3 bits per cell. The controller can treat a region as
if it stored only 1 bit per cell (pSLC = "pseudo-SLC"), which:
- Writes 3–4× faster
- Reads about the same
- Wears about 3× slower per actual program cycle

Default behavior: a **dynamic pSLC cache** of a few GB that slides
across the NAND. Good for burst writes, bad for sustained — once the
cache fills, performance falls off the "SLC cliff" to native TLC.

For swap, you want **static** pSLC: a fixed region, always pSLC,
dedicated. The controller treats writes to that region as pSLC always,
no cliff.

**Trade:** capacity. If 25% of a 64 GB drive is static pSLC, you lose
~16 GB. Combined with 30% OP, the drive advertises ~34 GB usable.

### 3. USB link mode

**For swap: force SuperSpeed.** (profile: `superspeed_force`)

Swap over USB 2.0 (480 Mbps = ~30 MB/s theoretical, 25 MB/s practical)
is painful. Over USB 3.0 (5 Gbps = 100–400 MB/s practical on commodity
sticks) is tolerable.

Many drives silently negotiate down to USB 2.0 on marginal cables or
old hosts. Force SuperSpeed via firmware so the drive refuses the
fallback.

**Trade:** on hosts that genuinely can't do USB 3.x, the drive won't
enumerate at all.

### 4. Garbage collection aggressiveness

**For swap: aggressive.** (profile: `aggressive`)

GC is background work the controller does to coalesce half-full erase
blocks into fully-free ones. More aggressive = faster response to new
writes, worse idle power.

Swap workloads have bursty structure: pressure → saturate → idle for
10 minutes → pressure again. Aggressive GC uses the idle time to
prepare for the next burst.

**Trade:** higher idle power. A USB stick doing aggressive GC can draw
400+ mA at idle vs. 50 mA stock. Hub may complain on long cable runs.

### 5. Write buffer / write combining

**For swap: minimal / low-latency mode.** (profile: `low_latency`)

Many controllers accumulate small writes in SRAM and flush larger
coalesced writes to NAND. Good for sequential write throughput, bad
for 4K random latency — a 4K page sits in SRAM waiting for siblings
that may never arrive.

Low-latency mode: write-through to NAND for small IOs. 4K page gets
written and acked immediately.

**Trade:** peak sequential throughput drops (because you lose
coalescing). Swap doesn't care.

### 6. ECC strength

**For swap: maximum rated.** (profile: `max_rated`)

Flash reads can suffer bit flips over time (retention) and under heavy
read load (disturb). ECC codewords correct up to N bit flips per
codeword. Stronger ECC = tolerates more flips = slightly slower decode
but safer data.

Swap pages are the one place where silent corruption directly becomes
process memory corruption. Use max rated ECC for the NAND generation.

**Trade:** slightly slower reads (microseconds). Not noticeable in
practice.

### 7. Thermal throttle setpoint

**For swap: 70–75°C.** (profile: 70°C)

Flash NAND program times get WORSE as temperature rises. Controllers
throttle (reduce write bandwidth) above ~70–80°C. Default is
conservative (~65°C). Swap-tuned drive runs hot continuously, so
raising the setpoint keeps full performance longer.

**Trade:** drive runs hotter, which reduces NAND retention lifetime
slightly. Monitor the enclosure.

---

## Settings people get wrong

**"Just enable the biggest pSLC cache possible."** Only in STATIC
mode. A huge DYNAMIC cache has a worse cliff than a smaller one (it
takes longer to flush when it fills).

**"Disable TRIM for USB — safer."** TRIM / discard matters MORE on
swap, not less. The controller needs to know which blocks are reusable
so it can GC them during idle gaps.

**"Use ext4 on top for safety."** No. Swap is raw blocks. Any
filesystem on top adds a layer of translation (block → file → block)
with its own journaling. Latency doubles for zero benefit on swap. The
only reason to put a filesystem on your swap drive is if you're also
using it for files, which defeats the point of this profile.

**"Set swap priority as low as possible so it's used last."** Opposite
if this is a tuned fast drive. Set priority HIGH (`--priority 100`) so
the kernel prefers this device over any slower swap device you might
also have.

**"Enable zswap AND use USB swap."** zswap compresses pages in RAM
before swapping to disk; a tuned USB drive is already fast. zswap is
primarily useful when your swap device is slow (spinning rust, SD
card). On a tuned USB 3 stick, zswap mostly adds CPU overhead without
helping latency. Try without first.

---

## Projected gains (commodity USB 3.0 64 GB drive, swap workload)

| Metric | Stock | Tuned (swap-aggressive) | Change |
|---|---|---|---|
| 4K random read, QD=1 | 8–12 MB/s | 20–30 MB/s | +150% |
| 4K random write, QD=1 | 1–4 MB/s | 10–20 MB/s | +400% |
| 4K random mixed, QD=1 | 2–5 MB/s | 12–18 MB/s | +300% |
| Sustained write (sequential) | 30–80 MB/s | 60–150 MB/s | +50–100% |
| Peak sequential read | 100–150 MB/s | 100–150 MB/s | unchanged |
| Advertised capacity | 64 GB | ~34 GB | -47% |
| Expected lifetime at 24/7 swap | 3–9 months | 12–30 months | ~3× |

Rough estimates. Real numbers depend on NAND generation, controller
SKU, host chipset, cable, and workload.

---

## Thermal and endurance

### Thermal

Sustained swap over USB puts the stick in continuous 1–2 W
dissipation. Plastic case + no airflow = 70–90°C junction temp.
Options to improve:

- **Metal-cased drive** (SanDisk Extreme Pro, Corsair Flash Survivor,
  Lexar JumpDrive M45). Metal case is a passive heatsink.
- **A short USB extension cable** to pull the drive off the host, away
  from host-generated heat.
- **An open-air USB-A → USB-C adapter** and let the drive dangle in
  open air rather than lying flat against a hot laptop chassis.
- **A tiny 40mm USB fan** aimed at the drive. Overkill but it works.

### Endurance

Flash endurance is quoted in Program/Erase cycles. Commodity TLC
NAND: 500–3000 P/E cycles. At stock OP (~5%), swap workload burns
through these roughly 10× faster than mixed-use. At 30% OP, closer to
3× faster than mixed-use.

Rough practical lifespan at this profile for a $10 USB stick running
as 24/7 swap under moderate pressure: **12–24 months**. Keep a second
drive flashed with the same profile as a hot spare.

Hibernation note: the hibernation image also lands on the swap
device. If you hibernate, be aware that memory snapshots pass through
this stick. Fine from a performance standpoint; worth remembering
from a data-exposure standpoint if you lose the drive.

---

## macOS reality check

**macOS does NOT support redirecting swap to an external device.** The
kernel's dynamic pager writes to `/private/var/vm/` on the boot volume
and there is no supported sysctl, mount option, or launchd shim to
move it. People have tried; everything that worked on 10.9 was closed
by 10.12.

This project's `swap_optimizer.py` can still tune the drive. To USE
the tuned drive as swap, move it to a Linux host.

If you want macOS-side swap optimization, your lever is memory
pressure settings (`sysctl vm.compressor_mode`, memory limits per
process). That's a different project.

---

## Why not just buy an SSD?

Fair question. A $25 USB NVMe enclosure + $30 128 GB NVMe stick
annihilates a $10 USB flash drive at swap. Factors of 10–50× faster
across the board, no tuning needed.

This project's value is NOT "USB flash as superior swap medium." It is:
- Learning what a flash controller actually is.
- Building the toolchain for anyone who wants to tune a drive for any
  workload.
- Making useful work out of drives you already have.

If you need production-quality swap performance, buy an NVMe. If you
want to understand flash and extract more out of what's on your desk,
you're in the right place.
