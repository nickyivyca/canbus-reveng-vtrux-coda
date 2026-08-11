import sys
sys.path.insert(0, ".")
import cantools
from canre.parsers import parse_file

DBC = "projects/vtrux/epri-pt-bus.dbc"
LOGDIR = "../../CANLogs/VtruxLogs"
CHUNKS = [
    "vtrux_20260617_193900_T0.log",
    "vtrux_20260617_193900_T1.log",
    "vtrux_20260617_193900_T2.log",
]

db = cantools.database.load_file(DBC)
m_ibat = db.get_message_by_name("EPRI_BCM_Status_0410")      # bcm_ibat, bcm_soc
m_gene = db.get_message_by_name("EPRI_MCU_Cmd2_Response_0054")  # GENE_RotSpd
id_ibat = m_ibat.frame_id
id_gene = m_gene.frame_id

ibat_rows = []   # (t, ibat, soc, vbat?)
gene_rows = []   # (t, rpm)

for fn in CHUNKS:
    for fr in parse_file(f"{LOGDIR}/{fn}", absolute=True):
        aid = fr.arbitration_id
        if (aid & 0x7FF) == (id_ibat & 0x7FF):
            try:
                r = m_ibat.decode(fr.data, decode_choices=False, allow_truncated=True)
            except Exception:
                continue
            ib = r.get("bcm_ibat")
            soc = r.get("bcm_soc")
            ibat_rows.append((fr.timestamp, ib, soc))
        elif (aid & 0x7FF) == (id_gene & 0x7FF):
            try:
                r = m_gene.decode(fr.data, decode_choices=False, allow_truncated=True)
            except Exception:
                continue
            gene_rows.append((fr.timestamp, r.get("GENE_RotSpd")))

t0 = ibat_rows[0][0]
print(f"ibat samples: {len(ibat_rows)}  gene samples: {len(gene_rows)}")

ibs = [r[1] for r in ibat_rows if r[1] is not None]
print(f"\nbcm_ibat (A, neg=discharge pos=charge): min={min(ibs):.1f} max={max(ibs):.1f} mean={sum(ibs)/len(ibs):.1f}")
pos = sum(1 for x in ibs if x > 2)
neg = sum(1 for x in ibs if x < -2)
near0 = len(ibs) - pos - neg
print(f"  charging(>2A): {pos}  discharging(<-2A): {neg}  near-zero: {near0}")

rpms = [r[1] for r in gene_rows if r[1] is not None]
if rpms:
    print(f"\nGENE_RotSpd (rpm): min={min(rpms):.0f} max={max(rpms):.0f} mean={sum(rpms)/len(rpms):.0f}")
    running = sum(1 for x in rpms if x > 200)
    print(f"  generator running(>200rpm): {running} / {len(rpms)} samples")

print("\n=== timeline (~30s) ibat / soc / gene_rpm ===")
gi = 0
last = None
for t, ib, soc in ibat_rows:
    rel = t - t0
    if last is None or rel - last >= 30:
        while gi + 1 < len(gene_rows) and gene_rows[gi][0] < t:
            gi += 1
        rpm = gene_rows[gi][1] if gene_rows else None
        rpm_s = f"{rpm:.0f}" if rpm is not None else "na"
        print(f"  t={rel:7.1f}s  ibat={ib:8.1f}A  soc={soc}  gene_rpm={rpm_s}")
        last = rel
