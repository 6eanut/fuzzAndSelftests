#!/usr/bin/env python3
"""
Step 1: Convert raw coverage addresses to file:line, function form.

Inputs:
  prefix/addr2function/input/fuzz-old-rawcover.txt
  prefix/addr2function/input/fuzz-new-rawcover.txt
  prefix/addr2function/input/selftests-kvm-rawcover/xxx_rawcover.txt  (multiple files)
  prefix/addr2function/input/fuzz-old-vmlinux
  prefix/addr2function/input/fuzz-new-vmlinux
  prefix/addr2function/input/selftests-kvm-vmlinux

Outputs:
  prefix/addr2function/output/fuzz-old-functions.txt
  prefix/addr2function/output/fuzz-new-functions.txt
  prefix/addr2function/output/selftests-kvm-functions/xxx_functions.txt
"""

import os
import sys
import glob
import shutil
import subprocess
import argparse
from pathlib import Path


# ── Filter: only keep lines from these two kernel subsystems ──────────────────
FILTER_PATHS = ("arch/riscv/kvm", "virt/")


def is_relevant(filepath: str) -> bool:
    if not filepath or filepath in ("??", ""):
        return False
    for p in FILTER_PATHS:
        if p in filepath:
            return True
    return False


def find_addr2line() -> str:
    """Return the first riscv addr2line found in PATH."""
    for candidate in (
        "riscv64-linux-gnu-addr2line",
        "riscv64-unknown-linux-gnu-addr2line",
        "addr2line",
    ):
        if shutil.which(candidate):
            return candidate
    raise FileNotFoundError(
        "No addr2line found in PATH. "
        "Install with: apt install binutils-riscv64-linux-gnu"
    )


def addr2line_stdin(vmlinux: str, addrs: list[str], addr2line_bin: str) -> dict[str, tuple[str, str]]:
    """
    Feed all addresses to addr2line via stdin — same as:
        addr2line -e vmlinux -f < addrs_file | paste - -
    Output is strictly 2 lines per address: function\nfile:line
    Returns dict: addr -> (file:line, function)
    """
    print(f"  Running {os.path.basename(addr2line_bin)} on {len(addrs)} addresses (stdin mode) ...")
    cmd = [addr2line_bin, "-e", vmlinux, "-f"]
    input_data = "\n".join(addrs) + "\n"
    try:
        out = subprocess.check_output(
            cmd, input=input_data, stderr=subprocess.DEVNULL, text=True
        )
    except subprocess.CalledProcessError as e:
        print(f"  WARNING: addr2line error: {e}")
        return {a: ("??:0", "??") for a in addrs}

    lines = out.splitlines()
    result: dict[str, tuple[str, str]] = {}
    for j, addr in enumerate(addrs):
        func     = lines[j * 2].strip()     if j * 2     < len(lines) else "??"
        fileline = lines[j * 2 + 1].strip() if j * 2 + 1 < len(lines) else "??:0"
        result[addr] = (fileline, func)
    print("  addr2line done.")
    return result


def process_rawcover(rawcover_file: str, vmlinux: str, output_file: str,
                     addr2line_bin: str) -> None:
    """
    Read addresses from rawcover_file, resolve via addr2line against vmlinux,
    filter to relevant paths, deduplicate, and write to output_file.

    Output format (TSV):
        file:line <TAB> function_name
    """
    print(f"  Reading addresses from {rawcover_file} ...")
    with open(rawcover_file, "r") as fh:
        raw_addrs = [ln.strip() for ln in fh if ln.strip()]

    # Deduplicate while preserving order
    seen_a: set[str] = set()
    unique_addrs: list[str] = []
    for a in raw_addrs:
        if a not in seen_a:
            seen_a.add(a)
            unique_addrs.append(a)
    print(f"  Total addresses: {len(raw_addrs)}, unique: {len(unique_addrs)}")

    mapping = addr2line_stdin(vmlinux, unique_addrs, addr2line_bin)

    # Build deduplicated set of (file:line, function) for relevant paths
    seen: set[tuple[str, str]] = set()
    entries: list[tuple[str, str]] = []
    for addr in unique_addrs:
        fileline, func = mapping.get(addr, ("??:0", "??"))
        if not is_relevant(fileline):
            continue
        key = (fileline, func)
        if key not in seen:
            seen.add(key)
            entries.append(key)

    print(f"  Relevant unique (file:line, function) pairs: {len(entries)}")

    Path(output_file).parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w") as fh:
        for fileline, func in sorted(entries):
            fh.write(f"{fileline}\t{func}\n")

    print(f"  Written -> {output_file}")


def run(prefix: str) -> None:
    base_in  = os.path.join(prefix, "addr2function", "input")
    base_out = os.path.join(prefix, "addr2function", "output")

    try:
        addr2line_bin = find_addr2line()
    except FileNotFoundError as e:
        print(f"  ERROR: {e}")
        sys.exit(1)
    print(f"  Using addr2line: {addr2line_bin}")

    # ── fuzz-old ──────────────────────────────────────────────────────────────
    print("\n[1/3] Processing fuzz-old ...")
    process_rawcover(
        rawcover_file=os.path.join(base_in,  "fuzz-old-rawcover.txt"),
        vmlinux      =os.path.join(base_in,  "fuzz-old-vmlinux"),
        output_file  =os.path.join(base_out, "fuzz-old-functions.txt"),
        addr2line_bin=addr2line_bin,
    )

    # ── fuzz-new ──────────────────────────────────────────────────────────────
    print("\n[2/3] Processing fuzz-new ...")
    process_rawcover(
        rawcover_file=os.path.join(base_in,  "fuzz-new-rawcover.txt"),
        vmlinux      =os.path.join(base_in,  "fuzz-new-vmlinux"),
        output_file  =os.path.join(base_out, "fuzz-new-functions.txt"),
        addr2line_bin=addr2line_bin,
    )

    # ── selftests/kvm ──────────────────────────────────────────────────────────
    print("\n[3/3] Processing selftests/kvm ...")
    selftest_raw_dir = os.path.join(base_in,  "selftests-kvm-rawcover")
    selftest_out_dir = os.path.join(base_out, "selftests-kvm-functions")
    vmlinux_st       = os.path.join(base_in,  "selftests-kvm-vmlinux")

    raw_files = sorted(glob.glob(os.path.join(selftest_raw_dir, "*_rawcover.txt")))
    if not raw_files:
        print(f"  WARNING: no *_rawcover.txt files found in {selftest_raw_dir}")
    for raw_file in raw_files:
        test_name = os.path.basename(raw_file).replace("_rawcover.txt", "")
        out_file  = os.path.join(selftest_out_dir, f"{test_name}_functions.txt")
        print(f"  -> {test_name}")
        process_rawcover(raw_file, vmlinux_st, out_file, addr2line_bin)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Step 1: addr -> file:line, function")
    parser.add_argument("--prefix", default=".", help="Project prefix directory")
    args = parser.parse_args()
    run(args.prefix)