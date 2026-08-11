import os

LOGS = [
    ("interlock test 1", ["projects/vtrux/logs/vtruxinterlocktest.log"]),
    ("interlock test 2", ["projects/vtrux/logs/vtruxinterlocktest2.log"]),
    ("isolation fault",  ["projects/vtrux/logs/vtruxisolationtest.log"]),
]

def ts_to_sec(ts):
    parts = ts.split(":")
    if len(parts) == 4:
        try:
            h, m, s, t = parts
            return int(h)*3600 + int(m)*60 + int(s) + int(t)/10000.0
        except ValueError:
            return None
    return None

for label, files in LOGS:
    print(f"\n{'='*60}")
    print(f"{label}")
    print(f"{'='*60}")

    events = []
    for fpath in files:
        with open(fpath, "r", encoding="latin-1") as f:
            for line in f:
                if line.startswith("*") or not line.strip():
                    continue
                parts = line.split()
                if len(parts) < 6:
                    continue
                if parts[4] != "s":
                    continue
                sec = ts_to_sec(parts[0])
                if sec is None:
                    continue
                try:
                    data = [int(x, 16) for x in parts[6:]]
                except ValueError:
                    continue
                cid = parts[3]
                if cid == "0x400" and len(data) >= 1:
                    events.append((sec, parts[0], "0x400", f"B0=0x{data[0]:02X} epo={(data[0]>>1)&1}"))
                elif cid == "0x410" and len(data) >= 2:
                    hvil = (data[0] >> 3) & 1
                    events.append((sec, parts[0], "0x410", f"B0=0x{data[0]:02X}(hvil={hvil}) B1=0x{data[1]:02X}"))

    events.sort(key=lambda x: x[0])

    prev_400_b0 = None
    prev_410_b0 = None
    prev_410_b1 = None
    fault_start = None

    for sec, ts, cid, desc in events:
        if cid == "0x400":
            b0 = int(desc.split("B0=0x")[1].split()[0], 16)
            epo = (b0 >> 1) & 1
            if b0 != prev_400_b0:
                if fault_start is None and epo == 1:
                    fault_start = sec
                rel = f"  [{sec - fault_start:+.4f}s]" if fault_start is not None else ""
                print(f"  {ts}  0x400  {desc}{rel}")
                prev_400_b0 = b0
        elif cid == "0x410":
            b0_raw = int(desc.split("B0=0x")[1].split("(")[0], 16)
            b1 = int(desc.split("B1=0x")[1], 16)
            hvil = (b0_raw >> 3) & 1
            changed = (b0_raw != prev_410_b0) or (b1 != prev_410_b1)
            if changed:
                rel = f"  [{sec - fault_start:+.4f}s]" if fault_start is not None else ""
                print(f"  {ts}  0x410  {desc}{rel}")
                prev_410_b0 = b0_raw
                prev_410_b1 = b1
