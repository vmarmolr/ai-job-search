#!/usr/bin/env python3
"""Fetch one posting, gate it and save it, so no agent has to carry the text.

`/daily` used to dispatch a `posting-fetcher` agent per pick and then retype each
returned posting into a file. For a host with an installed portal CLI none of that
needs a model: this script runs the CLI's `detail` command, passes the body through
`posting_guard.guard()`, writes the cleaned text and prints one JSON line.

    fetch_posting.py --url <URL> --out daily/<date>/postings/<n>_<slug>.md
    fetch_posting.py --in job_scraper/postings/indeed/<key>.md --out <same>
    fetch_posting.py --picks daily/<date>/picks.json

--picks does every pick in one call: it saves each to `postings/<n>_<slug>.md` beside
the file and records `n`, `slug`, `cv`, `posting`, `posting_guard` and any `fetch_error`
there. A posting already saved is gated again, not refetched, so a rerun is safe.

Exit 0: saved (check `guard` in the JSON line). Exit 1: not retrieved, nothing was
written; the caller falls back to the `posting-fetcher` agent's full escalation order.
With --picks, exit 1 means at least one pick failed; the printed lines say which.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

from posting_guard import guard

ROOT = Path(__file__).resolve().parent.parent
MIN_POSTING_CHARS = 200
TIMEOUT_SECONDS = 90
SKILLS = ROOT / ".agents" / "skills"


def portal_for(url: str, skills: Path = SKILLS):
    """Return the portal CLI that serves `url`, or None: linkedin.com -> linkedin-search."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    labels = parts.hostname.lower().split(".")
    if len(labels) < 2 or not re.fullmatch(r"[a-z0-9-]+", labels[-2]):
        return None
    name = f"{labels[-2]}-search"
    return name if (skills / name / "cli" / "src" / "cli.ts").is_file() else None


def run_detail(url: str, portal: str) -> str:
    """Return the CLI's plain-text body for `url`; raise RuntimeError on failure."""
    command = ["bun", "run", f".agents/skills/{portal}/cli/src/cli.ts", "detail", url, "--format", "plain"]
    try:
        done = subprocess.run(
            command, cwd=ROOT, capture_output=True, encoding="utf-8", errors="replace",
            timeout=TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"{portal} detail failed: {exc}") from exc
    if done.returncode != 0:
        raise RuntimeError(f"{portal} detail exited {done.returncode}: {done.stderr.strip()[:200]}")
    return done.stdout


def save(raw: str, out: Path) -> dict:
    """Gate `raw`, write the cleaned text to `out` and return the report."""
    cleaned, findings = guard(raw, "text")
    if len(cleaned.strip()) < MIN_POSTING_CHARS:
        raise RuntimeError(f"only {len(cleaned.strip())} characters came back, not a posting")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(cleaned + "\n", encoding="utf-8")
    return {"ok": True, "out": out.as_posix(), "chars": len(cleaned), "guard": findings["verdict"]}


def fetch_pick(pick: dict, folder: Path, indeed: Path) -> dict:
    """Save one pick's posting and return the report."""
    out = folder / "postings" / f"{pick['n']}_{pick['slug']}.md"
    saved_copy = indeed / f"{pick['key']}.md"
    if out.is_file():
        raw = out.read_text(encoding="utf-8")
    elif saved_copy.is_file():
        raw = saved_copy.read_text(encoding="utf-8")
    else:
        portal = portal_for(pick["url"])
        if portal is None:
            raise RuntimeError("no installed portal CLI for this host")
        raw = run_detail(pick["url"], portal)
    return save(raw, out)


def run_picks(path: Path, indeed: Path = ROOT / "job_scraper" / "postings" / "indeed") -> bool:
    """Do every pick in `path` and record the results there; True if all were saved."""
    data = json.loads(path.read_text(encoding="utf-8"))
    all_saved = True
    for n, pick in enumerate(data["picks"], start=1):
        slug = pick["key"].replace("-", "_")
        pick.update(n=n, slug=slug, cv=f"{n}_{slug}.pdf", posting=f"{n}_{slug}.md")
        pick.pop("fetch_error", None)
        try:
            report = fetch_pick(pick, path.parent, indeed)
            pick["posting_guard"] = report["guard"]
            print(f"{n} ok {report['guard']}")
        except (OSError, RuntimeError) as exc:
            pick["fetch_error"] = str(exc)
            all_saved = False
            print(f"{n} FAILED {pick['url']} -> postings/{n}_{slug}.md: {exc}")
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return all_saved


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Fetch one posting, gate it and save it.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--url", help="posting URL on a host with an installed portal CLI")
    source.add_argument("--in", dest="infile", type=Path, help="saved copy to gate instead of fetching")
    source.add_argument("--picks", type=Path, help="the day's picks.json: do every pick")
    parser.add_argument("--out", type=Path, help="where to write the cleaned text")
    args = parser.parse_args(argv)
    if args.picks is not None:
        return 0 if run_picks(args.picks) else 1
    if args.out is None:
        parser.error("--out is required with --url or --in")

    try:
        if args.infile is not None:
            raw = args.infile.read_text(encoding="utf-8")
        else:
            portal = portal_for(args.url)
            if portal is None:
                raise RuntimeError("no installed portal CLI for this host")
            raw = run_detail(args.url, portal)
        report = save(raw, args.out)
    except (OSError, RuntimeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
