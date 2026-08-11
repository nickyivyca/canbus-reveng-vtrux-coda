# WiCAN Pro — SWCAN / GMLAN Single-Wire Logging

**Date:** 2026-04-26
**Goal:** Log the GM single-wire GMLAN bus (OBD pin 1, 33.333 kbps) using the WiCAN Pro

---

## Hardware

The WiCAN Pro has a dedicated secondary OBD chip connected to the ESP32 via UART (TX=GPIO2, RX=GPIO1, 4 Mbaud). This secondary chip handles legacy protocols including single-wire CAN (SWCAN/GMLAN), SAE J1850-PWM/VPW, K-line (ISO 9141, ISO 14230). The README feature table correctly marks "Single Wire CAN GMLAN (PIN 1) ✅ (WiCAN Pro only)". The hardware capability is real.

The secondary chip supports ELM329 v2.2 and STN instruction sets, which include SWCAN protocol selection.

## Current Firmware Limitation

As of firmware checked out 2026-04-22, **SWCAN is not accessible via the web UI or WiFi interface**. The web UI `can_mode` field only offers `normal` / `silent` (for the ESP32's own high-speed CAN controller). There is no bus-type selection exposed.

Root cause in the firmware source (`wican-fw` repo):

- `main.c` detects hardware variant at runtime from the project binary name. The Pro binary (`wican-fw_obd_pro_...`) does not match `"usb"` or `"hv210"`, so `project_hardware_rev` falls through to `WICAN_V300`.
- `wc_uart_init()` (which initializes the secondary chip's UART) is only called when `project_hardware_rev == WICAN_USB_V100` (`main.c:561`).
- The WiFi→UART routing path is also gated on `project_hardware_rev == WICAN_USB_V100` (`main.c:328`).
- The ESP32 ELM327 stack (`elm327.c`) only handles CAN protocols 6–9 (ISO 15765-4 at 500k/250k); SWCAN is not implemented there.

The secondary chip is powered and connected at the PCB level, but the firmware never sends it any data in the OBD Pro WiFi path.

## Next Steps

1. **Check for newer firmware releases** — the local repo may lag behind releases. Check [github.com/meatpiHQ/wican-fw/releases](https://github.com/meatpiHQ/wican-fw/releases) to see if a recent release wires up the Pro UART path.
2. **Ask on WiCAN Discord** — `https://discord.com/invite/2hpHVDmyfw` — whether SWCAN via WiFi is on the near-term roadmap, or if there's an alternate config trick.
3. **Alternative: USB serial** — The Pro's USB-C port may give direct access to the secondary OBD chip (the `WICAN_USB_V100` path). An ELM327 client connected via USB could issue SWCAN protocol commands (ELM329 `ATSP 7` or STN equivalent). Not confirmed — needs testing.
4. **Alternative: custom firmware build** — Enabling the Pro UART path would require changing the runtime hardware detection in `main.c` so `obd_pro` project names are handled as their own variant (not `WICAN_V300`), then routing WiFi→UART for that rev. The GPIO definitions are already correct in `hw_config.h`.

## Vtrux Context

The Vtrux GMLAN single-wire bus (OBD pin 1) is the native bus for the TCCM (transfer case) and potentially other chassis modules not present on the OBD-II bus. Current captures only see these modules when VCM re-broadcasts their frames onto the main bus. Direct SWCAN capture would eliminate that filter and show raw module traffic including any frames VCM does not forward.
