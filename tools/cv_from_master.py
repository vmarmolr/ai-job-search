#!/usr/bin/env python3
"""Build a tailored CV from the master CV plus only the sections that changed.

A tailored CV changes two or three sections of the master. Writing the whole file
retypes the preamble, header and untouched sections for every job, and a retyped
preamble can drift. Here the caller writes a file holding just the changed sections,
each starting at its own `\\section{Name}` line; everything else is copied from the
master byte for byte.

    cv_from_master.py --sections <n>.sections.tex --out <n>.tex [--master cv/main_example.tex]

Exit 0: written. Exit 1: nothing written (no sections, or a name the master lacks).
"""

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECTION = re.compile(r"^\\section\*?\{(.+)\}[ \t]*$", re.M)
# A banner comment before the next \section belongs to that section, not this one.
TRAILING_COMMENTS = re.compile(r"(?:^[ \t]*%.*\n|^[ \t]*\n)+\Z", re.M)


def split_sections(text: str) -> list:
    """Return [(name, start, end)] for each `\\section`, ending at the next one."""
    marks = list(SECTION.finditer(text))
    tail = text.find("\\end{document}")
    limit = tail if tail != -1 else len(text)
    return [
        (m.group(1), m.start(), marks[i + 1].start() if i + 1 < len(marks) else limit)
        for i, m in enumerate(marks)
    ]


def merge(master: str, sections: str) -> str:
    """Return `master` with each section named in `sections` replaced."""
    new = split_sections(sections)
    if not new:
        raise ValueError("no \\section{...} line in the sections file")
    if sections[: new[0][1]].strip():
        raise ValueError("text before the first \\section in the sections file")
    old = {name: (start, end) for name, start, end in split_sections(master)}
    unknown = [name for name, _, _ in new if name not in old]
    if unknown:
        raise ValueError(f"section not in the master: {', '.join(unknown)}; master has: {', '.join(old)}")
    # Replace from the end so earlier offsets stay valid.
    merged = master
    replacements = sorted(new, key=lambda item: old[item[0]][0], reverse=True)
    for name, start, end in replacements:
        old_start, old_end = old[name]
        banner = TRAILING_COMMENTS.search(master[old_start:old_end])
        keep = banner.group(0) if banner else "\n"
        merged = merged[:old_start] + sections[start:end].rstrip() + "\n" + keep + merged[old_end:]
    return merged


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Build a CV from the master plus changed sections.")
    parser.add_argument("--master", type=Path, default=ROOT / "cv" / "main_example.tex")
    parser.add_argument("--sections", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        text = merge(
            args.master.read_text(encoding="utf-8"),
            args.sections.read_text(encoding="utf-8"),
        )
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    except (OSError, ValueError) as exc:
        print(f"cv_from_master: {exc}", file=sys.stderr)
        return 1
    print(f"cv_from_master: wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
