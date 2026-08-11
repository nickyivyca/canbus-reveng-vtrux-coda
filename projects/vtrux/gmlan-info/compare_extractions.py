#!/usr/bin/env python3
"""
Compare signal counts between two extraction JSON files produced by the
pdfplumber or Docling extractors.  Highlights messages with different signal
counts and signals missing from each file.

Usage:
    python compare_extractions.py --old old.json --new new.json
    python compare_extractions.py --old a.json --new b.json \\
        --old-label "pdfplumber" --new-label "docling"
"""
import argparse
import json


def main():
    p = argparse.ArgumentParser(description="Compare two extraction JSON files.")
    p.add_argument("--old", required=True, help="First (old/baseline) extraction JSON.")
    p.add_argument("--new", required=True, help="Second (new) extraction JSON.")
    p.add_argument("--old-label", default="old", help="Display label for first file.")
    p.add_argument("--new-label", default="new", help="Display label for second file.")
    args = p.parse_args()

    with open(args.old, encoding="utf-8") as f:
        old = json.load(f)["messages"]
    with open(args.new, encoding="utf-8") as f:
        new = json.load(f)["messages"]

    old_ids = set(old)
    new_ids = set(new)

    only_old = sorted(old_ids - new_ids, key=lambda x: int(x, 16))
    only_new = sorted(new_ids - old_ids, key=lambda x: int(x, 16))
    both     = sorted(old_ids & new_ids, key=lambda x: int(x, 16))

    print(f"Messages only in {args.old_label} ({len(only_old)}):")
    for mid in only_old:
        print(f"  {mid}: {old[mid]['name']} ({len(old[mid]['signals'])} signals)")

    print(f"\nMessages only in {args.new_label} ({len(only_new)}):")
    for mid in only_new:
        print(f"  {mid}: {new[mid]['name']} ({len(new[mid]['signals'])} signals)")

    print(f"\nMessages in both with differing signal counts:")
    any_diff = False
    for mid in both:
        o_sigs = old[mid]["signals"]
        n_sigs = new[mid]["signals"]
        if len(o_sigs) != len(n_sigs):
            any_diff = True
            print(f"  {mid}: {old[mid]['name']}")
            print(f"    {args.old_label}: {len(o_sigs)}  {args.new_label}: {len(n_sigs)}")
            o_names = {s["name"] for s in o_sigs}
            n_names = {s["name"] for s in n_sigs}
            for name in sorted(o_names - n_names):
                print(f"      MISSING from {args.new_label}: {name}")
            for name in sorted(n_names - o_names):
                print(f"      EXTRA in {args.new_label}:    {name}")
    if not any_diff:
        print("  (none)")

    print(f"\nSummary: {args.old_label}={len(old)} msgs / {args.new_label}={len(new)} msgs")
    old_total = sum(len(m["signals"]) for m in old.values())
    new_total = sum(len(m["signals"]) for m in new.values())
    print(f"  {args.old_label} signals: {old_total}")
    print(f"  {args.new_label} signals: {new_total}")
    print(f"  Difference: {old_total - new_total:+d}")


if __name__ == "__main__":
    main()
