#!/usr/bin/env python3
"""
run_all.py — Master script: run all 4 analysis steps in sequence.

Usage:
    python3 run_all.py --prefix /path/to/project [--steps 1234]

Steps:
  1 = addr2function  (addr -> file:line, function)
  2 = get_sum        (count total kcov-instrumented BB / functions in vmlinux)
  3 = get_coverage   (compute coverage rates)
  4 = analyze        (compare & generate HTML reports)

The --steps flag lets you re-run individual steps, e.g. --steps 34 to only
redo coverage computation and HTML generation.
"""

import argparse
import sys
import os
import importlib.util
import time


def load_module(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def banner(msg: str) -> None:
    w = 70
    print("\n" + "=" * w)
    print(f"  {msg}")
    print("=" * w)


def main() -> None:
    here = os.path.dirname(os.path.abspath(__file__))

    parser = argparse.ArgumentParser(
        description="KVM Coverage Analysis — run all steps",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--prefix", required=True,
        help="Root directory containing addr2function/, sum/, coverage/, analyze/ subdirs",
    )
    parser.add_argument(
        "--steps", default="1234",
        help="Which steps to run, e.g. '234' to skip step 1 (default: 1234)",
    )
    args = parser.parse_args()

    steps   = set(args.steps)
    prefix  = os.path.abspath(args.prefix)
    t_start = time.time()

    print(f"\nProject prefix : {prefix}")
    print(f"Steps to run   : {', '.join(sorted(steps))}")

    if "1" in steps:
        banner("Step 1 — Convert addresses to file:line / function")
        mod = load_module("step1", os.path.join(here, "step1_addr2function.py"))
        mod.run(prefix)

    if "2" in steps:
        banner("Step 2 — Extract total kcov-instrumented blocks from vmlinux")
        mod = load_module("step2", os.path.join(here, "step2_get_sum.py"))
        mod.run(prefix)

    if "3" in steps:
        banner("Step 3 — Compute coverage rates")
        mod = load_module("step3", os.path.join(here, "step3_get_coverage.py"))
        mod.run(prefix)

    if "4" in steps:
        banner("Step 4 — Generate HTML comparison reports")
        mod = load_module("step4", os.path.join(here, "step4_analyze_compare.py"))
        mod.run(prefix)

    elapsed = time.time() - t_start
    print(f"\n✅  All done in {elapsed:.1f}s")
    print(f"\nOutputs:")
    if "1" in steps:
        print(f"  {prefix}/addr2function/output/")
    if "2" in steps:
        print(f"  {prefix}/sum/output/")
    if "3" in steps:
        print(f"  {prefix}/coverage/output/")
    if "4" in steps:
        print(f"  {prefix}/analyze/output/*.html")


if __name__ == "__main__":
    main()
