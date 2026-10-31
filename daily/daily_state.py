"""State helper for /daily: pick today's jobs and remember what was delivered.

  pick   print the best ranked, not-yet-delivered jobs as JSON (no state change)
  mark   record delivered job keys so they are never sent again
  top    the "Top job" marks: prefs | boost | candidates | mark (logic in daily/top_jobs.py)

seen_jobs.json is read only; delivery history lives in daily/delivered.json.
"""

import argparse
import csv
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

import top_jobs

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "job_scraper" / "seen_jobs.json"
TRACKER = ROOT / "job_search_tracker.csv"
DELIVERED = Path(__file__).resolve().parent / "delivered.json"

FIELDS = ("title", "company", "url", "location", "rank_score", "rank_verdict", "deadline",
          "posted_date", "location_verdict", "language_gate", "language_note", "guard",
          "strengths", "gaps")

# Optional focus roles: one title fragment per line, e.g. "data engineer" ('#' starts a comment).
# Matched on the job title; focus roles fill the page first. Without the file every role counts.
FOCUS_FILE = Path(__file__).resolve().parent / "focus_roles.txt"


def focus_pattern() -> re.Pattern | None:
    if not FOCUS_FILE.is_file():
        return None
    lines = (line.split("#")[0].strip() for line in FOCUS_FILE.read_text(encoding="utf-8").splitlines())
    terms = [re.escape(line) for line in lines if line]
    return re.compile("|".join(terms), re.IGNORECASE) if terms else None


def load_json(path: Path, default):
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def tracker_pairs() -> set[tuple[str, str]]:
    if not TRACKER.is_file():
        return set()
    with TRACKER.open(encoding="utf-8", newline="") as fh:
        return {(r.get("company", "").strip().lower(), r.get("role", "").strip().lower())
                for r in csv.DictReader(fh)}


def cmd_pick(args) -> None:
    doc = load_json(STATE, None)
    if doc is None:
        sys.exit(f"{STATE} not found - run /scrape first")
    seen = doc.get("seen", doc) if isinstance(doc, dict) else {}
    delivered = load_json(DELIVERED, {})
    applied = tracker_pairs()
    today = date.today().isoformat()
    focus = focus_pattern()

    pool = []
    for key, e in seen.items():
        if not isinstance(e, dict) or e.get("status") != "ranked" or key in delivered:
            continue
        if e.get("location_verdict") == "FAIL" or e.get("language_gate") == "FAIL":
            continue
        dl = e.get("deadline")
        if isinstance(dl, str) and len(dl) == 10 and dl < today:
            continue
        if (str(e.get("company", "")).strip().lower(), str(e.get("title", "")).strip().lower()) in applied:
            continue
        score = e.get("rank_score")
        if not isinstance(score, (int, float)):
            continue
        pool.append({"key": key, "focus": focus is None or bool(focus.search(str(e.get("title", "")))),
                     **{f: e.get(f) for f in FIELDS}})

    # Top job marks only reorder: every filter above and the score gates below read the real rank_score.
    marks = top_jobs.load_marks()
    for j in pool:
        points, like = top_jobs.boost(j, marks)
        if points:
            j.update(top_boost=points, similar_to=like)

    # Focus roles first whatever their score; other roles only fill what is left, at most --other-max.
    pool.sort(key=lambda j: (not j["focus"], -(j["rank_score"] + j.get("top_boost", 0))))
    good = [j for j in pool if j["rank_score"] >= args.threshold]
    picks = [j for j in good if j["focus"]][: args.max]
    picks += [j for j in good if not j["focus"]][: min(args.other_max, args.max - len(picks))]
    # Top up to --min with the next best jobs above --floor, labelled below threshold.
    if len(picks) < args.min:
        extra = [j for j in pool if args.floor <= j["rank_score"] < args.threshold]
        for j in extra[: args.min - len(picks)]:
            picks.append({**j, "below_threshold": True})
    result = {"picks": picks, "available": len(pool)}
    if getattr(args, "out", None):
        Path(args.out).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps({"picks": len(picks), "available": len(pool), "out": args.out}))
        return
    json.dump(result, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


def cmd_mark(args) -> None:
    delivered = load_json(DELIVERED, {})
    for key in filter(None, (k.strip() for k in args.keys.split("|"))):
        delivered.setdefault(key, args.date)
    DELIVERED.write_text(json.dumps(delivered, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"delivered.json now holds {len(delivered)} jobs")


def cmd_top(args) -> None:
    marks = top_jobs.load_marks()
    if args.action == "prefs":
        queries = ROOT / ".claude" / "skills" / "job-scraper" / "search-queries.md"
        # Only what a default run searches counts as covered: Priority 4 on runs only when asked.
        default = queries.read_text(encoding="utf-8").split("### Priority 4")[0] if queries.is_file() else ""
        out = top_jobs.preferences(marks, default)
    elif args.action == "boost":
        doc = load_json(STATE, {})
        seen = doc.get("seen", doc)
        keys = filter(None, (k.strip() for k in args.keys.split("|")))
        out = {k: dict(zip(("top_boost", "similar_to"), top_jobs.boost(seen.get(k, {}), marks))) for k in keys}
    elif args.action == "candidates":
        run = subprocess.run([sys.executable, "tools/rank_state.py", "candidates", "--limit", "0"], cwd=ROOT,
                             capture_output=True, encoding="utf-8")
        if run.returncode:
            sys.exit(run.stderr or run.stdout)
        out = top_jobs.order_candidates(json.loads(run.stdout), marks, args.limit)
    else:
        try:
            top_jobs.set_mark(args.date, args.n, not args.off)
        except ValueError as exc:
            sys.exit(str(exc))
        out = {"marks": len(top_jobs.load_marks())}
    print(json.dumps(out, indent=2))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    pick = sub.add_parser("pick")
    pick.add_argument("--min", type=int, default=5)
    pick.add_argument("--max", type=int, default=10)
    pick.add_argument("--threshold", type=float, default=45, help="Moderate Fit and above")
    pick.add_argument("--floor", type=float, default=30, help="lowest score used to top up to --min")
    pick.add_argument("--other-max", type=int, default=3, help="most non-focus roles per day")
    pick.add_argument("--out", help="write the picks here and print only the counts")
    pick.set_defaults(func=cmd_pick)
    mark = sub.add_parser("mark")
    mark.add_argument("--keys", required=True, help="job keys separated by |")
    mark.add_argument("--date", default=date.today().isoformat())
    mark.set_defaults(func=cmd_mark)
    top = sub.add_parser("top", help="Top job marks and what they derive")
    actions = top.add_subparsers(dest="action", required=True)
    actions.add_parser("prefs", help="what the marks have in common, plus extra search queries")
    boost = actions.add_parser("boost", help="ordering bonus per job key; rank_score is never changed")
    boost.add_argument("--keys", required=True, help="job keys separated by |")
    cands = actions.add_parser("candidates", help="rank_state.py candidates, most similar jobs first")
    cands.add_argument("--limit", type=int, default=25)
    tick = actions.add_parser("mark", help="same as the checkbox on the page")
    tick.add_argument("--date", required=True, help="page date, e.g. 2026-10-29 or 2026-10-29-2")
    tick.add_argument("--n", required=True, type=int, help="card number")
    tick.add_argument("--off", action="store_true", help="remove the mark")
    top.set_defaults(func=cmd_top)
    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
