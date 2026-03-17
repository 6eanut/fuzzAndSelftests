#!/usr/bin/env python3
"""
Step 4: Compare coverage between test suites and generate HTML reports.

Each function table now shows a 'Source File' column.
When one side is selftests-kvm, exclusive functions also show a 'Testcases' column.
"""

import os
import re
import argparse
from pathlib import Path
from collections import defaultdict


CATS = ("arch/riscv/kvm", "virt")


# ── Parsers ───────────────────────────────────────────────────────────────────

def parse_cov_summary(path: str) -> dict[str, tuple[int, int, float]]:
    result: dict[str, tuple[int, int, float]] = {}
    if not os.path.exists(path):
        return result
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("---"):
                break
            m = re.match(
                r"^(.+?):\s+covered=(\d+)\s*/\s*total=(\d+)\s*\(([0-9.]+)%\)", line
            )
            if m:
                result[m.group(1).strip()] = (
                    int(m.group(2)), int(m.group(3)), float(m.group(4))
                )
    return result


def parse_fn_cov(path: str) -> tuple[
    dict[str, set[str]],        # cat -> {func}
    dict[str, dict[str, str]],  # cat -> {func -> srcfile}
]:
    """
    Parse functions-cov.txt.
    Under '--- functions covered (cat) ---', each line is: func TAB srcfile
    """
    fn_sets:  dict[str, set[str]]       = defaultdict(set)
    fn_files: dict[str, dict[str, str]] = defaultdict(dict)

    if not os.path.exists(path):
        return fn_sets, fn_files

    current_cat: str | None = None
    with open(path) as fh:
        for line in fh:
            line = line.rstrip()
            if line.startswith("--- functions covered ("):
                m = re.match(r"--- functions covered \((.+?)\) ---", line)
                if m:
                    current_cat = m.group(1)
            elif line and current_cat:
                if "\t" in line:
                    func, srcfile = line.split("\t", 1)
                    fn_sets[current_cat].add(func.strip())
                    fn_files[current_cat][func.strip()] = srcfile.strip()
                else:
                    # backward compat: bare function name
                    fn_sets[current_cat].add(line.strip())

    return fn_sets, fn_files


def parse_testcase_map(path: str) -> dict[str, dict[str, list[str]]]:
    """Returns {cat: {func: [testcase, ...]}}"""
    result: dict[str, dict[str, list[str]]] = defaultdict(dict)
    if not os.path.exists(path):
        return result
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) != 3:
                continue
            cat, func, tc_str = parts
            result[cat][func] = sorted(tc_str.split(",")) if tc_str else []
    return result


# ── HTML helpers ──────────────────────────────────────────────────────────────

CSS = """
:root {
  --bg: #f8f9fb; --card: #ffffff; --border: #e2e6ea;
  --text: #212529; --muted: #6c757d; --blue: #0d6efd;
  --green: #198754; --orange: #fd7e14; --red: #dc3545; --purple: #6f42c1;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'Segoe UI', system-ui, sans-serif; background: var(--bg);
       color: var(--text); padding: 2rem; }
h1 { font-size: 1.6rem; margin-bottom: 0.3rem; }
.subtitle { color: var(--muted); font-size: 0.9rem; margin-bottom: 2rem; }
h2 { font-size: 1.1rem; margin: 1.5rem 0 0.8rem; color: var(--blue); }
h3 { font-size: 0.95rem; margin: 1.2rem 0 0.5rem; color: var(--purple); }
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin-bottom: 1.5rem; }
.card { background: var(--card); border: 1px solid var(--border);
        border-radius: 10px; padding: 1.2rem; }
.card-title { font-size: 0.78rem; text-transform: uppercase; letter-spacing:.05em;
              color: var(--muted); margin-bottom: 0.5rem; }
table { width: 100%; border-collapse: collapse; font-size: 0.875rem; }
thead th { background: var(--bg); padding: 0.5rem 0.75rem; text-align: left;
           border-bottom: 2px solid var(--border); font-weight: 600; }
tbody td { padding: 0.45rem 0.75rem; border-bottom: 1px solid var(--border);
           vertical-align: top; }
tbody tr:last-child td { border-bottom: none; }
.fn   { font-family: monospace; }
.src  { font-family: monospace; font-size: 0.8rem; color: var(--muted); }
.tag  { display: inline-block; padding: 1px 7px; border-radius: 4px;
        font-size: 0.75rem; font-weight: 600; white-space: nowrap; margin: 1px; }
.tag-a    { background: #cfe2ff; color: #084298; }
.tag-b    { background: #d1e7dd; color: #0f5132; }
.tag-both { background: #fff3cd; color: #664d03; }
.tag-tc   { background: #e2d9f3; color: #4a235a; font-family: monospace; }
.venn { display: flex; gap: 1rem; margin: 1rem 0; flex-wrap: wrap; }
.venn-box { flex: 1; min-width: 140px; border-radius: 8px;
            padding: 0.9rem 1rem; text-align: center; }
.venn-box .num { font-size: 1.8rem; font-weight: 700; }
.venn-box .lbl { font-size: 0.78rem; margin-top: 0.2rem; }
.venn-a    { background: #cfe2ff; color: #084298; }
.venn-b    { background: #d1e7dd; color: #0f5132; }
.venn-both { background: #fff3cd; color: #664d03; }
.bar-wrap  { background: var(--border); border-radius: 4px; height: 10px;
             overflow: hidden; margin-top: 4px; }
.bar       { height: 100%; border-radius: 4px; }
details summary { cursor: pointer; font-weight: 600; font-size: 0.9rem;
                  color: var(--blue); user-select: none; padding: 0.4rem 0; }
details summary:hover { text-decoration: underline; }
details[open] summary { margin-bottom: 0.6rem; }
.search-box { width: 100%; padding: 0.4rem 0.7rem; border: 1px solid var(--border);
              border-radius: 6px; font-size: 0.85rem; margin-bottom: 0.8rem; }
@media(max-width:700px) { .grid { grid-template-columns: 1fr; } }
"""

JS = """
function filterTable(inputId, tableId) {
  const q = document.getElementById(inputId).value.toLowerCase();
  document.querySelectorAll('#' + tableId + ' tbody tr').forEach(tr => {
    tr.style.display = tr.textContent.toLowerCase().includes(q) ? '' : 'none';
  });
}
"""


def pct_color(pct: float) -> str:
    if pct >= 70: return "#198754"
    if pct >= 40: return "#fd7e14"
    return "#dc3545"


def bar_html(pct: float, color: str) -> str:
    w = min(100, max(0, pct))
    return (f'<div class="bar-wrap">'
            f'<div class="bar" style="width:{w:.1f}%;background:{color}"></div>'
            f'</div>')


def summary_cards(label: str,
                  bb_data: dict[str, tuple[int, int, float]],
                  fn_data: dict[str, tuple[int, int, float]]) -> str:
    html = f'<h2>📊 {label} — Coverage Summary</h2><div class="grid">'
    for cat in CATS:
        bb_cov, bb_tot, bb_pct = bb_data.get(cat, (0, 0, 0.0))
        fn_cov, fn_tot, fn_pct = fn_data.get(cat, (0, 0, 0.0))
        html += f"""
        <div class="card">
          <div class="card-title">{cat}</div>
          <table>
            <thead><tr><th></th><th>Covered</th><th>Total</th><th>Rate</th></tr></thead>
            <tbody>
              <tr>
                <td>Basic blocks</td><td>{bb_cov}</td><td>{bb_tot}</td>
                <td style="color:{pct_color(bb_pct)}"><b>{bb_pct:.1f}%</b>
                  {bar_html(bb_pct, pct_color(bb_pct))}</td>
              </tr>
              <tr>
                <td>Functions</td><td>{fn_cov}</td><td>{fn_tot}</td>
                <td style="color:{pct_color(fn_pct)}"><b>{fn_pct:.1f}%</b>
                  {bar_html(fn_pct, pct_color(fn_pct))}</td>
              </tr>
            </tbody>
          </table>
        </div>"""
    html += "</div>"
    return html


def _fn_table(title: str, funcs: set[str],
              tid: str,
              files_a: dict[str, str],      # func -> srcfile for side A (or shared)
              files_b: dict[str, str],       # func -> srcfile for side B
              side_label: str | None,        # None = "both" table
              tag_cls:    str | None,
              tc_map:     dict[str, list[str]] | None,
              open_attr:  str = "") -> str:
    """
    Universal function table renderer.

    Columns:
      # | Function | Source File | [Exclusive to] | [Testcases]

    For "both" tables, Source File is taken from files_a (or files_b as fallback).
    For exclusive tables, Source File comes from the relevant side's dict.
    """
    iid = f"inp-{tid}"
    show_exclusive = side_label is not None
    show_tc        = tc_map is not None

    exc_hdr = "<th>Exclusive to</th>" if show_exclusive else ""
    tc_hdr  = "<th>Testcases</th>"    if show_tc        else ""

    html = f"""
    <details {open_attr}>
      <summary>{title} ({len(funcs)} functions)</summary>
      <input class="search-box" id="{iid}" type="text"
             placeholder="Search function or file name…"
             oninput="filterTable('{iid}','{tid}')">
      <table id="{tid}">
        <thead><tr><th>#</th><th>Function</th><th>Source File</th>{exc_hdr}{tc_hdr}</tr></thead>
        <tbody>
    """
    for i, fn in enumerate(sorted(funcs), 1):
        # Source file: prefer the side whose functions we're listing
        srcfile = (files_b.get(fn) or files_a.get(fn) or "")

        exc_cell = ""
        if show_exclusive:
            exc_cell = f'<td><span class="tag {tag_cls}">{side_label}</span></td>'

        tc_cell = ""
        if show_tc:
            tcs = tc_map.get(fn, [])
            tc_cell = "<td>" + " ".join(
                f'<span class="tag tag-tc">{tc}</span>' for tc in tcs
            ) + "</td>"

        html += (f'<tr>'
                 f'<td>{i}</td>'
                 f'<td class="fn">{fn}</td>'
                 f'<td class="src">{srcfile}</td>'
                 f'{exc_cell}{tc_cell}'
                 f'</tr>')

    html += "</tbody></table></details>"
    return html


def compare_section(name_a: str, name_b: str,
                    fn_a:    dict[str, set[str]],
                    fn_b:    dict[str, set[str]],
                    files_a: dict[str, dict[str, str]],
                    files_b: dict[str, dict[str, str]],
                    tc_map_b: dict[str, dict[str, list[str]]] | None) -> str:

    html = (f'<h2>🔍 Function Coverage Comparison: '
            f'<span style="color:#084298">{name_a}</span> vs '
            f'<span style="color:#0f5132">{name_b}</span></h2>')

    for cat in CATS:
        set_a  = fn_a.get(cat, set())
        set_b  = fn_b.get(cat, set())
        both   = set_a & set_b
        only_a = set_a - set_b
        only_b = set_b - set_a
        fa     = files_a.get(cat, {})
        fb     = files_b.get(cat, {})
        tc_cat = tc_map_b.get(cat) if tc_map_b else None

        html += f"<h3>Subsystem: {cat}</h3>"
        html += '<div class="venn">'
        html += (f'<div class="venn-box venn-a"><div class="num">{len(only_a)}</div>'
                 f'<div class="lbl">Only in {name_a}</div></div>')
        html += (f'<div class="venn-box venn-both"><div class="num">{len(both)}</div>'
                 f'<div class="lbl">Both</div></div>')
        html += (f'<div class="venn-box venn-b"><div class="num">{len(only_b)}</div>'
                 f'<div class="lbl">Only in {name_b}</div></div>')
        html += '</div>'

        slug = cat.replace("/", "_").replace(" ", "_")

        # Functions only in B
        if only_b:
            html += _fn_table(
                title      = f"Functions only in <b>{name_b}</b>",
                funcs      = only_b,
                tid        = f"tbl-{slug}-only-b",
                files_a    = {},
                files_b    = fb,
                side_label = name_b,
                tag_cls    = "tag-b",
                tc_map     = tc_cat,
                open_attr  = "open",
            )
        else:
            html += (f'<p style="color:var(--muted);font-size:0.85rem">'
                     f'No functions exclusive to {name_b} in this subsystem.</p>')

        # Functions only in A
        if only_a:
            html += _fn_table(
                title      = f"Functions only in <b>{name_a}</b>",
                funcs      = only_a,
                tid        = f"tbl-{slug}-only-a",
                files_a    = fa,
                files_b    = {},
                side_label = name_a,
                tag_cls    = "tag-a",
                tc_map     = None,
            )

        # Shared functions
        if both:
            html += _fn_table(
                title      = f"Functions in both",
                funcs      = both,
                tid        = f"tbl-{slug}-both",
                files_a    = fa,
                files_b    = fb,
                side_label = None,
                tag_cls    = None,
                tc_map     = None,
            )

    return html


def build_html(title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <style>{CSS}</style>
</head>
<body>
  <h1>🧪 {title}</h1>
  <p class="subtitle">KVM Coverage Analysis — arch/riscv/kvm &amp; virt/</p>
  {body}
  <script>{JS}</script>
</body>
</html>"""


def generate_report(name_a: str, name_b: str,
                    bb_a: dict, bb_b: dict,
                    fn_sum_a: dict, fn_sum_b: dict,
                    fn_a:    dict[str, set[str]],
                    fn_b:    dict[str, set[str]],
                    files_a: dict[str, dict[str, str]],
                    files_b: dict[str, dict[str, str]],
                    tc_map_b: dict | None,
                    out_path: str) -> None:
    body  = summary_cards(name_a, bb_a, fn_sum_a)
    body += summary_cards(name_b, bb_b, fn_sum_b)
    body += compare_section(name_a, name_b, fn_a, fn_b, files_a, files_b, tc_map_b)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(build_html(f"{name_a} vs {name_b}", body))
    print(f"  Written -> {out_path}")


def run(prefix: str) -> None:
    cov_out = os.path.join(prefix, "coverage", "output")
    ana_out = os.path.join(prefix, "analyze",  "output")

    print("\n[Step 4] Loading coverage data ...")

    def load(tag: str):
        bb     = parse_cov_summary(os.path.join(cov_out, f"{tag}-bb-cov.txt"))
        fn_s   = parse_cov_summary(os.path.join(cov_out, f"{tag}-functions-cov.txt"))
        fn, ff = parse_fn_cov(     os.path.join(cov_out, f"{tag}-functions-cov.txt"))
        return bb, fn_s, fn, ff

    bb_old, fn_sum_old, fn_old, files_old = load("fuzz-old")
    bb_new, fn_sum_new, fn_new, files_new = load("fuzz-new")
    bb_st,  fn_sum_st,  fn_st,  files_st  = load("selftests-kvm")

    tc_map = parse_testcase_map(
        os.path.join(cov_out, "selftests-kvm-func-testcase-map.txt")
    )
    print(f"  Loaded testcase map: "
          f"{sum(len(v) for v in tc_map.values())} functions attributed")

    print("  Generating reports ...")

    generate_report(
        "fuzz-old", "selftests-kvm",
        bb_old, bb_st, fn_sum_old, fn_sum_st,
        fn_old, fn_st, files_old, files_st,
        tc_map_b=tc_map,
        out_path=os.path.join(ana_out, "fuzz-old-selftests-kvm-compare.html"),
    )
    generate_report(
        "fuzz-new", "selftests-kvm",
        bb_new, bb_st, fn_sum_new, fn_sum_st,
        fn_new, fn_st, files_new, files_st,
        tc_map_b=tc_map,
        out_path=os.path.join(ana_out, "fuzz-new-selftests-kvm-compare.html"),
    )
    generate_report(
        "fuzz-old", "fuzz-new",
        bb_old, bb_new, fn_sum_old, fn_sum_new,
        fn_old, fn_new, files_old, files_new,
        tc_map_b=None,
        out_path=os.path.join(ana_out, "fuzz-old-fuzz-new-compare.html"),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Step 4: compare coverage and generate HTML reports"
    )
    parser.add_argument("--prefix", default=".", help="Project prefix directory")
    args = parser.parse_args()
    run(args.prefix)