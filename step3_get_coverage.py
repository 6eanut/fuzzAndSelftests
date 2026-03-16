#!/usr/bin/env python3
"""
Step 3: Calculate BB and function coverage rates via set intersection.

New in this version:
  - categorize() uses os.path.normpath() to resolve ".." before matching,
    fixing mis-categorization of paths like arch/riscv/kvm/../../../virt/kvm/foo.c
  - For selftests-kvm, also writes a func->testcase mapping file so that
    step4 can annotate which testcase triggered each function.

Outputs (per tag):
  prefix/coverage/output/{tag}-bb-cov.txt
  prefix/coverage/output/{tag}-functions-cov.txt
  prefix/coverage/output/selftests-kvm-func-testcase-map.txt  (selftests only)
"""

import os
import glob
import argparse
from pathlib import Path
from collections import defaultdict


CATS = ("arch/riscv/kvm", "virt")


# ── Categorization (normpath-aware) ───────────────────────────────────────────

def categorize(filepath: str) -> str | None:
    """
    Return 'arch/riscv/kvm', 'virt', or None.
    Normalizes path first so that sequences like
      arch/riscv/kvm/../../../virt/kvm/foo.c
    resolve to  virt/kvm/foo.c  and are correctly assigned to 'virt'.
    """
    norm = os.path.normpath(filepath)
    if "arch/riscv/kvm" in norm:
        return "arch/riscv/kvm"
    if "virt/" in norm:
        return "virt"
    return None


# ── Read helpers ───────────────────────────────────────────────────────────────

def read_set(path: str) -> set[str]:
    if not os.path.exists(path):
        print(f"  WARNING: file not found: {path}")
        return set()
    with open(path) as fh:
        return {line.strip() for line in fh if line.strip()}


def read_functions_file(path: str) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """
    Parse a *-functions.txt (TSV: file:line <TAB> function).
    Returns:
      fl_by_cat : {cat -> set of "file:line"}
      fn_by_cat : {cat -> set of function names}
    """
    fl_by_cat: dict[str, set[str]] = defaultdict(set)
    fn_by_cat: dict[str, set[str]] = defaultdict(set)
    if not os.path.exists(path):
        print(f"  WARNING: file not found: {path}")
        return fl_by_cat, fn_by_cat
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or "\t" not in line:
                continue
            fileline, func = line.split("\t", 1)
            cat = categorize(fileline)
            if cat:
                fl_by_cat[cat].add(fileline)
                fn_by_cat[cat].add(func)
    return fl_by_cat, fn_by_cat


def merge_functions_dir(directory: str) -> tuple[
    dict[str, set[str]],           # fl_merged:  cat -> file:line set
    dict[str, set[str]],           # fn_merged:  cat -> func name set
    dict[str, dict[str, set[str]]] # fn_testcases: cat -> {func -> set of testcase names}
]:
    """
    Merge all *_functions.txt files in a directory (for selftests).
    Also builds a per-function testcase attribution map.
    Testcase name is the 'xxx' from 'xxx_functions.txt'.
    """
    fl_merged:    dict[str, set[str]]           = defaultdict(set)
    fn_merged:    dict[str, set[str]]           = defaultdict(set)
    fn_testcases: dict[str, dict[str, set[str]]] = {
        "arch/riscv/kvm": defaultdict(set),
        "virt":           defaultdict(set),
    }

    paths = sorted(glob.glob(os.path.join(directory, "*_functions.txt")))
    if not paths:
        print(f"  WARNING: no *_functions.txt in {directory}")
        return fl_merged, fn_merged, fn_testcases

    print(f"  Merging {len(paths)} test-case function files ...")
    for p in paths:
        # testcase name = filename without _functions.txt suffix
        testcase = os.path.basename(p).replace("_functions.txt", "")
        fl, fn = read_functions_file(p)
        for cat, items in fl.items():
            fl_merged[cat].update(items)
        for cat, funcs in fn.items():
            fn_merged[cat].update(funcs)
            for func in funcs:
                fn_testcases[cat][func].add(testcase)

    return fl_merged, fn_merged, fn_testcases


# ── Write helpers ──────────────────────────────────────────────────────────────

def write_bb_cov(out_path: str,
                 fl_covered: dict[str, set[str]],
                 fl_total:   dict[str, set[str]]) -> None:
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as fh:
        for cat in CATS:
            total_set = fl_total.get(cat, set())
            hit = fl_covered.get(cat, set()) & total_set
            tot = len(total_set)
            cov = len(hit)
            pct = (cov / tot * 100) if tot > 0 else 0.0
            fh.write(f"{cat}: covered={cov} / total={tot} ({pct:.2f}%)\n")
    print(f"  Written -> {out_path}")


def write_fn_cov(out_path: str,
                 fn_covered: dict[str, set[str]],
                 fn_total:   dict[str, set[str]]) -> None:
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as fh:
        for cat in CATS:
            total_set = fn_total.get(cat, set())
            hit = fn_covered.get(cat, set()) & total_set
            tot = len(total_set)
            cov = len(hit)
            pct = (cov / tot * 100) if tot > 0 else 0.0
            fh.write(f"{cat}: covered={cov} / total={tot} ({pct:.2f}%)\n")
        fh.write("\n")
        for cat in CATS:
            total_set = fn_total.get(cat, set())
            hit = fn_covered.get(cat, set()) & total_set
            fh.write(f"--- functions covered ({cat}) ---\n")
            for fn in sorted(hit):
                fh.write(fn + "\n")
            fh.write("\n")
    print(f"  Written -> {out_path}")


def write_testcase_map(out_path: str,
                       fn_testcases: dict[str, dict[str, set[str]]],
                       fn_covered:   dict[str, set[str]],
                       fn_total:     dict[str, set[str]]) -> None:
    """
    Write func -> testcase mapping for functions that are in the covered∩total set.
    Format (TSV):
        cat <TAB> func <TAB> testcase1,testcase2,...
    """
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as fh:
        for cat in CATS:
            total_set = fn_total.get(cat, set())
            hit = fn_covered.get(cat, set()) & total_set
            tc_map = fn_testcases.get(cat, {})
            for func in sorted(hit):
                testcases = sorted(tc_map.get(func, set()))
                fh.write(f"{cat}\t{func}\t{','.join(testcases)}\n")
    print(f"  Written -> {out_path}")


# ── Per-tag pipeline ───────────────────────────────────────────────────────────

def load_total_sets(tag: str, sum_out: str) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    fl_total: dict[str, set[str]] = {}
    fn_total: dict[str, set[str]] = {}
    for cat, suffix in (("arch/riscv/kvm", "kvm"), ("virt", "virt")):
        fl_total[cat] = read_set(os.path.join(sum_out, f"{tag}-all-filelines-{suffix}.txt"))
        fn_total[cat] = read_set(os.path.join(sum_out, f"{tag}-all-funcs-{suffix}.txt"))
        print(f"  Total [{cat}]: {len(fl_total[cat])} file:lines, {len(fn_total[cat])} functions")
    return fl_total, fn_total


def process_single(tag: str, functions_file: str,
                   sum_out: str, cov_out: str) -> None:
    print(f"\n  [{tag}] Loading total sets from step2 ...")
    fl_total, fn_total = load_total_sets(tag, sum_out)

    print(f"  [{tag}] Loading covered sets from step1 ...")
    fl_covered, fn_covered = read_functions_file(functions_file)
    for cat in CATS:
        print(f"  Covered [{cat}]: {len(fl_covered.get(cat, set()))} file:lines, "
              f"{len(fn_covered.get(cat, set()))} functions")

    write_bb_cov(os.path.join(cov_out, f"{tag}-bb-cov.txt"),        fl_covered, fl_total)
    write_fn_cov(os.path.join(cov_out, f"{tag}-functions-cov.txt"), fn_covered, fn_total)


def process_selftests(functions_dir: str, sum_out: str, cov_out: str) -> None:
    tag = "selftests-kvm"
    print(f"\n  [{tag}] Loading total sets from step2 ...")
    fl_total, fn_total = load_total_sets(tag, sum_out)

    print(f"  [{tag}] Loading covered sets from step1 ...")
    fl_covered, fn_covered, fn_testcases = merge_functions_dir(functions_dir)
    for cat in CATS:
        print(f"  Covered [{cat}]: {len(fl_covered.get(cat, set()))} file:lines, "
              f"{len(fn_covered.get(cat, set()))} functions")

    write_bb_cov(os.path.join(cov_out, f"{tag}-bb-cov.txt"),        fl_covered, fl_total)
    write_fn_cov(os.path.join(cov_out, f"{tag}-functions-cov.txt"), fn_covered, fn_total)
    write_testcase_map(
        os.path.join(cov_out, "selftests-kvm-func-testcase-map.txt"),
        fn_testcases, fn_covered, fn_total,
    )


# ── Entry point ────────────────────────────────────────────────────────────────

def run(prefix: str) -> None:
    a2f_out = os.path.join(prefix, "addr2function", "output")
    sum_out = os.path.join(prefix, "sum",           "output")
    cov_out = os.path.join(prefix, "coverage",      "output")

    print("\n[Step 3] Computing coverage rates via set intersection ...\n")

    process_single("fuzz-old",
                   os.path.join(a2f_out, "fuzz-old-functions.txt"),
                   sum_out, cov_out)
    process_single("fuzz-new",
                   os.path.join(a2f_out, "fuzz-new-functions.txt"),
                   sum_out, cov_out)
    process_selftests(
        os.path.join(a2f_out, "selftests-kvm-functions"),
        sum_out, cov_out)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Step 3: compute coverage rates via set intersection"
    )
    parser.add_argument("--prefix", default=".", help="Project prefix directory")
    args = parser.parse_args()
    run(args.prefix)