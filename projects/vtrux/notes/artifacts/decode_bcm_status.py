"""Decode 0x0410 BCM_Status bit fields and show transitions + failure window.

CAN B0: bit0=bcm_ready, bit1=bcm_epo, bit2=bcm_on_plug, bit3=bcm_hvil_mon,
        bits[5:4]=bcm_mainc_stat, bits[7:6]=bcm_chgc_stat
CAN B1: bits[7:6]=bcm_alarm, bit4=bcm_cpwr_cmd
CAN B2|B1[3:0]: bcm_ibat (12-bit, scale TBD)
CAN B3: bcm_soc (raw, scale TBD)
CAN B4,B5: bcm_gfd BE16 * 0.025 - 1000
CAN B6: bit4=bcm_chg_done, bit5=bcm_cool_req
CAN B7|B6[3:0]: bcm_vbat (12-bit, scale TBD)
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

LOG = r"projects\vtrux\logs\full charge then fail.log"

import re

def parse_ts(ts):
    h, m, s, t = ts.split(':')
    return int(h)*3600 + int(m)*60 + int(s) + int(t)*0.0001

def decode_b0(b):
    ready       = (b & 0x01) != 0
    epo         = (b & 0x02) != 0
    on_plug     = (b & 0x04) != 0
    hvil_mon    = (b & 0x08) != 0
    mainc_stat  = (b >> 4) & 0x3
    chgc_stat   = (b >> 6) & 0x3
    return ready, epo, on_plug, hvil_mon, mainc_stat, chgc_stat

def decode_b1(b):
    cpwr_cmd = (b & 0x10) != 0
    alarm    = (b >> 6) & 0x3
    return cpwr_cmd, alarm

def decode(data):
    b = data
    ready, epo, on_plug, hvil_mon, mainc_stat, chgc_stat = decode_b0(b[0])
    cpwr_cmd, alarm = decode_b1(b[1])
    ibat_raw = b[2] | ((b[1] & 0x0F) << 8)
    soc_raw  = b[3]
    gfd_raw  = (b[4] << 8) | b[5]
    gfd      = gfd_raw * 0.025 - 1000.0 if (gfd_raw & 0xFFFE) != 0xFFFE else None
    chg_done = (b[6] & 0x10) != 0
    cool_req = (b[6] & 0x20) != 0
    vbat_raw = b[7] | ((b[6] & 0x0F) << 8)
    return {
        'ready': ready, 'epo': epo, 'on_plug': on_plug, 'hvil_mon': hvil_mon,
        'mainc_stat': mainc_stat, 'chgc_stat': chgc_stat,
        'cpwr_cmd': cpwr_cmd, 'alarm': alarm,
        'ibat_raw': ibat_raw, 'soc_raw': soc_raw, 'gfd': gfd,
        'chg_done': chg_done, 'cool_req': cool_req, 'vbat_raw': vbat_raw
    }

def state_str(d):
    return (f"ready={int(d['ready'])} epo={int(d['epo'])} plug={int(d['on_plug'])} "
            f"hvil={int(d['hvil_mon'])} mainc={d['mainc_stat']} chgc={d['chgc_stat']} "
            f"alarm={d['alarm']} cpwr={int(d['cpwr_cmd'])} "
            f"chg_done={int(d['chg_done'])} cool={int(d['cool_req'])} "
            f"soc={d['soc_raw']:3d} ibat={d['ibat_raw']:4d} vbat={d['vbat_raw']:4d} "
            f"gfd={d['gfd']:.1f}" if d['gfd'] is not None else
            f"ready={int(d['ready'])} epo={int(d['epo'])} plug={int(d['on_plug'])} "
            f"hvil={int(d['hvil_mon'])} mainc={d['mainc_stat']} chgc={d['chgc_stat']} "
            f"alarm={d['alarm']} cpwr={int(d['cpwr_cmd'])} "
            f"chg_done={int(d['chg_done'])} cool={int(d['cool_req'])} "
            f"soc={d['soc_raw']:3d} ibat={d['ibat_raw']:4d} vbat={d['vbat_raw']:4d} "
            f"gfd=INVALID")

pat = re.compile(r'^(\d+:\d+:\d+:\d+)\s+\w+\s+\d+\s+0x0?410\s+\w+\s+8\s+(.+)$')

frames = []
with open(LOG, encoding='latin-1') as f:
    for line in f:
        m = pat.match(line.strip())
        if not m:
            continue
        ts = parse_ts(m.group(1))
        hexbytes = m.group(2).split()
        if len(hexbytes) < 8:
            continue
        data = [int(x, 16) for x in hexbytes[:8]]
        frames.append((ts, data))

print(f"Total 0x0410 frames: {len(frames)}")
print(f"Time span: {frames[0][0]:.1f}s - {frames[-1][0]:.1f}s\n")

# Show all state transitions
print("=== State transitions (0x0410 bit fields) ===")
prev = None
transitions = []
for ts, data in frames:
    d = decode(data)
    # Key: boolean/indexed fields only (not analog)
    key = (d['ready'], d['epo'], d['on_plug'], d['hvil_mon'],
           d['mainc_stat'], d['chgc_stat'], d['alarm'],
           d['cpwr_cmd'], d['chg_done'], d['cool_req'])
    if key != prev:
        transitions.append((ts, data, d))
        prev = key

for ts, raw, d in transitions:
    raw_hex = ' '.join(f'{b:02X}' for b in raw)
    print(f"  t={ts:7.1f}s  [{raw_hex}]  {state_str(d)}")

# Show last 30 seconds in detail
print(f"\n=== Last 30 seconds (t >= {frames[-1][0]-30:.1f}s) ===")
print(f"{'time':>9}  {'soc':>4}  {'ibat':>6}  {'vbat':>6}  {'gfd':>8}  ready epo plug hvil mainc chgc alarm cpwr done cool")
cutoff = frames[-1][0] - 30
last_soc = None
for ts, data in frames:
    if ts < cutoff:
        continue
    d = decode(data)
    gfd_str = f"{d['gfd']:8.2f}" if d['gfd'] is not None else "   INVAL"
    # only print if something changed or every 5th frame
    print(f"  {ts:7.1f}s  {d['soc_raw']:4d}  {d['ibat_raw']:6d}  {d['vbat_raw']:6d}  {gfd_str}"
          f"  {int(d['ready'])}     {int(d['epo'])}    {int(d['on_plug'])}    {int(d['hvil_mon'])}"
          f"    {d['mainc_stat']}     {d['chgc_stat']}     {d['alarm']}     {int(d['cpwr_cmd'])}"
          f"    {int(d['chg_done'])}    {int(d['cool_req'])}")
