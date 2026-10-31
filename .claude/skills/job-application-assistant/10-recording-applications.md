---
framework_version: 1.0.0
---
# Recording Applications

When the user says they applied to a job (e.g. "I applied to #3 from today", "I applied to Acme"), find it in `daily/<date>/summary.md` (search recent days if no date is given; ask only if the match is ambiguous), then:
1. **Tracker:** add a row to `job_search_tracker.csv` (header and rules per `/apply` Step 6b and the `/outcome` status vocabulary) with `status` = `applied`, `date` = the day they applied (today unless they say otherwise), `fit_rating` = the daily score, `cv_file` = the daily CV path, `source` = the posting URL, `channel` = `portal` or `online`. If a row for that company+role already exists, update it instead of adding a duplicate.
2. **Archive:** copy the saved posting `daily/<date>/postings/<n>_<slug>.md` verbatim to `documents/applications/<company>_<role>/job_posting.md`, and copy the CV (`.tex` and `.pdf`) used into the same folder as `cv_draft.tex` / `cv_draft.pdf`. Never re-fetch or reconstruct a posting; if no saved copy exists, say so.
3. Confirm in one line, and mention `/outcome <company>` for later updates (interview, offer, rejection) and `/html-report` for the dashboard.

The "I applied" checkbox on each daily page (served by `daily/server.py` at http://localhost:8765) does steps 1-2 automatically; ticks are recorded in `daily/applied.json`.

The "Top job" checkbox beside it records the jobs the user likes best in `daily/top_jobs.json`, with facts taken from the saved posting (never re-fetched; logic in `daily/top_jobs.py`). `/daily` uses the marks for up to 4 extra search queries, to score similar jobs first when there is a backlog, and for an ordering bonus of at most 8 points in `pick`. Marks never change `rank_score`, the score cut-offs or any deal-breaker, and no marks means no change. `python3 daily/daily_state.py top prefs` shows what the marks have in common. When the user says a job is a top job, run `python3 daily/daily_state.py top mark --date <date> --n <n>` (`--off` removes it).

The application tracker page (http://localhost:8765/applications, code in `daily/tracker*`) shows every row of `job_search_tracker.csv` joined with `daily/tracker_data.json`, which holds what the CSV has no column for: location, salary, interviews, follow-up date and long notes. The full job description stays in `documents/applications/<company>_<role>/job_posting.md`. To record those fields outside the page, use `python3 daily/tracker_cli.py capture` on a row that already exists. Keep the CSV's columns as they are.
