import sys, re, struct
sys.path.insert(0, ".")
import cantools
from canre.parsers import parse_file

BASE = "<home>/<drive-root>/<library>/My Libraries/CANLogs/VtruxLogs/"
LOG_FILES = sorted(
    [BASE + f"vtrux_20260503_192242_T{n}.log" for n in range(32)],
    key=lambda p: int(re.search(r'_T(\d+)\.log', p).group(1))
)

CHUNK_DURATION = 300.0

def chunk_offset(path):
    m = re.search(r'_T(\d+)\.log', path)
    return int(m.group(1)) * CHUNK_DURATION if m else 0.0

db = cantools.database.load_file("projects/vtrux/epri-pt-bus.dbc")

def decode_bel_d7(data):
    hv_v = struct.unpack_from("<h", data, 0)[0] * 0.05
    hv_i = struct.unpack_from("<h", data, 2)[0] * 0.05
    ac_v = struct.unpack_from("<h", data, 4)[0] * 0.05
    ac_i = struct.unpack_from("<h", data, 6)[0] * 0.05
    return hv_v, hv_i, ac_v, ac_i

def decode_bel_d9(data):
    max_cur = struct.unpack_from("<h", data, 0)[0] * 0.05
    veh_state = data[2]
    return max_cur, veh_state

first_offset = 0.0

for log_path in LOG_FILES:
    offset = chunk_offset(log_path) - first_offset
    name = log_path.split("/")[-1]
    print(f"\n{'='*70}")
    print(f"CHUNK: {name}  (session-relative: t={offset:.0f}s - {offset+300:.0f}s)")
    print(f"{'='*70}")

    vmax_vals = []
    vmin_vals = []
    hvi_vals = []
    hvv_vals = []
    maxcur_vals = []
    chgmax_vals = []
    cell_ov_seen = False
    bal_active_seen = False
    bal_cnt_vals = []
    soc_vals = []
    b2_412_vals = []

    frames = list(parse_file(log_path))
    t0 = frames[0].timestamp

    for frame in frames:
        t_local = frame.timestamp - t0
        arb = frame.arbitration_id
        data = bytes(frame.data)
        t_abs = offset + t_local

        if arb == 0x430:
            try:
                dec = db.decode_message(0x430, data)
                vmax_vals.append(dec["bcm_cell_vmax"])
                vmin_vals.append(dec["bcm_cell_vmin"])
            except Exception:
                pass

        elif arb == 0x420:
            try:
                dec = db.decode_message(0x420, data)
                chgmax_vals.append(dec["bcm_chg_max"])
                if dec["bcm_cell_overvolt"]:
                    cell_ov_seen = True
            except Exception:
                pass

        elif arb == 0x18FFD7C0:
            try:
                hv_v, hv_i, ac_v, ac_i = decode_bel_d7(data)
                hvi_vals.append(hv_i)
                hvv_vals.append(hv_v)
            except Exception:
                pass

        elif arb == 0x440:
            try:
                dec = db.decode_message(0x440, data)
                if dec.get("bcm_balancing"):
                    bal_active_seen = True
                bal_cnt_vals.append(int(dec.get("bcm_balancing_cnt", 0)))
            except Exception:
                pass

        elif arb == 0x411:
            if len(data) >= 2:
                soc = (data[0] * 64 + (data[1] >> 2)) / 100.0
                soc_vals.append(soc)

        elif arb == 0x412:
            if len(data) >= 3:
                b2_412_vals.append(data[2])

        elif arb == 0x18FFD9C0:
            try:
                max_cur, _ = decode_bel_d9(data)
                maxcur_vals.append(max_cur)
            except Exception:
                pass

    if vmax_vals:
        spreads = [(mx - mn) * 1000 for mx, mn in zip(vmax_vals, vmin_vals)]
        print(f"  cell_vmax:  min={min(vmax_vals):.3f}V  max={max(vmax_vals):.3f}V  mean={sum(vmax_vals)/len(vmax_vals):.3f}V")
        print(f"  cell_vmin:  min={min(vmin_vals):.3f}V  max={max(vmin_vals):.3f}V  mean={sum(vmin_vals)/len(vmin_vals):.3f}V")
        print(f"  spread(mV): min={min(spreads):.1f}  max={max(spreads):.1f}  mean={sum(spreads)/len(spreads):.1f}")
        print(f"  cell_OV ever set: {cell_ov_seen}")
    else:
        print("  (no 0x430 frames)")

    if bal_cnt_vals:
        print(f"  bal_active ever:  {bal_active_seen}")
        print(f"  bal_cnt:    min={min(bal_cnt_vals)}  max={max(bal_cnt_vals)}  final={bal_cnt_vals[-1]}")
    else:
        print("  (no 0x440 frames)")

    if soc_vals:
        print(f"  SoC(0x411): first={soc_vals[0]:.1f}%  last={soc_vals[-1]:.1f}%  min={min(soc_vals):.1f}%  max={max(soc_vals):.1f}%")
    else:
        print("  (no 0x411 frames)")

    if chgmax_vals:
        print(f"  chg_max:    min={min(chgmax_vals):.1f}A  max={max(chgmax_vals):.1f}A  mean={sum(chgmax_vals)/len(chgmax_vals):.1f}A")
    else:
        print("  (no 0x420 frames)")

    if b2_412_vals:
        print(f"  0x412 B2:   first={b2_412_vals[0]}  last={b2_412_vals[-1]}  min={min(b2_412_vals)}  max={max(b2_412_vals)}")
    else:
        print("  (no 0x412 frames)")

    if hvi_vals:
        print(f"  hvI(A):     min={min(hvi_vals):.2f}  max={max(hvi_vals):.2f}  mean={sum(hvi_vals)/len(hvi_vals):.2f}")
        print(f"  hvV(V):     min={min(hvv_vals):.1f}  max={max(hvv_vals):.1f}  mean={sum(hvv_vals)/len(hvv_vals):.1f}")
    else:
        print("  (no 0x18FFD7C0 frames)")

    if maxcur_vals:
        print(f"  maxAvailCur:min={min(maxcur_vals):.1f}A  max={max(maxcur_vals):.1f}A  mean={sum(maxcur_vals)/len(maxcur_vals):.1f}A")

    print()
    print(f"  --- Cell spread samples every 30s (first 10 and last 5) ---")
    if vmax_vals:
        fps = 10
        n = len(vmax_vals)
        step = max(1, n // (300 // 1))
        rows = []
        for i in range(0, n, step):
            frac = i / n
            t_in_chunk = frac * 300.0
            t_session = offset + t_in_chunk
            rows.append((t_session, vmax_vals[i], vmin_vals[i], (vmax_vals[i]-vmin_vals[i])*1000))
        sample_30s = []
        prev_t = -30
        for row in rows:
            if row[0] - prev_t >= 30:
                sample_30s.append(row)
                prev_t = row[0]
        show = sample_30s[:10] + (["..."] if len(sample_30s) > 15 else []) + sample_30s[-5:]
        for item in show:
            if item == "...":
                print(f"    ...")
                continue
            t_s, vm, vn, sp = item
            print(f"    t={t_s:6.0f}s  vmax={vm:.3f}V  vmin={vn:.3f}V  spread={sp:.1f}mV")

    if hvi_vals:
        print()
        print(f"  --- hvI samples every 30s ---")
        n = len(hvi_vals)
        step = max(1, n // (300 // 1))
        rows = []
        for i in range(0, n, step):
            frac = i / n
            t_session = offset + frac * 300.0
            rows.append((t_session, hvi_vals[i], hvv_vals[i]))
        sample_30s = []
        prev_t = -30
        for row in rows:
            if row[0] - prev_t >= 30:
                sample_30s.append(row)
                prev_t = row[0]
        for t_s, hvi, hvv in sample_30s:
            print(f"    t={t_s:6.0f}s  hvI={hvi:.2f}A  hvV={hvv:.1f}V")
