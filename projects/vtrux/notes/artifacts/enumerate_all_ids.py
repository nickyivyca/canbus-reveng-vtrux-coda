"""
Systematic pass through ghidra-gopoint-decompiled.txt.
For every if (uVarN == 0x...) / if (uVarN != 0x...) guard, extract the ID and
the next ~20 lines of context to surface format strings and signal names.
"""

DECOMPILE = 'projects/vtrux/notes/artifacts/ghidra-gopoint-decompiled.txt'

import re

with open(DECOMPILE, encoding='utf-8', errors='replace') as f:
    lines = f.readlines()

# Pattern: if (uVarN == 0xHEX) or if (uVarN != 0xHEX)
GUARD = re.compile(r'if \((\w+) ([!=]=) (0x[0-9a-fA-F]+)\)')

# cfstring name pattern (Ghidra names like &cf_... or PTR_s_...__...)
CFSTR = re.compile(r'&cf_([^\s,;)]+)|PTR_s_([^\s_]+)')

hits = []  # (line_num, var, op, id_hex, context_lines)

for i, line in enumerate(lines):
    m = GUARD.search(line)
    if m:
        var, op, id_hex = m.group(1), m.group(2), m.group(3)
        # Only care about CAN ID variables (uVar2, uVar59, uVar3)
        if var not in ('uVar2', 'uVar59', 'uVar3'):
            continue
        # Gather next 25 lines as context
        ctx = lines[i:i+25]
        hits.append((i+1, var, op, id_hex, ctx))

# Group by variable (= bus/context)
VAR_LABEL = {
    'uVar3':  'handleGoPointMessage_ (GoPoint protocol)',
    'uVar2':  'parseEPRIMessage_ (VIA CAN bus IDs)',
    'uVar59': 'parseEPRIMessage_ (GoPoint / extended CAN IDs)',
}

from collections import defaultdict
by_var = defaultdict(list)
for h in hits:
    by_var[h[1]].append(h)

# Helper: pull format-string clues out of context
def extract_clues(ctx_lines):
    clues = []
    for ln in ctx_lines:
        # Format string cfstring names
        for m in CFSTR.finditer(ln):
            name = m.group(1) or m.group(2)
            if name and len(name) > 2 and 'OBJC' not in name and 'CLASS' not in name:
                clues.append(name)
        # Explicit format string literals visible as cf_ names with underscores-as-spaces
    # Deduplicate while preserving order
    seen = set()
    out = []
    for c in clues:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out[:6]  # keep top 6 clues

print('=' * 70)
print('COMPLETE CAN ID INVENTORY -- ghidra-gopoint-decompiled.txt')
print('=' * 70)

for var in ('uVar3', 'uVar2', 'uVar59'):
    entries = by_var.get(var, [])
    if not entries:
        continue
    print()
    print(f'--- {VAR_LABEL[var]} ---')
    print()
    for (lineno, v, op, id_hex, ctx) in entries:
        clues = extract_clues(ctx)
        clue_str = '  signals: ' + ', '.join(clues) if clues else ''
        print(f'  line {lineno:4d}:  {id_hex}  ({op})  {clue_str}')

print()
print('=' * 70)
print(f'Total guards found: {len(hits)}')
ids_uvar2  = sorted(set(int(h[3],16) for h in hits if h[1]=='uVar2'))
ids_uvar59 = sorted(set(int(h[3],16) for h in hits if h[1]=='uVar59'))
ids_uvar3  = sorted(set(int(h[3],16) for h in hits if h[1]=='uVar3'))
print(f'  uVar3  (GoPoint protocol): {len(ids_uvar3)} unique IDs: ' +
      ', '.join(f'0x{x:X}' for x in ids_uvar3))
print(f'  uVar2  (VIA CAN):          {len(ids_uvar2)} unique IDs: ' +
      ', '.join(f'0x{x:X}' for x in ids_uvar2))
print(f'  uVar59 (GoPoint/extended): {len(ids_uvar59)} unique IDs: ' +
      ', '.join(f'0x{x:X}' for x in ids_uvar59))
