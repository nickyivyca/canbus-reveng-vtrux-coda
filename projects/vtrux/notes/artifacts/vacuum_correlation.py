import sys
sys.path.insert(0, ".")

from canre.parsers import parse_file
from canre.analysis.correlation import _pearson
from collections import defaultdict

LOG = "projects/vtrux/logs/movingaroundindriveway.log"
PT_BUS = 3
REF_ID = 0x592
REF_START = 4
REF_LEN = 2

print(f"Parsing {LOG}...")
frames = parse_file(LOG)
pt_frames = [f for f in frames if f.bus == PT_BUS]
print(f"PT bus frames: {len(pt_frames)}")

ref_series = []
ref_times = []
for f in pt_frames:
    if f.arbitration_id == REF_ID and len(f.data) >= REF_START + REF_LEN:
        val = int.from_bytes(f.data[REF_START:REF_START+REF_LEN], byteorder='little', signed=False)
        ref_series.append(val * 0.01)
        ref_times.append(f.timestamp)

print(f"Reference samples (brake pedal %): {len(ref_series)}")
if ref_series:
    print(f"  Range: {min(ref_series):.2f} - {max(ref_series):.2f} %")

id_data = defaultdict(lambda: defaultdict(list))
id_times = defaultdict(lambda: defaultdict(list))
for f in pt_frames:
    aid = f.arbitration_id
    if aid == REF_ID:
        continue
    ts = f.timestamp
    for bi, b in enumerate(f.data):
        id_data[aid][bi].append(b)
        id_times[aid][bi].append(ts)

brake_on = [r for r in ref_series if r > 1.0]
brake_off = [r for r in ref_series if r < 0.5]
print(f"Brake-on samples (>1%): {len(brake_on)}, brake-off (<0.5%): {len(brake_off)}")

def resample_to_ref(ref_t, ref_v, sig_t, sig_v):
    ri = 0
    si = 0
    nr = len(ref_t)
    ns = len(sig_t)
    a_r = []
    a_s = []
    max_dt = 0.05
    while ri < nr and si < ns:
        rt = ref_t[ri]
        st = sig_t[si]
        if abs(rt - st) <= max_dt:
            a_r.append(ref_v[ri])
            a_s.append(sig_v[si])
            ri += 1
            si += 1
        elif rt < st:
            ri += 1
        else:
            si += 1
    return a_r, a_s

results = []
for aid in sorted(id_data.keys()):
    for bi in sorted(id_data[aid].keys()):
        vals = id_data[aid][bi]
        times = id_times[aid][bi]
        if len(vals) < 50:
            continue
        if len(set(vals)) < 2:
            continue
        a_ref, a_sig = resample_to_ref(ref_times, ref_series, times, vals)
        if len(a_ref) < 20:
            continue
        r = _pearson(a_ref, a_sig)
        if r is not None and abs(r) > 0.3:
            results.append((abs(r), r, aid, bi, 8, "u8", len(a_ref), min(a_sig), max(a_sig)))

for aid in sorted(id_data.keys()):
    max_bi = max(id_data[aid].keys())
    for bi in range(0, max_bi):
        if bi not in id_data[aid] or (bi+1) not in id_data[aid]:
            continue
        vals0 = id_data[aid][bi]
        vals1 = id_data[aid][bi+1]
        times0 = id_times[aid][bi]
        n = min(len(vals0), len(vals1))
        if n < 50:
            continue

        combined_be = [(vals0[i] << 8) | vals1[i] for i in range(n)]
        a_ref, a_sig = resample_to_ref(ref_times, ref_series, times0[:n], combined_be)
        if len(a_ref) >= 20 and len(set(a_sig)) >= 3:
            r = _pearson(a_ref, a_sig)
            if r is not None and abs(r) > 0.3:
                results.append((abs(r), r, aid, bi, 16, "BE16", len(a_ref), min(a_sig), max(a_sig)))

        combined_le = [vals0[i] | (vals1[i] << 8) for i in range(n)]
        a_ref2, a_sig2 = resample_to_ref(ref_times, ref_series, times0[:n], combined_le)
        if len(a_ref2) >= 20 and len(set(a_sig2)) >= 3:
            r2 = _pearson(a_ref2, a_sig2)
            if r2 is not None and abs(r2) > 0.3:
                results.append((abs(r2), r2, aid, bi, 16, "LE16", len(a_ref2), min(a_sig2), max(a_sig2)))

results.sort(key=lambda x: x[0], reverse=True)

print(f"\nTop correlations vs brake pedal (0x592 B4-B5 LE):")
print(f"{'|r|':>6}  {'r':>7}  {'ID':>8}  {'Byte':>5}  {'Bits':>5}  {'Enc':>6}  {'N':>6}  {'Min':>8}  {'Max':>8}")
print("-" * 85)
for abs_r, r, aid, bi, bits, enc, n, vmin, vmax in results[:60]:
    if aid < 0x1000:
        id_str = f"0x{aid:03X}"
    else:
        id_str = f"0x{aid:08X}"
    print(f"{abs_r:6.4f}  {r:+7.4f}  {id_str:>8}  {bi:>5}  {bits:>5}  {enc:>6}  {n:>6}  {vmin:>8.1f}  {vmax:>8.1f}")

neg_results = [(abs_r, r, aid, bi, bits, enc, n, vmin, vmax) for abs_r, r, aid, bi, bits, enc, n, vmin, vmax in results if r < -0.5]
print(f"\nStrongly anti-correlated (r < -0.5): {len(neg_results)}")
for abs_r, r, aid, bi, bits, enc, n, vmin, vmax in neg_results[:30]:
    if aid < 0x1000:
        id_str = f"0x{aid:03X}"
    else:
        id_str = f"0x{aid:08X}"
    print(f"  {id_str} B{bi} {bits}-bit {enc} r={r:.4f} n={n} vals=[{vmin:.1f}, {vmax:.1f}]")
