#!/usr/bin/env python3
"""
Step 2: Extract ALL kcov-instrumented basic block addresses from vmlinux,
        then map them to file:line and function, filtered to arch/riscv/kvm
        and virt/, and count totals.

Strategy (mirrors the reference shell script):
  1. Disassemble vmlinux with riscv64-linux-gnu-objdump.
  2. In RISC-V, kcov inserts a call to __sanitizer_cov_trace_pc; the runtime
     address recorded by kcov is the RETURN ADDRESS, i.e. the instruction
     immediately AFTER the call site.  So we capture the address of the line
     that follows any line containing "__sanitizer_cov_trace_pc>".
  3. Feed all collected addresses to addr2line via stdin (pipe), one per line,
     using "addr2line -e vmlinux -f" — same approach as the reference script's
     "addr2line -e vmlinux -f < addr_file | paste - -".
  4. Filter to arch/riscv/kvm and virt/, count unique BB addresses and unique
     function names per subsystem.

Cross-tool auto-detection order:
  riscv64-linux-gnu-objdump  →  riscv64-unknown-linux-gnu-objdump  →  objdump

Inputs:
  prefix/sum/input/{tag}-vmlinux

Outputs:
  prefix/sum/output/{tag}-rawcover-sum.txt   (unique instrumented BB count)
  prefix/sum/output/{tag}-functions-sum.txt  (unique instrumented function count)

Sum file format:
  arch/riscv/kvm:<count>
  virt:<count>
  total:<count>
"""

import os
import re
import sys
import shutil
import subprocess
import argparse
from pathlib import Path
from collections import defaultdict


# ── Tool detection ────────────────────────────────────────────────────────────

def find_tool(*candidates: str) -> str:
    """Return the first candidate found in PATH, or raise."""
    for c in candidates:
        if shutil.which(c):
            return c
    raise FileNotFoundError(
        f"None of {candidates} found in PATH. "
        "Install riscv64-linux-gnu-binutils (e.g. apt install gcc-riscv64-linux-gnu binutils-riscv64-linux-gnu)."
    )


# ── Address extraction ────────────────────────────────────────────────────────

def extract_kcov_addrs(vmlinux: str, objdump: str) -> list[str]:
    """
    Stream objdump -d output, capture the address of the jalr instruction
    that calls __sanitizer_cov_trace_pc.

    Verified from actual rawcover data: the address kcov records IS the call
    instruction itself, e.g.:
        ffffffff80007544:   jalr  -40(ra) # ffffffff8050f518 <__sanitizer_cov_trace_pc>
        ↑ 0xffffffff80007544 is exactly what appears in rawcover

    So we grab the address field of every line containing "__sanitizer_cov_trace_pc>".
    """
    print(f"  Running {os.path.basename(objdump)} on {os.path.basename(vmlinux)} ...")
    cmd = [objdump, "-d", "--no-show-raw-insn", vmlinux]

    addrs: list[str] = []

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1 << 20,
        )
        for line in proc.stdout:
            if "__sanitizer_cov_trace_pc>" not in line:
                continue
            m = re.match(r"^\s*([0-9a-f]+):", line)
            if m:
                addrs.append("0x" + m.group(1))
        proc.wait()
    except FileNotFoundError:
        print(f"  ERROR: {objdump} not found.")
        sys.exit(1)

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for a in addrs:
        if a not in seen:
            seen.add(a)
            unique.append(a)

    print(f"  Found {len(unique)} unique kcov instrumentation points")
    return unique


# ── addr2line via stdin pipe ──────────────────────────────────────────────────

def addr2line_stdin(vmlinux: str, addrs: list[str], addr2line: str) -> list[tuple[str, str]]:
    """
    Feed addresses to addr2line via stdin, one per line.
    "addr2line -e vmlinux -f" outputs alternating lines:
        function_name
        file:line
    Returns list[(function, file:line)] in same order as addrs.
    Same approach as: addr2line -e vmlinux -f < addrs | paste - -
    """
    print(f"  Running addr2line on {len(addrs)} addresses (via stdin) ...")
    cmd = [addr2line, "-e", vmlinux, "-f"]
    input_data = "\n".join(addrs) + "\n"

    try:
        out = subprocess.check_output(
            cmd,
            input=input_data,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"  WARNING: addr2line returned non-zero: {e}")
        return [("??", "??:0")] * len(addrs)

    lines = out.splitlines()
    results: list[tuple[str, str]] = []
    for i in range(len(addrs)):
        func     = lines[i * 2].strip()     if i * 2     < len(lines) else "??"
        fileline = lines[i * 2 + 1].strip() if i * 2 + 1 < len(lines) else "??:0"
        results.append((func, fileline))

    print(f"  addr2line done.")
    return results


# ── Categorization ────────────────────────────────────────────────────────────

def categorize(filepath: str) -> str | None:
    # Normalize first to resolve ".." sequences, e.g.:
    #   arch/riscv/kvm/../../../virt/kvm/foo.c  ->  virt/kvm/foo.c
    import os as _os
    norm = _os.path.normpath(filepath)
    if "arch/riscv/kvm" in norm:
        return "arch/riscv/kvm"
    if "virt/" in norm:
        return "virt"
    return None


# ── Output ────────────────────────────────────────────────────────────────────

def write_sum(path: str, kvm_count: int, virt_count: int) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as fh:
        fh.write(f"arch/riscv/kvm:{kvm_count}\n")
        fh.write(f"virt:{virt_count}\n")
        fh.write(f"total:{kvm_count + virt_count}\n")
    print(f"  Written -> {path}  (kvm={kvm_count}, virt={virt_count})")


def write_set(path: str, items: set[str]) -> None:
    """Write a sorted set of strings, one per line."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as fh:
        for item in sorted(items):
            fh.write(item + "\n")
    print(f"  Written -> {path}  ({len(items)} entries)")


# ── Main per-vmlinux pipeline ─────────────────────────────────────────────────

def process_vmlinux(vmlinux: str, tag: str, base_out: str,
                    objdump: str, addr2line: str) -> None:
    addrs = extract_kcov_addrs(vmlinux, objdump)
    if not addrs:
        print("  WARNING: no kcov points found — check CONFIG_KCOV is enabled in this kernel")
        return

    mapping = addr2line_stdin(vmlinux, addrs, addr2line)

    # file:line sets (BB-level denominator — same representation as step1 output)
    fl_kvm:  set[str] = set()
    fl_virt: set[str] = set()
    # function name sets
    fn_kvm:  set[str] = set()
    fn_virt: set[str] = set()

    for _addr, (func, fileline) in zip(addrs, mapping):
        cat = categorize(fileline)
        if cat == "arch/riscv/kvm":
            if fileline not in ("??:0", "??"):
                fl_kvm.add(fileline)
            if func not in ("??", ""):
                fn_kvm.add(func)
        elif cat == "virt":
            if fileline not in ("??:0", "??"):
                fl_virt.add(fileline)
            if func not in ("??", ""):
                fn_virt.add(func)

    # ── summary counts (backward-compatible) ──────────────────────────────────
    write_sum(os.path.join(base_out, f"{tag}-rawcover-sum.txt"),
              len(fl_kvm), len(fl_virt))
    write_sum(os.path.join(base_out, f"{tag}-functions-sum.txt"),
              len(fn_kvm), len(fn_virt))

    # ── full sets for set-intersection coverage calculation in step3 ──────────
    # BB denominator: all instrumented file:line strings, split by subsystem
    write_set(os.path.join(base_out, f"{tag}-all-filelines-kvm.txt"),  fl_kvm)
    write_set(os.path.join(base_out, f"{tag}-all-filelines-virt.txt"), fl_virt)
    # Function denominator: all instrumented function names, split by subsystem
    write_set(os.path.join(base_out, f"{tag}-all-funcs-kvm.txt"),  fn_kvm)
    write_set(os.path.join(base_out, f"{tag}-all-funcs-virt.txt"), fn_virt)


# ── Entry point ───────────────────────────────────────────────────────────────

def run(prefix: str) -> None:
    base_in  = os.path.join(prefix, "sum", "input")
    base_out = os.path.join(prefix, "sum", "output")

    try:
        objdump   = find_tool("riscv64-linux-gnu-objdump",
                              "riscv64-unknown-linux-gnu-objdump",
                              "objdump")
        addr2line = find_tool("riscv64-linux-gnu-addr2line",
                              "riscv64-unknown-linux-gnu-addr2line",
                              "addr2line")
    except FileNotFoundError as e:
        print(f"  ERROR: {e}")
        sys.exit(1)

    print(f"  Using objdump   : {objdump}")
    print(f"  Using addr2line : {addr2line}")

    for tag in ("fuzz-old", "fuzz-new", "selftests-kvm"):
        vmlinux = os.path.join(base_in, f"{tag}-vmlinux")
        print(f"\n[sum] Processing {tag} ...")
        if not os.path.exists(vmlinux):
            print(f"  SKIP: {vmlinux} not found")
            continue
        process_vmlinux(vmlinux, tag, base_out, objdump, addr2line)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Step 2: count total kcov-instrumented BB/functions in vmlinux"
    )
    parser.add_argument("--prefix", default=".", help="Project prefix directory")
    args = parser.parse_args()
    run(args.prefix)