#!/usr/bin/env python3
"""Command line for the application tracker, used by /apply, /outcome and the CLAUDE.md flow.

  python3 daily/tracker_cli.py migrate
      Back up job_search_tracker.csv and applied.json to daily/backups/, then give every row
      a sidecar entry and copy any posting saved only under daily/<date>/ to its archive
      folder. Safe to re-run.

  python3 daily/tracker_cli.py capture --company X --role Y [--location L] [--salary S]
                                       [--follow-up YYYY-MM-DD]
                                       [--interview-date YYYY-MM-DD --interview-format phone|video|in_person
                                        --interview-time HH:MM --interview-with NAME]
      Record the fields the CSV has no column for, on a row that already exists.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tracker  # noqa: E402


def capture(args) -> dict:
    app_id = tracker.find_id(args.company, args.role)
    changes = {}
    if args.location is not None:
        changes["location"] = args.location
    if args.salary is not None:
        changes["salary"] = args.salary
    if args.follow_up is not None:
        changes["follow_up"] = args.follow_up
    if args.interview_date:
        now = tracker.app_view(app_id)["interviews"]
        changes["interviews"] = now + [{"date": args.interview_date, "time": args.interview_time or "",
                                        "format": args.interview_format or "video",
                                        "with": args.interview_with or ""}]
    view = tracker.update(app_id, changes)
    return {"id": app_id, "status": view["status"], "follow_up": view["follow_up"]["date"],
            "job_description_saved": view["jd_saved"]}


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="tracker_cli.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate")
    cap = sub.add_parser("capture")
    cap.add_argument("--company", required=True)
    cap.add_argument("--role", required=True)
    for flag in ("--location", "--salary", "--follow-up", "--interview-date", "--interview-time",
                 "--interview-with"):
        cap.add_argument(flag)
    cap.add_argument("--interview-format", choices=tracker.FORMATS)
    args = parser.parse_args(argv)
    try:
        result = tracker.migrate() if args.cmd == "migrate" else capture(args)
    except (KeyError, ValueError, OSError) as exc:
        print(f"tracker_cli: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
