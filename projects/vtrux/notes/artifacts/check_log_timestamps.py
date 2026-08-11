import os
import re
import datetime

def parse_header_date(fpath):
    with open(fpath, "r", encoding="latin-1") as f:
        for line in f:
            m = re.match(r"\*\*\*START DATE AND TIME (\d+):(\d+):(\d+) (\d+):(\d+):(\d+)", line)
            if m:
                day, mon, yr, hh, mm, ss = [int(x) for x in m.groups()]
                return datetime.datetime(yr, mon, day, hh, mm, ss)
            if not line.startswith("*"):
                break
    return None

def get_last_ts(fpath):
    last = None
    with open(fpath, "r", encoding="latin-1") as f:
        for line in f:
            if line.startswith("*") or not line.strip():
                continue
            parts = line.split()
            if len(parts) < 3:
                continue
            ts = parts[0]
            if re.match(r"[\d-]+:[\d-]+:[\d-]+:[\d-]+", ts):
                last = ts
    return last

LOG_DIR = "projects/vtrux/logs"

files = []
for fname in sorted(os.listdir(LOG_DIR)):
    if fname.endswith(".log"):
        files.append(os.path.join(LOG_DIR, fname))

print(f"{'File':<55} {'Header date':<22} {'Last ts':<18} {'Size MB'}")
print("-" * 105)

for fpath in files:
    fname = os.path.basename(fpath)
    try:
        size_mb = os.path.getsize(fpath) / (1024*1024)
        hdr = parse_header_date(fpath)
        hdr_str = hdr.strftime("%Y-%m-%d %H:%M") if hdr else "N/A"
        last = get_last_ts(fpath)
        print(f"{fname:<55} {hdr_str:<22} {str(last):<18} {size_mb:.1f}")
    except Exception as e:
        print(f"{fname:<55} ERROR: {e}")
