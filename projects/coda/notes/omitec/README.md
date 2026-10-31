# Omitec diagnostic handset -- USB interface investigation

Opened 2026-09-26. Goal: learn to talk to the Omitec handset (the Coda dealer scan
tool) over its USB port. No Omitec PC software is available, so everything here is
learned from the device itself.

> **STATUS: DEAD END. Closed 2026-09-26 by owner decision, same day.** Stopped after
> the idle echo test got no response. Never tried: replying inside the boot
> window, any frame other than the handset's own boot frame echoed back, and
> reading the MCU or NOR flash directly. Anyone reopening this should start from
> "Open questions" below. The safety contract still applies.

## Files

| File | What |
|------|------|
| `artifacts/omitec_usb_passive_probe.py` | Receive-only probe: FTDI EEPROM dump, modem-status poll, RX-only baud sweep. |
| `artifacts/omitec_usb_listener.py` | Receive-only event listener; survives USB replug; default 3 Mbaud activity-detector mode. |
| `artifacts/omitec_usb_send.py` | **The only script here that transmits to the handset.** Sends the exact `--hex` byte strings given, with listen windows before and after; still never touches DTR/RTS. |
| `artifacts/send_echo_idle_20260926.log` | First transmission: 7-byte and 6-byte echoes of the boot frame, sent to the idle handset. |
| `artifacts/passive_probe_20260926.log` | Output of the first probe run (handset on, idle at its normal screen). |
| `artifacts/listen_3M_20260926.log` | 3 Mbaud activity-detector listen across one USB replug (first sighting of the boot transmission). |
| `artifacts/listen_baudstep_20260926.log` | Seven replugs, one baud rate each (9600, 19200, 38400, 57600, 115200, 4800, 2400). |
| `artifacts/listen_38400_repeat_20260926.log` | Repeat boots captured at 38400 only (repeatability check). |

Python: a local venv at `~/.venvs/omitec` on `the Linux box` (pyusb, pyftdi,
pyserial) -- deliberately outside the Seafile library. Device access needs the udev
rule `/etc/udev/rules.d/99-omitec.rules` (1258:0009 -> group `plugdev`, mode 0660).
The rule grants access only; it does not bind a kernel driver.

## Safety contract for all tooling here

The FT232's DTR/RTS outputs may be wired to the main MCU's reset or boot-mode pins
(common in field-updatable designs; not verified on this board). On Renesas H8 flash
parts, boot mode erases the on-chip flash before accepting a new program. A normal
Linux `ttyUSB` open asserts DTR/RTS, so this investigation does **not** use
`ftdi_sio`. All access is raw libusb, where every request is explicit. The scripts
never send `SIO_SET_MODEM_CTRL`, `SIO_RESET`, EEPROM writes, or bulk-OUT data.
Anything that transmits toward the MCU is a separate, explicitly approved step.

## Findings

### USB bridge (2026-09-26)

- USB ID `1258:0009`, manufacturer "Omitec", product "Diagnostic Handset".
  `bcdDevice 0x0400` = FTDI FT232BM/BL, matching the FTDI232BL on the board.
- One vendor-specific interface, bulk EP `0x81` IN / `0x02` OUT, 64 bytes, full
  speed, bus-powered 90 mA: the stock FT232B layout.
- 93C46 config EEPROM read out, checksum valid. It holds only the custom
  VID/PID/strings; the config byte is `0x18` (use-serial + USB-version override).
  Because of the custom VID, Linux's `ftdi_sio` does not auto-bind, which is why no
  serial port ever appeared.
- **Conclusion: the USB port is a plain UART bridge.** The protocol belongs to the
  handset's MCU firmware, not to the USB layer.

### Bench setup (2026-09-26)

In this bench setup the handset is **powered from USB alone**: plugging in the USB
boots it, unplugging turns it off. Every USB replug is therefore a full MCU
power-on, not just a USB re-enumeration. Three LEDs: red (always on while powered),
green, and a third one not yet characterised. The green LED blinks **twice** a
couple of seconds after each boot, the first blink slightly longer than the
second (operator observation; its timing against the serial bursts has not been
measured).
The handset's menu reports unit serial `00610`, which differs from the FTDI's USB
serial string (`OM318431`). Its only menu item that looks PC-related is "show
security key" (a 4x5-character code; value not recorded here, see Open questions).

### Idle behaviour (2026-09-26, handset on at its normal ready-to-connect screen)

- Modem inputs CTS/DSR/RI/DCD all read inactive.
- RX-only listen, 4 s at each of 9600 ... 1 Mbaud (13 rates): **zero bytes and zero
  line errors at every rate.** A wrong baud would still produce bytes with framing
  errors, so zero bytes at every rate means the MCU never drove the FTDI RXD line.
  The handset is silent on this port while idle.

### Boot-time transmission (2026-09-26)

The handset **does** transmit on this port, but only just after power-up:

- About **3.4 s after USB connect** (i.e. after power-on), it sends **4 identical
  bursts about 262 ms apart**, then a 5th event about 262 ms later, then nothing
  further. The same pattern appeared on all 12 boots captured (1 at 3 Mbaud,
  7 in the baud step, 4 in the 38400 repeat run).
- **Serial format: 38400 baud, 8N1.** Of the rates tried against a boot (9600,
  19200, 38400, 57600, 115200, 4800, 2400, plus 3 Mbaud), 38400 is the only rate
  down to 9600 that decoded with no line errors, and it gave the same bytes in all
  4 bursts. 19200/57600/115200 gave framing errors or breaks, but the same garbage
  in each of their 4 bursts, which is what one repeated frame looks like read at the
  wrong rate. 4800/2400 gave no errors but are too slow to resolve the bytes.
  No parity bit: under 8N1 reception, even parity would put a 0 in the stop-bit
  slot after `00` and odd parity would after `07`, so either would raise framing
  errors. None occurred.
- **Each of the 4 bursts is these 7 bytes:**
  ```
  07 00 10 50 00 67 00
  ```
- **Repeatability (5 boots at 38400, 20 bursts): byte-identical every time.**
  First burst 3.41-3.45 s after USB connect (includes enumeration time); burst
  spacing 261-263 ms.
- **The trailing `00` is separated in time.** The first six bytes
  (`07 00 10 50 00 67`) arrive back-to-back, but the final `00` arrives about
  4-6 ms after the `67` in every burst. One byte at 38400 takes 0.26 ms, so this is
  a real pause on the line, not the next byte in a stream. Host timestamps are
  quantised by the FTDI's 2 ms latency timer, so the pause is only known to within
  about 2 ms. Whether that `00` belongs to the frame is open.
- **The 5th event is not a frame.** At 38400 it reads as a break (RXD held low
  longer than a character time) followed by one `00`.
- During all of this, the modem inputs CTS/DSR/RI/DCD stayed inactive. DTR/RTS were
  never driven by the host.
- The protocol meaning of the frame is **not yet determined**. It is deliberately
  not interpreted here until more frames have been seen.

### First transmission: echo to the idle handset (2026-09-26 13:22)

Operator-approved. Handset idle at its normal screen, well after its boot window.
38400 8N1, DTR/RTS untouched. 2 s baseline, then:

| Sent | Response in the following 6 s |
|---|---|
| `07 00 10 50 00 67 00` (full 7-byte boot frame) | nothing: 0 bytes, no line errors, modem lines unchanged |
| `07 00 10 50 00 67` (first 6 bytes only) | nothing: 0 bytes, no line errors, modem lines unchanged |

On open, the FTDI RX buffer already held 54 `00` bytes received before the host
configured the port. The handset had been replugged shortly before, so these were
received at whatever rate the FT232 defaults to on power-up. Their origin is not
established: the 9600 capture of the boot frames looked different (`b1 fa fe`).
The baseline window after that was silent.

## Board chip list (operator's markings, 2026-09-26)

ADM202EA (RS-232 transceiver); NXP SJA1000T (CAN controller); FTDI FT232BL (USB);
M6636B OKI; 64F33377H16V (main MCU -- **hypothesis:** a Renesas/Hitachi H8 flash
part, exact part unconfirmed); 2x Altera MAX EPM3064ATC100 CPLD; 8x M29W320DT
(4 MB NOR each, 32 MB total -- **hypothesis:** vehicle application/database
storage); ISSI IS61C256AL (32 KB SRAM); ALVC164245 (level translator); CBT3384 (bus
switch); 74HCT00; plus several unidentified small parts (HT08, MCT32, S21B, AQ8C,
A570A).

## Open questions / next steps

- What does the handset do if the host answers during the boot window? This needs
  the first host->handset transmission, and each one must be approved separately.
- Is the green LED's start-up blink tied to the boot transmission window?
- The handset has a "show security key" menu item that displays a 4x5-character
  code. **Hypothesis:** it is a per-unit licence/registration code for Omitec's PC
  update software. The value is deliberately not recorded here, because these notes
  are published.
