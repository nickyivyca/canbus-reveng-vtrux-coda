import csv
rows = list(csv.DictReader(open('coolant_temp_part4.csv')))
peak = max(rows, key=lambda r: int(r['value']))
print(f"Peak: t={float(peak['timestamp']):.1f}s  raw={peak['value']}  degC={int(peak['value'])-40}")
prev_raw = None
for r in rows:
    raw = int(r['value'])
    if raw != prev_raw:
        print(f"  t={float(r['timestamp']):.1f}  raw={raw}  degC={raw-40}")
        prev_raw = raw
