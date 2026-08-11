import os
import re

LOG_DIR = "projects/vtrux/logs/actual-failed-charges"

results = []

for fname in sorted(os.listdir(LOG_DIR)):
    if not fname.endswith(".log"):
        continue
    fpath = os.path.join(LOG_DIR, fname)
    has_std = False
    has_bms = False
    has_ext = False
    line_count = 0
    try:
        with open(fpath, "r", encoding="latin-1") as f:
            for line in f:
                if line.startswith("*") or not line.strip():
                    continue
                parts = line.split()
                if len(parts) < 5:
                    continue
                frame_type = parts[4] if len(parts) > 4 else ""
                can_id_str = parts[3] if len(parts) > 3 else ""
                if frame_type == "s":
                    has_std = True
                    try:
                        cid = int(can_id_str, 16)
                        if 0x400 <= cid <= 0x507:
                            has_bms = True
                    except ValueError:
                        pass
                elif frame_type == "x":
                    has_ext = True
                line_count += 1
    except Exception as e:
        results.append((fname, "ERROR", str(e)))
        continue
    tag = []
    if has_bms:
        tag.append("BMS+ext" if has_ext else "BMS-only")
    elif has_std:
        tag.append("std-no-BMS" + ("+ext" if has_ext else ""))
    else:
        tag.append("ext-only")
    results.append((fname, ", ".join(tag), line_count))

print(f"{'File':<40} {'Type':<20} Lines")
print("-" * 70)
for r in results:
    if len(r) == 3:
        print(f"{r[0]:<40} {r[1]:<20} {r[2]}")
    else:
        print(f"{r[0]:<40} {r[1]:<20} {r[2]}")
