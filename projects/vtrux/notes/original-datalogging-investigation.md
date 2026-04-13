# Original Datalogging Investigation

## Hardware Inventory — Truck 1

Both Vtruxes came from Via Motors with a factory-supplied breakout harness on the Via-specific OBD
port. This port exposes all three CAN buses. The harness splits them into two standard OBD2-pinout
connectors and includes a relay that switches a cigarette lighter socket when the truck is active.

**Bus wiring on the breakout harness:**
- The two OBD2 connectors on the Via breakout harness carry the **OBD bus** and **Powertrain bus**.
- The **Vehicle bus** is not carried on the breakout harness; the regular OBD2 DLC (above the
  Via-specific connector) gives access to the OBD bus as normal.

Hardware found connected on Truck 1:
- **iPhone** -- powered from cigarette lighter; has an app called **"EPRI Logger"** (confirmed 2026-03-26 by powering up the unit). App launches then immediately crashes -- likely iOS version incompatibility or missing backend server.
- **2x GoPoint BT1** Bluetooth OBD2 dongles -- one on the Vehicle bus connector, one on the PT bus connector
- **Samsara VG34** -- CAN gateway/telematics device, tucked in with the harness
- **Pathway Technologies Inc MPR 3 Multi Protocol Router** (model 10-01-02) -- at the rear of the
  truck near the charger. Pinout label: CAN Low, CAN High, Pilot Return, 12V, Power GND, Control Pilot.
  Bears EPRI logo.

GoPoint BT1 internals (unit disassembled):
- **Roving Networks RN-42** Bluetooth 2.1 chip (SPP serial bridge)
  - FCC ID: T9J-RN42, IC: 6514A-RN42, Bluetooth QDID: B014867
- **Freescale MC9S12XS** microcontroller (the protocol engine)

---

## Two-Layer Installation

Research revealed the hardware cluster represents two distinct installations:

**Layer 1 -- Via Motors proprietary telematics (for the INL/EPRI fleet study):**
Via Motors installed their own undisclosed logging hardware on every fleet truck. Data path was:
`truck -> Via proprietary logger -> EPRI server -> INL via NDA-protected server feed`.
The specific logger brand/model is not publicly disclosed. This is what fed the INL study data.
The GoPoint/Samsara/MPR 3 cluster is NOT this hardware.

**Layer 2 -- EPRI smart charging research apparatus:**
Pathway Technologies was the named "Smart Charging Developer and Producer" for the DOE/EPRI
Plug-In Hybrid Medium-Duty Truck Demonstration and Evaluation Program (OSTI 1234437). The MPR 3
and likely the GoPoint dongles are part of this layer.

---

## Part 1 -- GoPoint BT1 Findings

### What it is

The device is **not ELM327 compatible** and uses no AT commands. It communicates over Bluetooth
SPP (via the RN-42) using a **proprietary binary packet protocol**: 2-byte message type ID,
1-byte length, up to 12 data bytes. The host must be GoPoint-aware (the standard GoPoint app,
DashCommand, Harry's LapTimer, or a custom implementation).

Source: GoPoint Technology OBD Programming Manual v4.6 (February 2013).

### Supported protocols (confirmed from programming manual)

| Code | Protocol |
|------|----------|
| 0x00 | CAN 11-bit ID, 500 kbaud |
| 0x01 | CAN 29-bit ID, 500 kbaud |
| 0x02 | CAN 11-bit ID, 250 kbaud |
| 0x03 | CAN 29-bit ID, 250 kbaud |
| 0x04 | J1850 VPW (GM/Chrysler) |
| 0x05 | J1850 PWM (Ford SCP) |
| 0x06 | ISO 14230 KWP2000, 5-baud slow init |
| 0x07 | ISO 9141, 5-baud slow init |
| 0x08 | ISO 14230 KWP2000, fast init |
| 0x0A | CAN 11-bit ID, 125 kbaud |
| 0xFF | Trigger bus discovery |

This covers ISO 15765-4 standard OBD-II over CAN (11-bit, 500 kbaud) and the J1939 physical
layer (29-bit, 250 kbaud).

### Two operating modes

**Standard mode** (default):
- Auto-detects bus; automatically polls RPM every second
- Issues OBD-II Mode 01 PID requests using functional address 0x07DF
- Handles ISO-TP flow control internally
- Example: `0x07DF 0x02 0x01 0x0C` for RPM (Mode 01, PID 0x0C)

**Extended mode** (host-initiated, must enter within ~3 sec of power-up or after):
- Auto RPM polling stops
- Host must supply full header bytes and manage ISO-TP flow control
- Allows **arbitrary CAN frame injection and OEM-specific messages** -- explicitly documented
- Via Motors may have used a custom app in extended mode to query proprietary CAN IDs

### J1939 and UDS

- **J1939 physical layer:** confirmed supported (29-bit, 250 kbaud). No native J1939 PGN
  handling documented -- would require extended mode with manually constructed frames.
- **UDS/ISO 14229:** not a native mode. Possible via extended mode (ISO-TP flow control can be
  set up manually), but not documented as a built-in capability.

### Implication for the Vtrux

The GoPoints were in standard mode for normal OBD app use, issuing 0x07DF Mode 01 requests on
the Vehicle and PT buses. For the VCM to have answered, it must respond to 0x07DF on those
buses -- we know it answers 0x7E8 on the OBD bus (PID 0x0D confirmed). Whether it also
responds on Vehicle/PT buses is **confirmed plausible but not yet tested**.

---

## Part 2 -- INL / EPRI Fleet Study Findings

### Program overview

- **Program:** DOE/ARRA Plug-In Hybrid Medium-Duty Truck Demonstration and Evaluation
- **Sponsors:** U.S. DOE (ARRA), EPRI, SCAQMD, California Energy Commission
- **Program manager:** EPRI
- **Vehicles:** 125 VTRUX pickups + 52 VTRUX vans + 119 Odyne Class 6-8 trucks; deployed to
  >50 fleet operators (SCE, PG&E, Verizon, FedEx, U.S. Air Force, universities, municipalities)
- **Timeline:** Vehicle builds from July 2013; last delivery October 2014; data through 2015
- **Primary report:** OSTI 1234437 / EPRI 3002006566 (Miyasato/Kosowski, Oct 2015)
- **INL factsheets:** avt.inl.gov/project-type/via-motors.html (403-gated PDFs)
- **CEC follow-on:** CEC-600-2020-010 (Impullitti/Kosowski, 2020)

### Data collection method

Via Motors installed proprietary onboard logging hardware (brand/model undisclosed, under NDA).
Data flowed: `vehicle -> Via logger -> EPRI server -> INL via NDA server feed`. INL did not
install its own hardware and received pre-processed "vehicle network data."

The phrase "vehicle network data" implies CAN-level access via Via's own logger reading the PT
bus directly -- the signals (SOC, operating mode, fuel) are not accessible via standard OBD-II
and would require direct CAN access or Mode 22. Specific CAN IDs and PIDs are under NDA and
not published anywhere.

### Data captured (inferred from published outputs)

- Vehicle speed and trip distance
- Operating mode: charge-depleting (CD, EV) vs charge-sustaining (CS, engine-on), per trip
- State of charge (SOC) -- used to determine CD/CS transitions and characterize charging
- Fuel consumption (gallons, CS mode)
- Electrical energy consumption (kWh, CD mode)
- Charging events (time, duration, energy delivered)
- Driver-selected "Hold mode" (engine forced on to protect SOC)
- GPS/location

No OBD PID numbers, CAN message IDs, or raw signal definitions appear in any public document.

### Key study findings (for context)

- VTRUX pickups drove on EV power (CD mode) only ~17% of miles -- well below manufacturer
  claims based on assumed <35 miles/day fleet usage
- Fuel economy in CS mode: ~18 mpg (worse than base Silverado ~20 mpg highway)
- Root cause: fleet trips routinely exceeded the ~35-mile CD range; highway driving engages
  the engine regardless of SOC

---

## Part 2b -- Samsara VG34 Findings

The VG34 supports one CAN bus only (secondary CAN is a VG54 feature). It was almost certainly
plugged into the standard OBD-II DLC (OBD bus), not the Via breakout harness connectors.

- Black-box telematics -- processed telemetry uploaded to Samsara cloud, no raw CAN frames
- No Via Motors-specific decoder; no documented EV support for aftermarket conversions
- Likely captured from GM chassis: GPS, speed, 12V voltage, engine states, odometer, DTCs
- HV battery SoC, motor torque, BMS data: invisible to it (proprietary Via CAN, not on OBD bus)
- **Conclusion:** Not a useful ground-truth source for the RE project.

---

## Part 2c -- Pathway Technologies MPR 3 Findings

### Identity

Pathway Technologies Inc. was the **named "Smart Charging Developer and Producer"** for the
DOE/EPRI PHEV fleet program. Their MPR 3 (model 10-01-02) is a purpose-built EPRI research
device -- no public datasheet, no commercial product listing, no indexed documentation found.

### Function

The MPR 3 is a **J1772 Control Pilot to CAN gateway**. Based on pinout and program context:

- Monitors the J1772 **Control Pilot** signal: PWM duty cycle encodes available EVSE current;
  voltage level encodes charging state (A=disconnected, B=connected, C=charging, D=ventilation)
- Monitors **Pilot Return** (vehicle side of pilot circuit -- vehicle signals readiness to charge)
- Outputs **CAN messages** to the vehicle network (CAN High/Low connect to a vehicle bus)
- Powered from vehicle 12V accessory supply
- Located at the rear near the charger = correct placement for a J1772 monitoring device

The "Multi Protocol Router" name likely refers to bridging between the J1772 analog pilot
protocol and the vehicle CAN network. May also bridge to a utility-facing demand response
channel (cellular/cloud) -- the "multi" could refer to J1772 + CAN + network.

### What CAN bus it connects to

Almost certainly the **Powertrain bus** -- the PT bus is where the Bel Fuse charger lives, and
the MPR 3 is physically co-located with the charger. Demand response commands (delay charging,
reduce current) would need to reach the Bel Fuse charger module, which is on the PT bus.

### CAN output content (inferred)

The MPR 3 likely generates CAN messages encoding:
- J1772 state machine (A/B/C/D/E/F states)
- Available current (derived from pilot PWM duty cycle, e.g. 16% duty = 10A, 50% = 32A)
- Charge session start/stop events
- Possibly utility demand response commands (charge delay, setpoint)

These messages would appear only during plug-in events. **We may already have them in existing
charge-session logs and simply haven't identified them as MPR 3 output.**

### EPRI iPhone app

**Confirmed 2026-03-26:** The iPhone has an app named "EPRI Logger". It launches then
immediately crashes -- either it was never meant to open, or the backend server it phones home to 
is no longer running. The app name "Logger" suggests it was a data collection display/relay tool,
not just a demand response controller.

iPhone configuration confirmed:
- **Paired to both GoPoint BT1 dongles** (one on OBD bus, one on PT bus) -- the app was
  reading from both buses simultaneously
- **Location access: enabled** -- GPS was being logged alongside CAN data
- **Background App Refresh: enabled** -- the app continued logging/uploading even when not
  in the foreground; designed for always-on fleet operation
- **Cellular Data: enabled** -- data was being uploaded live over cellular to an EPRI server,
  not just stored locally

This confirms the EPRI Logger was a **live telemetry uplink**: GoPoint BT1 pairs -> iPhone
reads both Vehicle and PT buses via GoPoint binary protocol -> EPRI Logger packages data with
GPS and uploads over cellular to EPRI backend in real time.

---

## Open Questions

- Which GoPoint dongle was on which bus (Vehicle vs Powertrain)? Via_OBD_List has 0x00C9
  (OBD bus) and TRAC MCU IDs; Via_CANid_List has BCM + GENE MCU + Bel Fuse IDs (PT bus).
  This strongly implies: GoPoint 1 on PT bus (reads GENE + BCM + Bel), GoPoint 2 on OBD
  bus (reads TRAC + GMLAN engine). The Vehicle bus (EBCM, wheel speeds) does NOT appear in
  either list -- EPRI may not have connected to it, or the GoPoints only saw two buses.
- Does the VCM respond to 0x7DF Mode 01 on the Vehicle and/or PT bus? (Key unknown -- Part 4)
- Was the Samsara VG34 on the OBD bus or on one of the breakout harness connectors?
- What CAN IDs does the MPR 3 generate? Are they already in our charge-session logs?
- What are the byte positions and scales for 0x0410/0x0420/0x0430/0x0440 BCM messages?
  The plist key suffix (.11, .12, etc.) appears to be a signal index, not a byte offset.
  Need to run analyze_id.py on these IDs in existing logs.
- What is the scale for 0x0054 GENE_RotSpd? Compare against 0x051 B3-B4 RPM reference.
- What is the scale for 0x0044 TRAC_RotSpd? Is this ID visible in any existing log?
- Does 0x18FFD6C0 have overlapping signals with BelInverter.dbc? Check for duplicates.

---

## Part 3 -- EPRI Logger iPhone Analysis (COMPLETE 2026-03-26)

> Extraction was completed 2026-03-26. Actual findings (app identity, signal maps,
> binary decompile, all signal decodings) are documented in **`epri-decompile.md`**.

**Goal:** Extract and analyze the EPRI Logger app from the iPhone to determine exactly what
GoPoint queries EPRI was issuing and what CAN data was being collected. This directly informs
Part 4 -- rather than sweeping blind, we get EPRI's own query list.

**iPhone:** MF269LL/A, iOS 8.3 build 12F70

**CORRECTION 2026-03-26:** Device is an **iPhone 4S (A5 chip)**, NOT an iPhone 5s as
previously noted. Confirmed by 30-pin dock connector (iPhone 5s uses Lightning). The
model number MF269LL/A and iOS version were read from Settings → General → About on the
physical device. lsusb correctly identified it as "iPhone 4S" -- the earlier notes
incorrectly overrode this with an assumption.

**DO NOT upgrade the iOS** -- the app binary lives on device NAND and is not included in
iTunes backups. Upgrading destroys the only copy of the binary.

### Jailbreak situation (updated 2026-03-26)

- **checkra1n / checkm8:** Does NOT support A5. iPhone 4S is out of scope for checkra1n.
  All prior notes about checkra1n, checkm8, s5l8960x bootrom are irrelevant -- ignore.
- **palera1n:** Does not support A5 -- ignore.
- **EtasonJB:** iOS 8.4.1 only -- ignore.
- **TaiG 2.x and PP Jailbreak:** Cover iOS 8.1.3--8.4 on A5 but both confirmed dead --
  no offline/patched builds exist. Server check cannot be bypassed. Dead end.
- **EverPwnage (by LukeZGD):** RECOMMENDED. Sideloaded IPA, no server dependency,
  fully offline. Supports iPhone 4S / A5 on iOS 8.3--8.4.1 (untethered via `daibutsu`
  untether + `oob_entry` exploit). Installs Cydia. GitHub: LukeZGD/EverPwnage.
  Install via: OTA from jailbreaks.app/legacy.html (no PC needed) or Sideloadly
  (Windows/Mac only -- not available for Linux). v2.0 released 2026-03-27.
- **Carbon (by mineekdev/staturnzdev):** WebKit exploit, Safari-based, no PC required.
  Open http://carbon.sep.lol in Safari on device. Requires internet to reach that site
  for initial jailbreak only; untethered afterward. ios.cfw.guide primary recommendation
  for iPhone 4S iOS 8.x. Simpler but depends on carbon.sep.lol staying online.
- **Current recommended path (2026-03-26):** Carbon (easiest -- Safari only, no PC) or
  EverPwnage OTA (no PC, fully offline after install). Both untethered on iOS 8.3.

### Step 1 -- Charles Proxy network intercept (no jailbreak, do before jailbreaking)

The app crashes on launch almost certainly because it can't reach its backend server. If we
can fix the crash, the app reaches a running state which makes memory dumping much easier.

On iOS 8.3 without jailbreak:
1. Configure iPhone Wi-Fi to use Charles Proxy (manual HTTP proxy on LAN IP, port 8888)
2. Install Charles Root CA on the iPhone (Settings -> General -> Profiles)
3. Launch EPRI Logger -- Charles will capture the failing request and show the dead endpoint
4. Set up a stub HTTP/HTTPS server on the LAN returning a plausible response for that endpoint
5. Use router DNS (or a LAN DNS server like dnsmasq) to redirect the dead domain to the stub
6. Test whether the app reaches a running state

**Why this matters:** An app running stably is much easier to dump than one that crashes
immediately. FairPlay decryption happens when the binary maps into memory at launch -- if
the crash is post-`main()` (SIGABRT / NSException type), the binary is fully mapped and
dumpable. If it's pre-`main()` (dyld crash), the window is narrow.

### Step 2 -- checkra1n jailbreak

**Platform: Linux or macOS with USB-A port.** Windows is unreliable for checkm8 DFU due to
USB driver issues. A Linux live USB (Ubuntu/Debian) on the Windows machine works well.

1. Download checkra1n CLI from checkra1n.com (use Linux binary for best reliability)
2. Put iPhone 5s into DFU mode: hold both buttons 10s, release power while holding home 5s
3. Run checkra1n -- exploits bootrom via pongoOS, applies kernel patches, boots jailbroken
4. Via Cydia, install: OpenSSH, Clutch or CrackerXI+ (for FairPlay decryption)
5. SSH into device via USB tunnel: `iproxy 2222 22` then `ssh root@localhost -p 2222`

**USB note:** Use a direct USB-A port. Some USB-C hubs break checkm8 DFU detection.

### Step 3 -- Check encryption status first

Before attempting memory dumping, check if the binary is even encrypted:

```
otool -l /var/containers/Bundle/Application/<UUID>/EPRILogger.app/EPRILogger | grep -A4 LC_ENCRYPTION_INFO
```

- **cryptid = 0:** Binary is NOT FairPlay encrypted (enterprise distribution). Pull it
  directly with SCP and open in Ghidra -- no memory dumping needed.
- **cryptid = 1:** Binary is FairPlay encrypted. Proceed to Step 4.

**Enterprise distribution is plausible** -- EPRI deployed this to a research fleet, not the
App Store. Enterprise-signed IPAs have cryptid=0 and require no memory dumping.

### Step 4 -- FairPlay decryption (if cryptid=1)

Requires the app to be running (see Step 1 -- fix the crash first if possible).

Options (install via Cydia on jailbroken device):
- **CrackerXI+** -- simplest, GUI app, tap to dump running apps
- **Clutch** -- CLI, `Clutch -d <BundleID>`
- **frida-ios-dump** -- most automated; install Frida server via Cydia, run the Python
  script from the host: `python frida-ios-dump/dump.py com.epri.logger` (or whatever the bundle ID is)

Crash log type determines feasibility:
- SIGABRT / NSException after launch = post-`main()` crash = binary fully mapped = dumpable
- EXC_BAD_ACCESS in dyld = pre-`main()` = harder; fixing the crash (Step 1) is essential

### Step 5 -- Binary analysis

With decrypted binary in hand (transfer to Windows for analysis):

- **Sysinternals `strings.exe`** -- first pass: server URLs, GoPoint command bytes, PID/DID
  constants, Bluetooth device name strings
- **Ghidra** (free, Java, Windows) -- ARM disassembly, full static analysis
- **class-dump** (Mac-only, optional) -- ObjC class/method names, cleaner symbol map

Look specifically for:
- EPRI backend server hostnames/IPs and API endpoint paths
- GoPoint binary protocol message type IDs being constructed in code
- CAN IDs, OBD Mode 01 PIDs, or UDS DIDs hardcoded as constants
- Bluetooth device name filter strings (how the app found the GoPoint dongles)

### Expected findings

- EPRI backend server URL (reveals data schema even if server is dead)
- GoPoint message type IDs for the PIDs/DIDs EPRI queried
- Standard mode (0x7DF Mode 01 PIDs) vs extended mode (OEM-specific frames)
- Possibly: hardcoded list of CAN IDs monitored passively

> Actual findings (app identity, signal maps, binary decompile, all signal decodings) are in
> **`epri-decompile.md`**.

---

---

## Part 4 -- CAN Interrogation Tools

> Moved to `dtc-can-interrogation.md`.
