# usb-overclock-kit

[![Download USB-Overclock-Kit](https://img.shields.io/sourceforge/dt/usb-oc-kit.svg?label=SourceForge%20downloads)](https://sourceforge.net/projects/usb-oc-kit/files/latest/download) [![Download USB-Overclock-Kit](https://a.fsdn.com/con/app/sf-download-button)](https://sourceforge.net/projects/usb-oc-kit/files/latest/download)


Cross-platform recon, backup, benchmarking, and tuning for commodity USB
flash drives — with heavy documentation so a stranger can walk in cold
and understand what's actually happening inside the plastic stick.

**Not just overclocking.** "Overclock" is in the name because it's the
word people search for, but a USB flash controller doesn't have a clock
multiplier. The real knobs — over-provisioning, pSLC cache sizing, USB
link mode, NAND timing grade, thermal setpoint — all live in the vendor
MPTool INI. This project generates those INIs honestly, for a chosen
workload profile, with a revert path.

---

## What's in the box

```
usb-overclock-kit/
├── README.md
├── LICENSE                           ← MIT
├── docs/
│   ├── 01-open-the-drive.md          ← physical teardown + chip ID
│   ├── 02-controller-families.md     ← Phison / SMI / Alcor / Innostor landscape
│   ├── 03-safety.md                  ← backup discipline, bricking modes
│   ├── 04-what-overclocking-means.md ← honest scope of achievable gains
│   ├── 05-phison-mpall-ps2309-workflow.md   ← pull + make, step-by-step
│   ├── 06-swap-optimization.md       ← why swap is a special case
│   └── 07-profiles-and-reverting.md  ← profile library + revert path
├── tools/
│   ├── recon.py                      ← enumerate USB drives & controllers
│   ├── bench.sh                      ← backup / restore / benchmark
│   └── tune.py                       ← generate INI overlay + host script
├── data/
│   ├── controllers.json              ← VID:PID → controller family lookup
│   └── profiles/
│       ├── swap-aggressive.json      ← Linux swap workload
│       ├── balanced.json             ← fix-the-stock-defaults profile
│       ├── undervolt-cool.json       ← low-power / low-thermal
│       ├── endurance.json            ← max lifetime
│       └── max-throughput.json       ← peak-numbers / benchmark-friendly
└── reports/                          ← per-drive outputs land here
```

---

## What `tune.py` actually does

A USB flash controller firmware is reconfigured, not patched. The
vendor MPTool (Phison MPALL, Silicon Motion MPTool, Alcor AlcorMP,
etc.) reads an INI, writes new firmware based on that INI, and
reflashes the drive. The INI has sections like `[Preformat]`, `[MP]`,
`[Partition]` with keys like `OverProvision`, `SLCCacheSize`,
`USB3Only`, `ThermalThrottle`.

Factory-shipped INIs are conservative. `tune.py` generates an **INI
overlay** — just the lines you need to change — for a chosen workload
profile:

```bash
# Pick a profile and a drive:
./tools/tune.py apply --vid-pid 13fe:5500 --profile swap-aggressive

# Writes:
#   reports/13fe-5500-swap-aggressive/ini-13fe-5500-swap-aggressive.ini
#   reports/13fe-5500-swap-aggressive/host-linux-13fe-5500-swap-aggressive.sh
```

You then merge the overlay into your real MPTool base INI (the one
from flashboot.ru matching your IC version), run the MPTool's Check
step, and if OK, flash. Full step-by-step in
[docs/05-phison-mpall-ps2309-workflow.md](docs/05-phison-mpall-ps2309-workflow.md).

### Reverting

```bash
./tools/tune.py revert \
    --vid-pid 13fe:5500 \
    --stock-fw  reports/drive1/fw-stock.bin \
    --stock-ini reports/drive1/cfg-stock.ini
```

Generates a shell runbook that prints the Windows-side revert
procedure using the stock backup files you captured in the pull phase.
See [docs/07-profiles-and-reverting.md](docs/07-profiles-and-reverting.md).

### Listing

```bash
./tools/tune.py list-profiles      # catalog of profiles
./tools/tune.py list-drives        # what recon.py sees right now
```

---

## Platform support

| Phase | macOS | Linux | Windows |
|---|---|---|---|
| Enumeration (`recon.py`) | ✅ | ✅ (lsblk-based) | ✅ (future) |
| Backup / benchmark (`bench.sh`) | ✅ | ✅ | ⚠️ via WSL |
| INI generation (`tune.py`) | ✅ | ✅ | ✅ |
| **Firmware flash** | ❌ | ❌ | ✅ vendor MPTool |
| Linux swap setup (host script) | n/a | ✅ | n/a |

### The hard truth about firmware tools

Phison MPALL, SMI MPTool, Alcor AlcorMP, Innostor IS-tool, Chipsbank
UMPTool — all **closed-source Windows binaries**, redistributed on
[flashboot.ru](https://flashboot.ru/) and [usbdev.ru](https://usbdev.ru/).
No native macOS or Linux equivalent for the firmware write step.

This project does everything *around* that step and documents the
Windows handoff. You still need Windows (or Windows-in-UTM/Parallels
with USB passthrough) for the actual flash.

---

## What "overclock" means here (and what it doesn't)

A USB flash drive is not a CPU. There's no clock multiplier. "Overclock"
is shorthand for the real controller tunables:

- **USB link mode** — force SuperSpeed over HighSpeed
- **Over-provisioning** — reserve more NAND as spare for sustained writes
- **pSLC cache** — size / mode of the pSLC region (TLC drives emulate SLC for bursts)
- **NAND timing grade** — toggle-mode speed the NAND runs at
- **ECC strength** — error correction codeword size
- **Thermal setpoint** — temperature at which controller throttles
- **Idle garbage collection** — background cleanup aggressiveness

Honest expected gains for a $8–$15 commodity 64 GB USB 3.0 stick:

| Metric | Stock | Fully tuned | Change |
|---|---|---|---|
| 4K random write, QD=1 | 1–4 MB/s | 10–20 MB/s | +400% |
| 4K random read, QD=1 | 8–12 MB/s | 20–30 MB/s | +150% |
| Sustained sequential write | 30–80 MB/s | 60–150 MB/s | +50–100% |
| Peak sequential read | 100–150 MB/s | 100–150 MB/s | unchanged |
| Advertised capacity | 64 GB | 30–50 GB | varies by profile |

Nobody doubles their drive's peak sequential by firmware tuning.
Physics. See [docs/04-what-overclocking-means.md](docs/04-what-overclocking-means.md).

---

## Quickstart

```bash
# 1. Enumerate drives:
./tools/recon.py

# 2. BEFORE anything destructive, back up user data:
./tools/bench.sh backup /dev/diskN ~/usbdrive-backup.img

# 3. Baseline benchmark:
./tools/bench.sh bench-ro /dev/diskN

# 4. Open the drive to confirm the controller (recon's VID:PID is a hint,
#    not proof — see docs/01-open-the-drive.md):

# 5. Pick a profile:
./tools/tune.py list-profiles
./tools/tune.py apply --vid-pid 13fe:5500 --profile balanced

# 6. The pull + flash + verify loop (Windows-side):
#    see docs/05-phison-mpall-ps2309-workflow.md
```

---

## Current supported controllers

- **Phison** (PS2251-xx, PS2309) — INI mapper implemented
- SMI, Alcor, Innostor, Chipsbank — DB entries present, INI mapper
  not yet written. Contributions welcome.

Adding a family is one function in [tools/tune.py](tools/tune.py)
(see `map_phison`) plus a line in `FAMILY_MAPPERS`.

---

## Contributing

Three starting drives in play as this project was built. For your own
drive, submit a report:

```bash
./tools/recon.py --report > reports/<vendor>-<model>-<capacity>.json
```

PR welcome. Open the drive and photograph the controller + NAND
markings; those photos go in `reports/photos/`. The more drives
documented, the more useful `data/controllers.json` gets, which helps
future users identify their controller without opening the case.

Adding a new profile: drop a JSON file in `data/profiles/` with the
same structure as the existing ones. `tune.py` picks it up
automatically. Writing a new controller family: see `map_phison` in
`tune.py` for the pattern.

---

## Credits

The hard-won community knowledge about controller families comes from
flashboot.ru and usbdev.ru — this project is a tribute to those
forums, translated and reorganized for a Western / cross-platform
audience.

Built in collaboration with Claude Code.

## License

MIT. See [LICENSE](LICENSE).
