# 07 — Profiles and reverting

This chapter covers the profile library (what each one does, when to
pick which) and the revert path (how to roll a tuned drive back to
stock).

## The profile library

Profiles live in [`data/profiles/*.json`](../data/profiles/). Each is a
JSON document describing a target workload and the tuning values that
suit it. `tools/tune.py` reads them and dispatches to the controller
family's INI mapper.

### `swap-aggressive`

Prioritize sustained random 4K IOPS and endurance for Linux swap.

- OP: 30%, static pSLC 25%, SuperSpeed force, aggressive GC, max ECC,
  low-latency write buffer, 70°C throttle.
- Capacity: 64 GB → ~34 GB usable.
- Reality check: macOS can't redirect swap to external drives. This
  profile is Linux-only in practice.
- Full write-up: [`docs/06-swap-optimization.md`](06-swap-optimization.md).

### `undervolt-cool`

Low-power / cool-running profile. Translates the "undervolt" concept
honestly for a USB flash controller: lower NAND clock grade, LPM
enabled, modest OP, cool thermal setpoint.

- OP: 15%, dynamic pSLC 8%, allow HS fallback, minimal idle GC, standard
  ECC, standard write buffer, 55°C throttle.
- Capacity: 64 GB → ~50 GB usable.
- A USB flash controller doesn't expose a VID offset like a CPU, so
  "undervolt" means power-down tactics, not voltage adjustment. The
  gain is lower idle current and cooler junction temp, not literal
  voltage.
- Best for: drives in enclosed cases, drives running continuously, or
  anywhere thermal budget is tight.

### `balanced`

The drive the OEM should have shipped. Reasonable OP, modest pSLC,
SuperSpeed forced, factory-safe thermal setpoint.

- OP: 15%, dynamic pSLC 15%, SuperSpeed force, moderate GC, max ECC,
  adaptive write buffer, 65°C throttle.
- Capacity: 64 GB → ~46 GB usable.
- Best for: a daily-driver USB stick for mixed read/write — the "fix
  the stock firmware's conservative defaults" profile.

### `endurance`

Maximum lifetime. Huge OP, static pSLC, aggressive GC, conservative
NAND timing.

- OP: 40%, static pSLC 20%, SuperSpeed force, aggressive GC, max ECC,
  rated_mid NAND timing, 60°C throttle.
- Capacity: 64 GB → ~30 GB usable.
- Best for: log/cache drives, 24/7 recorders, long-running swap, any
  write-heavy use that needs multi-year life.

### `max-throughput`

Peak numbers. Huge DYNAMIC pSLC cache, minimal OP, high NAND clock,
generous thermal headroom.

- OP: 7%, dynamic pSLC 40%, SuperSpeed force, idle-only GC, HT
  coalesce buffer, 75°C throttle.
- Capacity: 64 GB → ~59 GB usable.
- Trade-off: nice benchmark numbers, ugly SLC cliff on sustained
  writes. Great for short burst use. Bad for filling the drive end
  to end.

## Picking a profile

| If you want… | Pick |
|---|---|
| Linux swap drive | `swap-aggressive` |
| Daily-driver USB stick (OEM-reset+) | `balanced` |
| Drive to run cool / low power | `undervolt-cool` |
| 24/7 log, recorder, long-run swap | `endurance` |
| Benchmark numbers, short bursts | `max-throughput` |
| Factory default | revert — see below |

## How a profile becomes an INI

```
profile JSON (data/profiles/<name>.json)
    │
    │  tune.py apply --profile <name> --vid-pid <V:P>
    ▼
family mapper (map_phison / map_smi / …)
    │     maps profile.targets to vendor-INI {section: {key: value}}
    ▼
ini-overlay-<vid>-<pid>-<profile>.ini
    │     human merges into the real MPTool base INI
    ▼
MPTool base INI (edited)
    │     MPTool.exe --check  (dry-run)
    │     MPTool.exe --start  (actual flash)
    ▼
flashed drive
```

The overlay is NOT a complete INI — it only contains the lines you
need to change. Factory lines you don't touch stay at factory values.
This is important because the full stock INI has drive-specific fields
(NAND strap, SKU IDs, serial format) that must not be clobbered.

## Reverting (the "back" button)

The user said "and bakc" during planning — meaning: once I tune a
drive, I need a path back. Here it is.

### 1. Backup discipline (done during pull)

See [`docs/05-phison-mpall-ps2309-workflow.md`](05-phison-mpall-ps2309-workflow.md)
section A3-A4. You should have, from your pull phase:
- `reports/<drive>/fw-stock.bin` — stock firmware dump
- `reports/<drive>/cfg-stock.ini` — stock INI dump (if MPTool supports)

### 2. Generate a revert runbook

```bash
./tools/tune.py revert \
    --vid-pid 13fe:5500 \
    --stock-fw   reports/drive1-ps2309/fw-stock.bin \
    --stock-ini  reports/drive1-ps2309/cfg-stock.ini \
    --out-dir    reports/drive1-ps2309
```

This writes `reports/drive1-ps2309/revert-13fe-5500.sh` — a shell
script that prints the step-by-step revert procedure. The actual
revert happens in the vendor MPTool on Windows (same as the forward
flash — this project doesn't run MPTool).

### 3. Run the revert on Windows

The runbook explains it:
1. Launch the SAME MPTool build you flashed with.
2. If the build supports Restore / Reflash: point it at your stock
   firmware + stock INI, hit Start.
3. If it doesn't: reload the stock INI by itself and hit Start —
   MPTool regenerates firmware based on the INI, equivalent to a
   stock reflash.
4. Confirm the drive comes back at the original advertised capacity.

### 4. Keep your tuned INI around

Even after reverting, don't delete your tuned INI. The re-apply is
trivial if you decide you want the tune back — just reload your
tuned INI and reflash.

## Edge cases

### "I didn't dump stock firmware during pull — can I still revert?"

Partially. You can:
- Flash a FRESH stock INI from a flashboot.ru pack matching your IC
  version — the drive comes out "like new" but with their chosen
  defaults, not your original drive's defaults. For a mass-produced
  drive, this is usually indistinguishable from the original.
- You CANNOT recover the exact serial, VPD strings, or any other
  per-drive metadata that was factory-flashed. Most people don't
  care, but if your workflow depends on a specific serial (DRM-ish
  licensing, backup software bindings), those bindings break.

### "The drive is a brick after I flashed my tune. Can I revert?"

If the drive still enumerates in Boot ROM mode:
- Yes, just flash the stock firmware via the revert runbook.
- `recon.py` will tell you if it's in Boot ROM mode (that's exactly
  what it detected on drive #1 at the start of this project).

If the drive is invisible to the host:
- Try TP-pad shorting (see docs/03-safety.md) to force Boot ROM mode.
- If that doesn't work, you're in NAND-reader territory. For a
  commodity drive, usually not worth it.

### "I want to switch from swap-aggressive to balanced."

That's not a revert — it's a re-tune. You just:
1. `tune.py apply --vid-pid X:Y --profile balanced` → generates new
   overlay.
2. Merge new overlay into the base INI you used before (same base,
   different overlay).
3. Flash. The drive moves between profiles via a normal MPTool run,
   each flash erasing user data.

**No partial switch:** profiles are a complete setting bundle. You
can't flash "just the pSLC change" and keep the current OP. Any
MPTool flash is a full reconfigure.

## Shortcut cheatsheet

```bash
# List profiles
./tools/tune.py list-profiles

# List drives recon can see
./tools/tune.py list-drives

# Apply a profile
./tools/tune.py apply --vid-pid 13fe:5500 --profile swap-aggressive

# Generate a revert runbook
./tools/tune.py revert --vid-pid 13fe:5500 --stock-fw reports/drive1/fw-stock.bin
```
