"""
Cross-reference bit-flip patterns from interlock test against charge failure
events to determine if they share a common fault response path.

Inputs (same directory):
  interlock-bit-catalog.json   -- HVAC pull + HVD pull events (3-bus capture)
  failedcharge-bit-catalog.json -- M0_b, M1_b, full-charge-then-fail events

Outputs:
  bit-flip-crossref.txt   -- human-readable report
  bit-flip-crossref.json  -- structured results

Algorithm:
  1. Load and normalize: filter to powertrain bus, standard frames, dt in [-0.5, +5.0]
  2. Build bit-flip sets per event: (id, byte) and (id, byte, bit, direction)
  3. Set comparison at byte level: universal, interlock-common, charge-common, etc.
  4. Cascade order comparison via Spearman rank correlation
  5. Value comparison: old->new byte transitions for shared positions
  6. Known signal annotation
"""

import json
import math
from collections import defaultdict, OrderedDict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent

# -- Configuration -----------------------------------------------------------

INTERLOCK_JSON = SCRIPT_DIR / "interlock-bit-catalog.json"
CHARGE_JSON = SCRIPT_DIR / "failedcharge-bit-catalog.json"

OUTPUT_TXT = SCRIPT_DIR / "bit-flip-crossref.txt"
OUTPUT_JSON = SCRIPT_DIR / "bit-flip-crossref.json"

DT_MIN = -0.5
DT_MAX = 5.0
ANALOG_THRESHOLD = 10
INTERLOCK_PT_BUS = 2

KNOWN_SIGNALS = {
    "0x050": "Generator/motor command",
    "0x053": "Generator/motor command",
    "0x390": "Charger-related (periodic)",
    "0x3FE": "DC-DC / LV system",
    "0x400": "HV system status",
    "0x410": "Contactor cmd/fault status",
    "0x411": "Contactor-related",
    "0x412": "Current measurement",
    "0x420": "Battery pack voltage",
    "0x430": "Voltage-related",
    "0x440": "Voltage-related (GMLAN cluster)",
    "0x460": "Post-contactor related",
    "0x505": "BMS/charger",
    "0x592": "BMS state",
    "0x595": "BMS state",
    "0x596": "SoC/BMS state",
    "0x597": "BMS temperature",
    "0x598": "Power/current bundle",
    "0x599": "BMS state",
    "0x600": "BMS/charger",
    "0x610": "BMS cluster",
    "0x611": "BMS cluster",
    "0x617": "BMS cluster",
    "0x625": "BMS cluster",
    "0x639": "Cell extremes",
    "0x63A": "Cell extremes",
    "0x63C": "Generator RPM / BMS",
    "0x63D": "Fault flags",
    "0x644": "BMS cluster",
    "0x646": "BMS cluster",
    "0x647": "BMS cluster",
    "0x648": "BMS cluster",
    "0x649": "BMS cluster",
    "0x651": "BMS cluster",
    "0x6A0": "BMS/system state",
}

EVENT_LABELS = OrderedDict([
    ("hvac_pull", "HVAC_Pull"),
    ("hvd_pull", "HVD_Pull"),
    ("m0b_failure", "M0_b"),
    ("m1b_failure", "M1_b"),
    ("full_charge_failure", "FullChg"),
])

INTERLOCK_EVENTS = {"hvac_pull", "hvd_pull"}
CHARGE_EVENTS = {"m0b_failure", "m1b_failure", "full_charge_failure"}


# -- Helpers -----------------------------------------------------------------

def is_standard_frame(id_str):
    """Standard CAN IDs are < 0x800 (11-bit)."""
    return int(id_str, 16) < 0x800


def normalize_id(id_str):
    """Normalize CAN ID to uppercase with 0x prefix."""
    val = int(id_str, 16)
    if val <= 0x7FF:
        return "0x{:03X}".format(val)
    return "0x{:08X}".format(val)


def spearman_rank(ranks1, ranks2):
    """Spearman rank correlation (no scipy needed)."""
    n = len(ranks1)
    if n < 3:
        return float("nan")
    d_sq = sum((r1 - r2) ** 2 for r1, r2 in zip(ranks1, ranks2))
    denom = n * (n * n - 1)
    if denom == 0:
        return float("nan")
    return 1.0 - (6.0 * d_sq) / denom


def assign_ranks(values):
    """Assign ranks to a list of values (1-based, average ties)."""
    indexed = sorted(enumerate(values), key=lambda x: x[1])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        j = i
        while j < len(indexed) and indexed[j][1] == indexed[i][1]:
            j += 1
        avg_rank = (i + j + 1) / 2.0
        for k in range(i, j):
            ranks[indexed[k][0]] = avg_rank
        i = j
    return ranks


def get_known_signal(id_str):
    """Return known signal annotation or empty string."""
    nid = normalize_id(id_str)
    return KNOWN_SIGNALS.get(nid, "")


# -- Load and filter events --------------------------------------------------

def load_interlock_events(path):
    """Load interlock catalog, filter to PT bus + standard frames + time window."""
    with open(path) as f:
        data = json.load(f)

    events = {}
    for event_key in ("hvac_pull", "hvd_pull"):
        edata = data["events"][event_key]
        t_ref = edata["t_first_fault_bit"]
        raw_changes = edata["changes"]

        filtered = []
        for c in raw_changes:
            if c["bus"] != INTERLOCK_PT_BUS:
                continue
            if not is_standard_frame(c["id"]):
                continue
            if not (DT_MIN <= c["dt"] <= DT_MAX):
                continue
            filtered.append({
                "t": c["t"],
                "dt": c["dt"],
                "id": normalize_id(c["id"]),
                "byte": c["byte"],
                "old_byte": c["old_byte"],
                "new_byte": c["new_byte"],
                "bits": c["bits"],
            })

        events[event_key] = {
            "t_ref": t_ref,
            "changes": filtered,
        }

    return events


def load_charge_events(path):
    """Load charge failure catalog, filter to standard frames + time window."""
    with open(path) as f:
        data = json.load(f)

    events = {}
    for event_key in ("m0b_failure", "m1b_failure", "full_charge_failure"):
        edata = data["log_events"][event_key]
        t_ref = edata["t_event"]
        raw_changes = edata["changes"]

        filtered = []
        for c in raw_changes:
            if c.get("is_extended", False):
                continue
            if not is_standard_frame(c["id"]):
                continue
            if not (DT_MIN <= c["dt"] <= DT_MAX):
                continue
            filtered.append({
                "t": c["t"],
                "dt": c["dt"],
                "id": normalize_id(c["id"]),
                "byte": c["byte"],
                "old_byte": c["old_byte"],
                "new_byte": c["new_byte"],
                "bits": c["bits"],
            })

        events[event_key] = {
            "t_ref": t_ref,
            "log_file": edata.get("log_file", ""),
            "detection_method": edata.get("detection_method", ""),
            "changes": filtered,
        }

    return events


# -- Build sets --------------------------------------------------------------

def build_event_sets(changes):
    """
    From a filtered change list, build byte_set, bit_set, analog_bytes,
    discrete_bytes, first_dt, transitions, and change_count.
    """
    idbyte_counts = defaultdict(int)
    for c in changes:
        idbyte_counts[(c["id"], c["byte"])] += 1

    analog_bytes = set()
    for key, count in idbyte_counts.items():
        if count > ANALOG_THRESHOLD:
            analog_bytes.add(key)

    byte_set = set()
    bit_set = set()
    first_dt = {}
    transitions = defaultdict(list)

    for c in changes:
        key = (c["id"], c["byte"])
        byte_set.add(key)
        if key not in first_dt or c["dt"] < first_dt[key]:
            first_dt[key] = c["dt"]
        transitions[key].append((c["old_byte"], c["new_byte"], c["dt"]))
        for b in c["bits"]:
            direction = "SET" if b["new"] == 1 else "CLEAR"
            bit_set.add((c["id"], c["byte"], b["bit"], direction))

    discrete_bytes = byte_set - analog_bytes

    return {
        "byte_set": byte_set,
        "bit_set": bit_set,
        "analog_bytes": analog_bytes,
        "discrete_bytes": discrete_bytes,
        "first_dt": first_dt,
        "transitions": transitions,
        "change_count": dict(idbyte_counts),
    }


# -- Set comparison -----------------------------------------------------------

def compute_set_categories(event_sets):
    """Compute universal, interlock_common, charge_common, etc."""
    il_sets = [event_sets[e]["discrete_bytes"] for e in sorted(INTERLOCK_EVENTS)]
    ch_sets = [event_sets[e]["discrete_bytes"] for e in sorted(CHARGE_EVENTS)]
    all_sets = [event_sets[e]["discrete_bytes"] for e in EVENT_LABELS]

    il_union = set().union(*il_sets)
    ch_union = set().union(*ch_sets)
    il_common = set.intersection(*il_sets) if il_sets else set()
    ch_common = set.intersection(*ch_sets) if ch_sets else set()
    universal = set.intersection(*all_sets) if all_sets else set()
    any_event = set().union(*all_sets)

    overlap = il_union & ch_union
    interlock_only = il_union - ch_union
    charge_only = ch_union - il_union

    return {
        "universal": universal,
        "interlock_common": il_common,
        "charge_common": ch_common,
        "interlock_only": interlock_only,
        "charge_only": charge_only,
        "overlap": overlap,
        "any_event": any_event,
    }


# -- Order comparison ---------------------------------------------------------

def compute_order_comparison(event_sets, overlap_set):
    """Compute Spearman rank correlations and cascade ordering."""
    if len(overlap_set) < 3:
        return {"correlations": {}, "cascade": []}

    overlap_list = sorted(overlap_set, key=lambda k: (k[0], k[1]))

    event_keys = list(EVENT_LABELS.keys())
    event_dts = {}
    for ek in event_keys:
        fdt = event_sets[ek]["first_dt"]
        event_dts[ek] = {pos: fdt.get(pos) for pos in overlap_list}

    hvac_dt = event_dts["hvac_pull"]
    overlap_list.sort(key=lambda pos: (
        hvac_dt.get(pos) if hvac_dt.get(pos) is not None else 999.0,
        pos[0], pos[1]
    ))

    correlations = {}
    for i, ek1 in enumerate(event_keys):
        for ek2 in event_keys[i+1:]:
            common_pos = []
            for pos in overlap_list:
                dt1 = event_dts[ek1].get(pos)
                dt2 = event_dts[ek2].get(pos)
                if dt1 is not None and dt2 is not None:
                    common_pos.append((pos, dt1, dt2))

            if len(common_pos) >= 3:
                vals1 = [x[1] for x in common_pos]
                vals2 = [x[2] for x in common_pos]
                ranks1 = assign_ranks(vals1)
                ranks2 = assign_ranks(vals2)
                r = spearman_rank(ranks1, ranks2)
            else:
                r = float("nan")

            label1 = EVENT_LABELS[ek1]
            label2 = EVENT_LABELS[ek2]
            correlations["{} vs {}".format(label1, label2)] = {
                "r": r,
                "n_shared": len(common_pos),
            }

    cascade = []
    for rank, pos in enumerate(overlap_list, 1):
        row = {"rank": rank, "id": pos[0], "byte": pos[1]}
        for ek in event_keys:
            dt_val = event_dts[ek].get(pos)
            row[EVENT_LABELS[ek]] = dt_val
        row["known_signal"] = get_known_signal(pos[0])
        cascade.append(row)

    return {"correlations": correlations, "cascade": cascade}


# -- Value comparison ---------------------------------------------------------

def compute_value_comparison(event_sets, overlap_set):
    """Compare actual byte transitions for overlapping positions."""
    results = []
    for pos in sorted(overlap_set, key=lambda k: (k[0], k[1])):
        entry = {"id": pos[0], "byte": pos[1], "events": {}}
        transitions_match = True
        ref_transition = None

        for ek in EVENT_LABELS:
            trans = event_sets[ek]["transitions"].get(pos, [])
            if not trans:
                entry["events"][EVENT_LABELS[ek]] = None
                continue
            trans_sorted = sorted(trans, key=lambda t: t[2])
            first = trans_sorted[0]
            entry["events"][EVENT_LABELS[ek]] = {
                "old": first[0],
                "new": first[1],
                "dt": first[2],
                "n_changes": len(trans),
            }
            this_trans = (first[0], first[1])
            if ref_transition is None:
                ref_transition = this_trans
            elif this_trans != ref_transition:
                transitions_match = False

        entry["transitions_match"] = transitions_match
        entry["known_signal"] = get_known_signal(pos[0])
        results.append(entry)

    return results


# -- Report generation -------------------------------------------------------

def format_txt_report(all_events, event_sets, categories, order_cmp, value_cmp):
    """Generate the human-readable text report."""
    lines = []
    W = lines.append

    W("BIT-FLIP CROSS-REFERENCE REPORT")
    W("=" * 70)
    W("")
    W("Events compared:")

    event_descriptions = {
        "hvac_pull": "HVAC Pull (interlock test)",
        "hvd_pull": "HVD Pull (interlock test)",
        "m0b_failure": "M0_b buckBoostFault (charge failure)",
        "m1b_failure": "M1_b buckBoostFault (charge failure)",
        "full_charge_failure": "Full charge then fail (charge failure)",
    }

    for i, ek in enumerate(EVENT_LABELS, 1):
        edata = all_events[ek]
        t_ref = edata["t_ref"]
        desc = event_descriptions[ek]
        n_raw = len(edata["changes"])
        n_discrete = len(event_sets[ek]["discrete_bytes"])
        n_analog = len(event_sets[ek]["analog_bytes"])
        W("  {}. {}, t_ref={:.3f}s".format(i, desc, t_ref))
        W("     {} changes in window -> {} discrete (id,byte) + {} analog".format(n_raw, n_discrete, n_analog))

    W("")
    W("Filter: dt in [{}, {}], standard frames only (id < 0x800),".format(DT_MIN, DT_MAX))
    W("        interlock filtered to bus {} (Powertrain)".format(INTERLOCK_PT_BUS))
    W("        analog threshold: >{} changes per (id,byte) in window".format(ANALOG_THRESHOLD))

    def format_transition(evsets, pos, ek):
        trans = evsets[ek]["transitions"].get(pos, [])
        if not trans:
            return "---"
        trans_sorted = sorted(trans, key=lambda t: t[2])
        first = trans_sorted[0]
        return "{}->{}".format(first[0], first[1])

    def print_set_table(title, pos_set, evsets):
        W("")
        W("{} ({} positions):".format(title, len(pos_set)))
        if not pos_set:
            W("  (none)")
            return
        sorted_pos = sorted(pos_set, key=lambda k: (k[0], k[1]))
        labels = list(EVENT_LABELS.values())
        header = "  {:<8} {:<5}".format("ID", "Byte")
        for lab in labels:
            header += " {:<14}".format(lab)
        header += " {}".format("Known Signal")
        W(header)
        W("  " + "-" * (len(header) - 2))
        for pos in sorted_pos:
            row = "  {:<8} B{:<4}".format(pos[0], pos[1])
            for ek in EVENT_LABELS:
                val = format_transition(evsets, pos, ek)
                row += " {:<14}".format(val)
            row += " {}".format(get_known_signal(pos[0]))
            W(row)

    W("")
    W("=" * 70)
    W("SET COMPARISON (discrete byte-level positions)")
    W("=" * 70)

    print_set_table("UNIVERSAL CHANGES (in ALL 5 events)", categories["universal"], event_sets)
    print_set_table("INTERLOCK-COMMON (in both interlock events, not universal)",
                    categories["interlock_common"] - categories["universal"], event_sets)
    print_set_table("CHARGE-COMMON (in all 3 charge events, not universal)",
                    categories["charge_common"] - categories["universal"], event_sets)
    print_set_table("OVERLAP (in >=1 interlock AND >=1 charge, not universal)",
                    categories["overlap"] - categories["universal"], event_sets)
    print_set_table("INTERLOCK-ONLY (interlock events but NO charge events)",
                    categories["interlock_only"], event_sets)
    print_set_table("CHARGE-ONLY (charge events but NO interlock events)",
                    categories["charge_only"], event_sets)

    # -- Analog bytes summary
    W("")
    W("=" * 70)
    W("ANALOG BYTES (excluded from set comparison, >{} changes in window)".format(ANALOG_THRESHOLD))
    W("=" * 70)

    all_analog = set()
    for ek in EVENT_LABELS:
        all_analog |= event_sets[ek]["analog_bytes"]
    sorted_analog = sorted(all_analog, key=lambda k: (k[0], k[1]))

    if sorted_analog:
        W("")
        header = "  {:<8} {:<5}".format("ID", "Byte")
        for lab in EVENT_LABELS.values():
            header += " {:<8}".format("#chg")
        header += " {}".format("Known Signal")
        W(header)
        W("  " + "-" * (len(header) - 2))
        for pos in sorted_analog:
            row = "  {:<8} B{:<4}".format(pos[0], pos[1])
            for ek in EVENT_LABELS:
                count = event_sets[ek]["change_count"].get(pos, 0)
                if count > ANALOG_THRESHOLD:
                    row += " {:<8}".format(count)
                elif count > 0:
                    cnt_str = "({})".format(count)
                    row += " {:<8}".format(cnt_str)
                else:
                    row += " {:<8}".format("---")
            row += " {}".format(get_known_signal(pos[0]))
            W(row)
    else:
        W("  (none)")

    # -- Order comparison section
    W("")
    W("=" * 70)
    W("ORDER COMPARISON (cascade timing)")
    W("=" * 70)

    corrs = order_cmp["correlations"]
    if corrs:
        W("")
        W("Spearman rank correlations (shared discrete byte positions):")
        for pair_label, data in sorted(corrs.items()):
            r_val = data["r"]
            n = data["n_shared"]
            if math.isnan(r_val):
                W("  {:<25} r = N/A (n={}, too few shared positions)".format(pair_label, n))
            else:
                W("  {:<25} r = {:+.3f}  (n={})".format(pair_label, r_val, n))
    else:
        W("")
        W("  Insufficient overlap for rank correlation.")

    cascade = order_cmp["cascade"]
    if cascade:
        W("")
        W("Cascade ordering (overlapping positions, sorted by HVAC_Pull dt):")
        labels = list(EVENT_LABELS.values())
        header = "  {:<5} {:<8} {:<5}".format("Rank", "ID", "Byte")
        for lab in labels:
            header += " {:<12}".format(lab + " dt")
        header += " {}".format("Known Signal")
        W(header)
        W("  " + "-" * (len(header) - 2))

        for row in cascade:
            line = "  {:<5} {:<8} B{:<4}".format(row["rank"], row["id"], row["byte"])
            for lab in labels:
                dt_val = row.get(lab)
                if dt_val is not None:
                    dt_str = "{:+.3f}".format(dt_val)
                    line += " {:<12}".format(dt_str)
                else:
                    line += " {:<12}".format("N/A")
            line += " {}".format(row["known_signal"])
            W(line)

    # -- Value comparison section
    W("")
    W("=" * 70)
    W("VALUE COMPARISON (byte transitions for overlapping positions)")
    W("=" * 70)

    matching = [v for v in value_cmp if v["transitions_match"]]
    differing = [v for v in value_cmp if not v["transitions_match"]]

    W("")
    W("Matching transitions ({} positions where all present events agree):".format(len(matching)))
    if matching:
        for v in matching:
            vals = []
            for lab_key, lab_val in EVENT_LABELS.items():
                ev = v["events"].get(lab_val)
                if ev:
                    vals.append("{}:{}->{}".format(lab_val, ev["old"], ev["new"]))
            sig = " [{}]".format(v["known_signal"]) if v["known_signal"] else ""
            W("  {} B{}: {}{}".format(v["id"], v["byte"], ", ".join(vals), sig))
    else:
        W("  (none)")

    W("")
    W("Differing transitions ({} positions where events disagree):".format(len(differing)))
    if differing:
        for v in differing:
            sig = " [{}]".format(v["known_signal"]) if v["known_signal"] else ""
            W("  {} B{}:{}".format(v["id"], v["byte"], sig))
            for lab_key, lab_val in EVENT_LABELS.items():
                ev = v["events"].get(lab_val)
                if ev:
                    W("    {:<12} {}->{}  (dt={:+.3f}, n={})".format(lab_val, ev["old"], ev["new"], ev["dt"], ev["n_changes"]))
                else:
                    W("    {:<12} ---".format(lab_val))
    else:
        W("  (none)")

    # -- Bit-level detail for universal changes
    W("")
    W("=" * 70)
    W("BIT-LEVEL DETAIL (universal positions)")
    W("=" * 70)

    universal_sorted = sorted(categories["universal"], key=lambda k: (k[0], k[1]))
    for pos in universal_sorted:
        sig_name = get_known_signal(pos[0])
        sig = " [{}]".format(sig_name) if sig_name else ""
        W("")
        W("  {} B{}{}:".format(pos[0], pos[1], sig))
        for ek, lab in EVENT_LABELS.items():
            bits_in_event = set()
            for c in all_events[ek]["changes"]:
                if c["id"] == pos[0] and c["byte"] == pos[1]:
                    for b in c["bits"]:
                        direction = "SET" if b["new"] == 1 else "CLR"
                        bits_in_event.add((b["bit"], direction))
            if bits_in_event:
                bit_str = ", ".join("b{}={}".format(b, d) for b, d in sorted(bits_in_event))
                trans = event_sets[ek]["transitions"].get(pos, [])
                trans_sorted = sorted(trans, key=lambda t: t[2])
                first = trans_sorted[0] if trans_sorted else ("?", "?", 0)
                W("    {:<12} {}->{}  dt={:+.3f}  bits: {}".format(lab, first[0], first[1], first[2], bit_str))
            else:
                W("    {:<12} ---".format(lab))

    # -- Conclusions
    W("")
    W("=" * 70)
    W("CONCLUSIONS")
    W("=" * 70)
    W("")

    n_universal = len(categories["universal"])
    n_overlap = len(categories["overlap"])
    n_il_only = len(categories["interlock_only"])
    n_ch_only = len(categories["charge_only"])
    n_total = len(categories["any_event"])

    W("  Total discrete (id,byte) positions across all events: {}".format(n_total))
    W("  Universal (all 5 events):    {}".format(n_universal))
    W("  Overlap (>=1 from each):     {}".format(n_overlap))
    W("  Interlock-only:              {}".format(n_il_only))
    W("  Charge-only:                 {}".format(n_ch_only))
    W("")

    if n_universal > 0:
        pct = 100.0 * n_universal / n_total
        W("  {} byte positions respond in ALL fault events ({:.0f}% of all positions).".format(n_universal, pct))
        W("  These represent the core fault-response path shared by both interlock")
        W("  disconnects and charge failures.")
    else:
        W("  No universal positions found -- fault paths may be distinct.")

    if n_overlap > n_universal:
        W("  {} additional positions overlap between groups but are not universal.".format(n_overlap - n_universal))

    if corrs:
        best_pair = None
        best_r = -999
        for pair_label, data in corrs.items():
            if not math.isnan(data["r"]) and data["r"] > best_r:
                best_r = data["r"]
                best_pair = pair_label

        if best_pair and best_r > 0.5:
            W("")
            W("  Strongest cascade ordering similarity: {} (r={:+.3f}).".format(best_pair, best_r))
            W("  This suggests similar temporal ordering of the fault cascade.")
        elif best_pair and best_r > 0.0:
            W("")
            W("  Weak ordering similarity: {} (r={:+.3f}).".format(best_pair, best_r))
            W("  The fault cascades may follow different temporal sequences.")
        elif best_pair:
            W("")
            W("  No positive ordering correlation found (best: {}, r={:+.3f}).".format(best_pair, best_r))
            W("  The fault cascades appear to follow different temporal sequences.")

    if n_il_only > 0:
        W("")
        W("  {} positions react ONLY to interlock events (physical HV disconnect).".format(n_il_only))
        W("  These may be direct HV-loss indicators not triggered by BMS-initiated shutdowns.")

    if n_ch_only > 0:
        W("")
        W("  {} positions react ONLY to charge failures.".format(n_ch_only))
        W("  These may be charger/BMS-specific fault indicators.")

    W("")
    return "\n".join(lines)


def build_json_output(all_events, event_sets, categories, order_cmp, value_cmp):
    """Build the structured JSON output."""

    def set_to_list(s):
        return sorted([{"id": p[0], "byte": p[1]} for p in s],
                       key=lambda x: (x["id"], x["byte"]))

    result = {
        "metadata": {
            "description": "Cross-reference of bit-flip patterns: interlock test vs charge failures",
            "filter": {
                "dt_range": [DT_MIN, DT_MAX],
                "analog_threshold": ANALOG_THRESHOLD,
                "interlock_pt_bus": INTERLOCK_PT_BUS,
                "standard_frames_only": True,
            },
        },
        "events": {},
        "set_comparison": {
            "universal": set_to_list(categories["universal"]),
            "interlock_common": set_to_list(categories["interlock_common"]),
            "charge_common": set_to_list(categories["charge_common"]),
            "overlap": set_to_list(categories["overlap"]),
            "interlock_only": set_to_list(categories["interlock_only"]),
            "charge_only": set_to_list(categories["charge_only"]),
            "counts": {
                "total_positions": len(categories["any_event"]),
                "universal": len(categories["universal"]),
                "overlap": len(categories["overlap"]),
                "interlock_only": len(categories["interlock_only"]),
                "charge_only": len(categories["charge_only"]),
            },
        },
        "order_comparison": {
            "correlations": {},
            "cascade": order_cmp["cascade"],
        },
        "value_comparison": value_cmp,
    }

    for ek, lab in EVENT_LABELS.items():
        edata = all_events[ek]
        es = event_sets[ek]
        result["events"][ek] = {
            "label": lab,
            "t_ref": edata["t_ref"],
            "group": "interlock" if ek in INTERLOCK_EVENTS else "charge",
            "n_changes_in_window": len(edata["changes"]),
            "n_discrete_positions": len(es["discrete_bytes"]),
            "n_analog_positions": len(es["analog_bytes"]),
        }

    for pair_label, data in order_cmp["correlations"].items():
        r_val = data["r"]
        result["order_comparison"]["correlations"][pair_label] = {
            "r": None if math.isnan(r_val) else round(r_val, 4),
            "n_shared": data["n_shared"],
        }

    return result


# -- Main --------------------------------------------------------------------

def main():
    print("Loading interlock bit catalog...")
    il_events = load_interlock_events(INTERLOCK_JSON)

    print("Loading charge failure bit catalog...")
    ch_events = load_charge_events(CHARGE_JSON)

    all_events = {}
    all_events.update(il_events)
    all_events.update(ch_events)

    print("Building event sets...")
    event_sets = {}
    for ek in EVENT_LABELS:
        event_sets[ek] = build_event_sets(all_events[ek]["changes"])
        n_d = len(event_sets[ek]["discrete_bytes"])
        n_a = len(event_sets[ek]["analog_bytes"])
        print("  {:<12}: {} discrete, {} analog (id,byte) positions".format(EVENT_LABELS[ek], n_d, n_a))

    print("Computing set comparison...")
    categories = compute_set_categories(event_sets)
    print("  Universal: {}".format(len(categories["universal"])))
    print("  Overlap:   {}".format(len(categories["overlap"])))
    print("  IL-only:   {}".format(len(categories["interlock_only"])))
    print("  CH-only:   {}".format(len(categories["charge_only"])))

    print("Computing order comparison...")
    order_cmp = compute_order_comparison(event_sets, categories["overlap"])

    print("Computing value comparison...")
    value_cmp = compute_value_comparison(event_sets, categories["overlap"])

    print("Generating report...")
    txt_report = format_txt_report(all_events, event_sets, categories, order_cmp, value_cmp)
    json_output = build_json_output(all_events, event_sets, categories, order_cmp, value_cmp)

    OUTPUT_TXT.write_text(txt_report, encoding="utf-8")
    print("  Wrote {}".format(OUTPUT_TXT))

    OUTPUT_JSON.write_text(json.dumps(json_output, indent=2), encoding="utf-8")
    print("  Wrote {}".format(OUTPUT_JSON))

    print("")
    print(txt_report)


if __name__ == "__main__":
    main()
