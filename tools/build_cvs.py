#!/usr/bin/env python3
"""Compile and check every CV in a folder in one call, with one short report.

Compiling, verifying and reading the logs CV by CV costs a model turn per step, and
every turn resends the whole conversation. This runs the same checks together and
prints only what a fix needs: page count, verification result, overfull lines, and
the lines either side of each page break (where a stranded employer line shows up).

    build_cvs.py daily/<date> [--only 2 5] [--pages 2] [--compiler lualatex]

It does not replace looking at the rendered page, which stays a separate step.
Exit 0: every CV passed. Exit 1: at least one needs work.
"""

import argparse
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from verify_pdf import VerificationError, verify_pdf

ROOT = Path(__file__).resolve().parent.parent
COMPILE_TIMEOUT_SECONDS = 240
OVERFULL = re.compile(r"^Overfull \\hbox \(([\d.]+)pt too wide\).*?lines? (\d+)", re.M)
TEX_ERROR = re.compile(r"^! .*$", re.M)
# Under this, an overfull line is invisible at print size. Above it, a warning: the
# master CV's own wording can overflow a little, and that must not fail every build.
OVERFULL_TOLERANCE_PT = 1.0


def parse_log(log: str) -> dict:
    """Pull errors and visible overfull lines out of a LaTeX log."""
    overfull = [
        (float(width), int(line))
        for width, line in OVERFULL.findall(log)
        if float(width) >= OVERFULL_TOLERANCE_PT
    ]
    return {"errors": TEX_ERROR.findall(log)[:3], "overfull": overfull}


def page_breaks(page_texts: list) -> list:
    """Return the last two lines of each page and the first line of the next."""
    pages = [[ln.strip() for ln in text.splitlines() if ln.strip()] for text in page_texts]
    return [
        {"page": i + 1, "ends": pages[i][-2:], "next_starts": pages[i + 1][:1]}
        for i in range(len(pages) - 1)
    ]


def read_pages(pdf: Path) -> list:
    from pypdf import PdfReader

    return [page.extract_text() or "" for page in PdfReader(str(pdf)).pages]


def build_one(tex: Path, pages: int, compiler: str) -> dict:
    """Compile `tex` beside itself, check the PDF and return a report."""
    folder, stem = tex.parent, tex.stem
    pdf = folder / f"{stem}.pdf"
    build = folder / f"build_{stem[:40]}"
    report = {"name": tex.name, "ok": False, "problems": [], "breaks": []}
    pdf.unlink(missing_ok=True)
    build.mkdir(exist_ok=True)
    try:
        try:
            subprocess.run(
                [compiler, "-interaction=nonstopmode", f"-output-directory={build.name}", tex.name],
                cwd=folder, capture_output=True, timeout=COMPILE_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            report["problems"].append(f"compile failed: {exc}")
            return report
        log_path = build / f"{stem}.log"
        log = log_path.read_text(encoding="utf-8", errors="replace") if log_path.is_file() else ""
        parsed = parse_log(log)
        report["problems"] += parsed["errors"]
        report["warnings"] = [f"overfull {width:.1f}pt at line {line}" for width, line in parsed["overfull"]]
        built = build / f"{stem}.pdf"
        if not built.is_file():
            report["problems"].append("no PDF produced")
            return report
        shutil.move(str(built), str(pdf))
    finally:
        shutil.rmtree(build, ignore_errors=True)
    try:
        verify_pdf(pdf, expected_pages=pages, ascii_dates=True)
    except VerificationError as exc:
        report["problems"].append(str(exc))
    report["breaks"] = page_breaks(read_pages(pdf))
    layout = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "verify_layout.py"), str(pdf)],
        capture_output=True, encoding="utf-8", errors="replace",
    )
    if layout.returncode == 1:
        report["problems"].append("layout: " + " ".join(layout.stdout.split())[:300])
    elif layout.returncode != 0:
        report["layout"] = "skipped (no Poppler)"
    report["ok"] = not report["problems"]
    return report


def render(report: dict) -> str:
    lines = [f"{'PASS' if report['ok'] else 'FAIL'} {report['name']}"]
    lines += [f"  problem: {p}" for p in report["problems"]]
    lines += [f"  warning: {w}" for w in report.get("warnings", [])]
    if report.get("layout"):
        lines.append(f"  layout: {report['layout']}")
    for item in report["breaks"]:
        ends = " / ".join(text[:70] for text in item["ends"])
        starts = " / ".join(text[:70] for text in item["next_starts"])
        lines.append(f"  page {item['page']} ends: {ends} || next starts: {starts}")
    return "\n".join(lines)


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Compile and check every CV in a folder.")
    parser.add_argument("folder", type=Path)
    parser.add_argument("--only", nargs="*", default=None, help="file-name prefixes, e.g. 2 5")
    parser.add_argument("--pages", type=int, default=2)
    parser.add_argument("--compiler", default="lualatex")
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args(argv)

    texs = sorted(t for t in args.folder.glob("*.tex") if not t.name.endswith(".sections.tex"))
    if args.only:
        texs = [t for t in texs if t.name.split("_", 1)[0] in args.only]
    if not texs:
        print(f"build_cvs: no .tex files in {args.folder}", file=sys.stderr)
        return 1
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        reports = list(pool.map(lambda t: build_one(t, args.pages, args.compiler), texs))
    print("\n".join(render(r) for r in reports))
    return 0 if all(r["ok"] for r in reports) else 1


if __name__ == "__main__":
    sys.exit(main())
