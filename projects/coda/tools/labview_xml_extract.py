#!/usr/bin/env python3
"""Extract CAN signal definitions from decompiled LabVIEW VI XML files.

Parses the VCTP (VI Consolidated Data Types) section of decompiled LabVIEW
.xml files, extracting signal names, data types, and cluster hierarchy.
Detects CAN IDs embedded in cluster names (e.g. "DCDCStatus2 (0x48A)").

Usage:
    python tools/labview_xml_extract.py <xml_file> [<xml_file2> ...] [--output signals.json]
    python tools/labview_xml_extract.py --batch <directory> [--output signals.json]

Output: JSON with message clusters, signals, and detected CAN IDs.
"""

import argparse
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

# LabVIEW type -> approximate CAN signal type hint
LV_TYPE_MAP = {
    "Boolean": {"bit_width": 1, "signed": False, "category": "boolean"},
    "NumUInt8": {"bit_width": 8, "signed": False, "category": "unsigned"},
    "NumInt8": {"bit_width": 8, "signed": True, "category": "signed"},
    "NumUInt16": {"bit_width": 16, "signed": False, "category": "unsigned"},
    "NumInt16": {"bit_width": 16, "signed": True, "category": "signed"},
    "NumUInt32": {"bit_width": 32, "signed": False, "category": "unsigned"},
    "NumInt32": {"bit_width": 32, "signed": True, "category": "signed"},
    "NumFloat32": {"bit_width": None, "signed": True, "category": "float_lv"},
    "NumFloat64": {"bit_width": None, "signed": True, "category": "float_lv"},
    "UnitUInt16": {"bit_width": 16, "signed": False, "category": "enum"},
    "String": {"bit_width": None, "signed": False, "category": "string"},
}

# Regex patterns for CAN ID extraction from cluster labels
CAN_ID_PATTERNS = [
    # "(0x48A)" or "(0x1D5)"
    re.compile(r'\(0x([0-9A-Fa-f]+)\)'),
    # "_208h" suffix (hex with 'h' suffix)
    re.compile(r'_([0-9A-Fa-f]{3,8})h$'),
    # "BS_208h" style
    re.compile(r'_([0-9A-Fa-f]{3,8})h\b'),
]


def extract_can_id(label):
    """Try to extract a CAN arbitration ID from a cluster label string.
    Returns (can_id_int, can_id_hex_str) or (None, None)."""
    if not label:
        return None, None
    for pattern in CAN_ID_PATTERNS:
        m = pattern.search(label)
        if m:
            hex_str = m.group(1)
            try:
                can_id = int(hex_str, 16)
                return can_id, f"0x{can_id:03X}"
            except ValueError:
                continue
    return None, None


def parse_vctp(xml_path):
    """Parse a LabVIEW decompiled XML file and extract TypeDesc entries from VCTP.

    Returns a list of flat TypeDesc dicts indexed by FlatTypeID.
    """
    tree = ET.parse(xml_path)
    root = tree.getroot()

    # Find the VCTP section
    vctp = root.find('.//VCTP')
    if vctp is None:
        return [], None

    section = vctp.find('Section')
    if section is None:
        return [], None

    # Also extract the source VI name from LVSR
    vi_name = None
    lvsr = root.find('.//LVSR')
    if lvsr is not None:
        lvsr_section = lvsr.find('Section')
        if lvsr_section is not None:
            vi_name = lvsr_section.get('Name', None)

    # Build flat type table indexed by FlatTypeID (order of appearance)
    flat_types = []
    for td in section.findall('TypeDesc'):
        entry = _parse_typedesc(td)
        flat_types.append(entry)

    return flat_types, vi_name


def _parse_typedesc(td_elem):
    """Parse a single TypeDesc element into a dict."""
    td_type = td_elem.get('Type', '')
    label = td_elem.get('Label', '')
    entry = {
        'type': td_type,
        'label': label,
    }

    # For types with known bit widths
    if td_type in LV_TYPE_MAP:
        entry['type_info'] = LV_TYPE_MAP[td_type].copy()

    # Enum labels (UnitUInt16 etc.)
    enum_labels = [el.text for el in td_elem.findall('EnumLabel') if el.text]
    if enum_labels:
        entry['enum_labels'] = enum_labels

    # Cluster: collect child TypeDesc references
    if td_type == 'Cluster':
        children = []
        for child_td in td_elem.findall('TypeDesc'):
            type_id = child_td.get('TypeID')
            if type_id is not None:
                children.append(int(type_id))
        entry['children'] = children

    # TypeDef: unwrap to find the nested type and label
    if td_type == 'TypeDef':
        nested = td_elem.find('TypeDesc')
        if nested is not None:
            entry['nested'] = _parse_typedesc(nested)
            # Nested clusters may have their own Label
            nested_label = nested.get('Label', '')
            if nested_label:
                entry['nested_label'] = nested_label
        # TypeDef source file label
        label_elem = td_elem.find('Label')
        if label_elem is not None:
            entry['typedef_source'] = label_elem.get('Text', '')

    # Array: note dimensionality and element type
    if td_type == 'Array':
        child_td = td_elem.find('TypeDesc')
        if child_td is not None:
            type_id = child_td.get('TypeID')
            if type_id is not None:
                entry['element_type_id'] = int(type_id)

    return entry


def resolve_cluster(flat_types, type_id, depth=0, max_depth=10, visited=None):
    """Recursively resolve a cluster TypeDesc into a signal tree.

    Returns a dict with:
      - name: cluster label
      - can_id / can_id_hex: if detected in name
      - signals: list of resolved child signals/subclusters
    """
    if visited is None:
        visited = set()
    if depth > max_depth or type_id in visited:
        return None
    visited = visited | {type_id}

    if type_id < 0 or type_id >= len(flat_types):
        return None

    td = flat_types[type_id]
    td_type = td['type']
    label = td.get('label', '')

    # TypeDef: unwrap
    if td_type == 'TypeDef':
        nested = td.get('nested', {})
        nested_type = nested.get('type', '')
        nested_label = td.get('nested_label', label)
        if nested_type == 'Cluster':
            children_ids = nested.get('children', [])
            can_id, can_id_hex = extract_can_id(nested_label)
            signals = []
            for cid in children_ids:
                child = resolve_cluster(flat_types, cid, depth + 1, max_depth, visited)
                if child:
                    signals.append(child)
            result = {
                'name': nested_label,
                'typedef_source': td.get('typedef_source', ''),
                'signals': signals,
            }
            if can_id is not None:
                result['can_id'] = can_id
                result['can_id_hex'] = can_id_hex
            return result
        else:
            # Simple typedef (e.g., ParkStates -> NumUInt16)
            type_info = LV_TYPE_MAP.get(nested_type, {})
            return {
                'name': nested_label or label,
                'lv_type': nested_type,
                'type_info': type_info,
                'typedef_source': td.get('typedef_source', ''),
            }

    # Cluster
    if td_type == 'Cluster':
        children_ids = td.get('children', [])
        can_id, can_id_hex = extract_can_id(label)
        signals = []
        for cid in children_ids:
            child = resolve_cluster(flat_types, cid, depth + 1, max_depth, visited)
            if child:
                signals.append(child)
        result = {
            'name': label,
            'signals': signals,
        }
        if can_id is not None:
            result['can_id'] = can_id
            result['can_id_hex'] = can_id_hex
        return result

    # Array
    if td_type == 'Array':
        elem_id = td.get('element_type_id')
        elem = None
        if elem_id is not None:
            elem = resolve_cluster(flat_types, elem_id, depth + 1, max_depth, visited)
        return {
            'name': label,
            'lv_type': 'Array',
            'element': elem,
        }

    # Leaf signal (Boolean, NumFloat64, NumUInt8, etc.)
    type_info = td.get('type_info', LV_TYPE_MAP.get(td_type, {}))
    result = {
        'name': label,
        'lv_type': td_type,
    }
    if type_info:
        result['type_info'] = type_info
    if 'enum_labels' in td:
        result['enum_labels'] = td['enum_labels']
    return result


def find_message_clusters(flat_types):
    """Find all top-level clusters that likely represent CAN messages or module data.

    Strategy:
    1. TypeDef entries wrapping Clusters (these are the primary type definitions)
    2. Named Clusters with embedded CAN IDs
    3. Named Clusters that look like module data (e.g., "BMS Globals", "DLCM")

    Skips internal/infrastructure types (RepeatedBlock, AlignedBlock, DCO tables, etc.)
    """
    results = []
    seen_labels = set()

    # Internal labels to skip
    SKIP_LABELS = {'udf', 'flg', 'oRt', 'eof', 'txd', 'ext'}
    SKIP_TYPES = {'RepeatedBlock', 'AlignedBlock', 'Block', 'Void', 'Ptr',
                  'NumInt32', 'NumInt16', 'NumUInt16', 'NumUInt8', 'NumUInt32',
                  'NumInt8', 'NumFloat32', 'NumFloat64', 'Boolean', 'String'}

    for i, td in enumerate(flat_types):
        td_type = td['type']
        label = td.get('label', '')

        # Skip unlabeled internal types
        if td_type in SKIP_TYPES:
            continue
        if label in SKIP_LABELS:
            continue

        # TypeDef wrapping a Cluster — primary target
        if td_type == 'TypeDef':
            nested = td.get('nested', {})
            nested_label = td.get('nested_label', '')
            if nested.get('type') == 'Cluster' and nested_label:
                if nested_label not in seen_labels:
                    seen_labels.add(nested_label)
                    resolved = resolve_cluster(flat_types, i)
                    if resolved and resolved.get('signals'):
                        resolved['source_type'] = 'TypeDef'
                        resolved['flat_type_id'] = i
                        results.append(resolved)
            continue

        # Named Cluster with CAN ID or module-like name
        if td_type == 'Cluster' and label:
            if label in seen_labels:
                continue
            can_id, _ = extract_can_id(label)
            # Include if it has a CAN ID, or if it's a named cluster with children
            children = td.get('children', [])
            if can_id is not None or (len(children) >= 2 and label not in SKIP_LABELS):
                seen_labels.add(label)
                resolved = resolve_cluster(flat_types, i)
                if resolved and resolved.get('signals'):
                    resolved['source_type'] = 'Cluster'
                    resolved['flat_type_id'] = i
                    results.append(resolved)

    return results


def extract_signals_from_file(xml_path):
    """Full extraction pipeline for a single XML file."""
    flat_types, vi_name = parse_vctp(xml_path)
    if not flat_types:
        return None

    clusters = find_message_clusters(flat_types)

    return {
        'source_file': os.path.basename(xml_path),
        'vi_name': vi_name,
        'clusters': clusters,
        'total_type_entries': len(flat_types),
    }


def flatten_signals(cluster, parent_path=""):
    """Flatten a nested cluster tree into a list of leaf signals with full paths."""
    signals = []
    name = cluster.get('name', '')
    path = f"{parent_path}.{name}" if parent_path else name

    if 'signals' in cluster:
        for sig in cluster['signals']:
            signals.extend(flatten_signals(sig, path))
    else:
        # Leaf signal
        entry = {
            'path': path,
            'name': name,
            'lv_type': cluster.get('lv_type', ''),
        }
        if 'type_info' in cluster:
            entry.update(cluster['type_info'])
        if 'enum_labels' in cluster:
            entry['enum_labels'] = cluster['enum_labels']
        signals.append(entry)

    return signals


def print_summary(result):
    """Print a human-readable summary of extracted signals."""
    print(f"\n{'='*70}")
    print(f"File: {result['source_file']}")
    if result['vi_name']:
        print(f"VI:   {result['vi_name']}")
    print(f"Total type entries in VCTP: {result['total_type_entries']}")
    print(f"{'='*70}")

    for cluster in result['clusters']:
        can_id_str = ""
        if 'can_id_hex' in cluster:
            can_id_str = f"  [CAN ID: {cluster['can_id_hex']} = {cluster['can_id']} dec]"
        print(f"\n  {cluster['name']}{can_id_str}")
        if 'typedef_source' in cluster:
            print(f"    (from {cluster['typedef_source']})")
        print(f"    {'-'*50}")

        flat = flatten_signals(cluster)
        for sig in flat:
            # Remove the top cluster name from the path for cleaner display
            parts = sig['path'].split('.', 1)
            display_path = parts[1] if len(parts) > 1 else parts[0]
            type_str = sig.get('lv_type', '?')
            bit_w = sig.get('bit_width')
            cat = sig.get('category', '')
            extras = []
            if bit_w:
                extras.append(f"{bit_w}bit")
            if cat:
                extras.append(cat)
            if 'enum_labels' in sig:
                extras.append(f"enum[{','.join(sig['enum_labels'][:3])}{'...' if len(sig['enum_labels'])>3 else ''}]")
            extra_str = f" ({', '.join(extras)})" if extras else ""
            print(f"      {display_path}: {type_str}{extra_str}")


def merge_results(all_results):
    """Merge results from multiple files, deduplicating clusters by name."""
    merged_clusters = {}

    for result in all_results:
        source = result['source_file']
        for cluster in result['clusters']:
            name = cluster['name']
            key = name
            if key not in merged_clusters:
                merged_clusters[key] = cluster.copy()
                merged_clusters[key]['sources'] = [source]
            else:
                existing = merged_clusters[key]
                # Prefer version with CAN ID
                if 'can_id' in cluster and 'can_id' not in existing:
                    existing['can_id'] = cluster['can_id']
                    existing['can_id_hex'] = cluster['can_id_hex']
                if source not in existing['sources']:
                    existing['sources'].append(source)

    return {
        'source_files': [r['source_file'] for r in all_results],
        'clusters': list(merged_clusters.values()),
        'total_unique_clusters': len(merged_clusters),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Extract CAN signal definitions from decompiled LabVIEW XML files"
    )
    parser.add_argument('files', nargs='*', help="XML file(s) to parse")
    parser.add_argument('--batch', metavar='DIR',
                        help="Scan directory for all non-FPHb/BDHb .xml files")
    parser.add_argument('--output', '-o', metavar='FILE',
                        help="Write JSON output to file")
    parser.add_argument('--quiet', '-q', action='store_true',
                        help="Suppress human-readable summary")
    parser.add_argument('--flat', action='store_true',
                        help="Also include a flat signal list in output")
    args = parser.parse_args()

    xml_files = list(args.files) if args.files else []

    if args.batch:
        batch_dir = Path(args.batch)
        for xml_path in sorted(batch_dir.rglob('*.xml')):
            name = xml_path.name
            # Skip FPHb and BDHb sidecar files — they don't have VCTP
            if '_FPHb' in name or '_BDHb' in name:
                continue
            xml_files.append(str(xml_path))

    if not xml_files:
        parser.print_help()
        sys.exit(1)

    all_results = []
    for xml_path in xml_files:
        result = extract_signals_from_file(xml_path)
        if result and result['clusters']:
            all_results.append(result)
            if not args.quiet:
                print_summary(result)

    if not all_results:
        print("No signal clusters found in any input files.", file=sys.stderr)
        sys.exit(1)

    # Merge if multiple files
    if len(all_results) > 1:
        merged = merge_results(all_results)
        if not args.quiet:
            print(f"\n{'='*70}")
            print(f"MERGED: {merged['total_unique_clusters']} unique clusters "
                  f"from {len(merged['source_files'])} files")
            print(f"{'='*70}")
        output_data = merged
    else:
        output_data = all_results[0]

    # Optionally add flat signal list
    if args.flat:
        flat_signals = []
        clusters = output_data.get('clusters', [])
        for cluster in clusters:
            for sig in flatten_signals(cluster):
                sig['parent_cluster'] = cluster['name']
                if 'can_id' in cluster:
                    sig['can_id'] = cluster['can_id']
                    sig['can_id_hex'] = cluster['can_id_hex']
                flat_signals.append(sig)
        output_data['flat_signals'] = flat_signals
        if not args.quiet:
            print(f"\nTotal flat signals: {len(flat_signals)}")

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w') as f:
            json.dump(output_data, f, indent=2)
        print(f"\nJSON written to: {args.output}")


if __name__ == '__main__':
    main()
