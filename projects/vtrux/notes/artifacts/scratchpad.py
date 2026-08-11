"""
Vtrux scratchpad -- exploratory analysis phases.
Run from project root: py -3.12 projects/vtrux/notes/artifacts/scratchpad.py <phase>
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
from canre.parsers import parse_file

ROOT = os.path.join(os.path.dirname(__file__), '..', '..', '..', '..')


def phase_highpwr_encoding():
    """
    Verify GENE_HighPwr_Curr and GENE_HighPwr_Volt (0x0482) encoding.
    Checks that LE interpretation (B1|(B2&7)<<8 for volt, B3|(B4&0x3F)<<8 for curr)
    gives physically plausible HV bus values, vs the byte-swapped alternative.
    """
    log = os.path.join(ROOT, 'projects/vtrux/logs/oghighwaydrive.log')
    frames = list(parse_file(log))
    id482 = [f for f in frames if f.arbitration_id == 0x482]
    print(f'0x482 frames: {len(id482)}, log: {log}')
    print()

    sample_indices = [
        ('start',  10),
        ('quarter', len(id482) // 4),
        ('mid',    len(id482) // 2),
        ('3q',     3 * len(id482) // 4),
        ('end',    -1),
    ]
    print(f'{"label":8s}  {"t(s)":7s}  {"raw bytes":18s}  {"Volt-LE":8s}  {"Curr-LE":10s}  {"Volt-swap":10s}  {"Curr-swap":10s}')
    print('-' * 90)
    for label, idx in sample_indices:
        f = id482[idx]
        b = f.data
        # LE interpretation (what the DBC encodes)
        volt_le = b[1] | ((b[2] & 0x7) << 8)
        curr_raw_le = b[3] | ((b[4] & 0x3F) << 8)
        curr_le = curr_raw_le * 0.25 - 2048
        # Byte-swapped (Motorola) alternative
        volt_sw = b[2] | ((b[1] & 0x7) << 8)
        curr_raw_sw = b[4] | ((b[3] & 0x3F) << 8)
        curr_sw = curr_raw_sw * 0.25 - 2048
        print(f'{label:8s}  {f.timestamp:7.1f}  {b.hex():18s}  {volt_le:6d}V    {curr_le:+8.2f}A    {volt_sw:6d}V    {curr_sw:+8.2f}A')

    # Also print a 10-frame window from the middle for detail
    mid = len(id482) // 2
    print()
    print('10-frame window at mid-drive:')
    print(f'{"t(s)":7s}  {"raw":18s}  {"Volt-LE":8s}  {"Curr-LE":10s}')
    print('-' * 55)
    for f in id482[mid:mid+10]:
        b = f.data
        volt_le = b[1] | ((b[2] & 0x7) << 8)
        curr_raw_le = b[3] | ((b[4] & 0x3F) << 8)
        curr_le = curr_raw_le * 0.25 - 2048
        print(f'{f.timestamp:7.1f}  {b.hex():18s}  {volt_le:6d}V    {curr_le:+8.2f}A')


PHASES = {
    'highpwr_encoding': phase_highpwr_encoding,
}

if __name__ == '__main__':
    if len(sys.argv) < 2 or sys.argv[1] not in PHASES:
        print(f'Usage: py -3.12 projects/vtrux/scratchpad.py <phase>')
        print(f'Phases: {", ".join(PHASES)}')
        sys.exit(1)
    PHASES[sys.argv[1]]()
