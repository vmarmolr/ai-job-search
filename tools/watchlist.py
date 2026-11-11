#!/usr/bin/env python3
"""Read the user's own watchlist: extra companies and positions, kept in a plain Markdown note.

    ## Companies
    - Acme Research
    - Initech | https://jobs.ashbyhq.com/initech

    ## Positions
    - Pricing Analyst

The note is found through, in order: $JOB_WATCHLIST, the path written in
job_scraper/watchlist_path.txt, job_scraper/watchlist.md. A missing note means an empty
watchlist, never an error. Headings are matched loosely (English or Spanish); a bullet
struck through with ~~ or an unticked `- [ ]` box is skipped.

A position is searched on every source and always counts as a target title, even one the
default filters drop. A company becomes a target company; when its careers URL is a
Greenhouse, Lever, Ashby, SmartRecruiters or Workday board it is also read as a feed.

    watchlist.py        print the parsed watchlist as JSON (the scrape skill reads this)
"""

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
POINTER = ROOT / "job_scraper" / "watchlist_path.txt"
DEFAULT = ROOT / "job_scraper" / "watchlist.md"

_BULLET = re.compile(r"^\s*[-*+]\s+(?:\[(?P<box>[ xX])\]\s+)?(?P<text>.+?)\s*$")
_URL = re.compile(r"https?://[^\s)>\]|]+")
_FEEDS = [  # careers URL -> ats_companies.json entry
    (re.compile(r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board\?for=)?([\w-]+)"),
     lambda m: {"ats": "greenhouse", "slug": m[1]}),
    (re.compile(r"jobs\.lever\.co/([\w-]+)"), lambda m: {"ats": "lever", "slug": m[1]}),
    (re.compile(r"jobs\.ashbyhq\.com/([\w.-]+)"), lambda m: {"ats": "ashby", "slug": m[1]}),
    (re.compile(r"(?:jobs|careers)\.smartrecruiters\.com/([\w-]+)"), lambda m: {"ats": "smartrecruiters", "slug": m[1]}),
    (re.compile(r"([\w-]+)\.wd(\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([\w-]+)"),
     lambda m: {"ats": "workday", "slug": m[1], "tenant": m[1], "wd": int(m[2]), "site": m[3]}),
]


def path() -> Path:
    if os.environ.get("JOB_WATCHLIST"):
        return Path(os.environ["JOB_WATCHLIST"])
    try:
        pointed = POINTER.read_text(encoding="utf-8").strip()
        if pointed:
            return Path(pointed)
    except OSError:
        pass
    return DEFAULT


def feed(url: str) -> dict | None:
    for pattern, build in _FEEDS:
        match = pattern.search(url or "")
        if match:
            return build(match)
    return None


def parse(text: str) -> dict:
    companies, titles, section = [], [], None
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            head = line.lower()
            section = ("companies" if re.search(r"compan|empres", head) else
                       "titles" if re.search(r"posi|title|puesto|rol", head) else None)
            continue
        match = _BULLET.match(line)
        if not section or not match or match["box"] == " " or match["text"].startswith("~~"):
            continue
        text_ = re.sub(r"\[([^\]]*)\]\(([^)]*)\)", r"\1 \2", match["text"])  # [name](url) -> name url
        url = _URL.search(text_)
        name = _URL.sub("", text_).strip(" |:-–—\t")
        if not name:
            continue
        if section == "titles":
            titles.append(name)
        else:
            entry = {"company": name, "url": url[0] if url else None}
            entry["feed"] = feed(entry["url"])
            companies.append(entry)
    return {"companies": companies, "titles": titles}


def load() -> dict:
    try:
        return parse(path().read_text(encoding="utf-8-sig"))
    except OSError:
        return {"companies": [], "titles": []}


def merge(spec: dict, watch: dict | None = None) -> dict:
    """target-titles.json plus the watchlist: `watchlist` title pattern, wider target_companies."""
    watch = load() if watch is None else watch
    spec = dict(spec)
    if watch["titles"]:
        spec["watchlist"] = "|".join(re.escape(t) for t in watch["titles"])
    names = [re.escape(c["company"]) for c in watch["companies"]]
    if names:
        spec["target_companies"] = "|".join(filter(None, [spec.get("target_companies")] + names))
    return spec


def feeds(known: list[dict], watch: dict | None = None) -> list[dict]:
    """ats_companies entries for watchlist companies whose URL is a readable board, minus known ones."""
    watch = load() if watch is None else watch
    have = {str(c.get("company")).lower() for c in known}
    return [{"company": c["company"], **c["feed"]} for c in watch["companies"]
            if c["feed"] and c["company"].lower() not in have]


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps({"file": str(path()), **load()}, indent=2, ensure_ascii=False))
