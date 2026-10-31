"""Tracker logic: follow-up defaulting, status mapping, persistence and CSV compatibility.

Everything runs against a temporary copy of the file layout, never the real data.
"""
import csv
import importlib
import io
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "daily"))
tracker = importlib.import_module("tracker")

TODAY = date(2026, 10, 31)
HEADER = ",".join(tracker.HEADER)
JD = "A real job description. " * 20
ROW = "2026-10-20,Acme,,Data Analyst,,portal,{status},,70,{notes},,,https://example.com/job,"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(tracker.use_root, REPO)
        self.root = Path(self.tmp.name)
        (self.root / "daily").mkdir()
        tracker.use_root(self.root)

    def write_csv(self, *rows, header=HEADER):
        text = "\r\n".join([header, *rows]) + "\r\n"
        tracker.TRACKER.write_bytes(text.encode("utf-8"))

    def rows(self):
        with tracker.TRACKER.open(encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh))

    def one(self):
        return tracker.snapshot(TODAY)["applications"][0]


class StatusMapping(unittest.TestCase):
    def test_every_vocabulary_value_lands_on_one_of_the_five(self):
        expected = {
            "drafted": "applied", "applied": "applied", "interview": "interviewing",
            "offer": "offer received", "hired": "offer received", "rejected": "rejected",
            "no_response": "rejected", "no response": "rejected", "withdrawn": "withdrawn",
            "offer_declined": "withdrawn", "offer declined": "withdrawn",
        }
        for raw, stage in expected.items():
            with self.subTest(raw=raw):
                self.assertEqual(tracker.stage_of(raw), stage)
                self.assertIn(stage, tracker.STAGES)

    def test_vocabulary_matches_outcome(self):
        block = (REPO / ".claude/commands/outcome.md").read_text(encoding="utf-8")
        for raw in tracker.STAGE_OF_RAW:
            self.assertIn(f"`{raw}`", block)

    def test_unknown_value_stays_open_and_is_kept(self):
        self.assertEqual(tracker.stage_of("on hold"), "applied")
        self.assertFalse(tracker.is_final("on hold"))

    def test_legacy_space_spellings_are_final(self):
        self.assertTrue(tracker.is_final("no response"))
        self.assertTrue(tracker.is_final("offer declined"))


class FollowUp(unittest.TestCase):
    def test_default_is_seven_days_after_applying(self):
        self.assertEqual(tracker.default_follow_up("2026-10-27"), "2026-11-03")
        self.assertEqual(tracker.default_follow_up("not a date"), "")

    def info(self, raw="applied", applied="2026-10-27", override="", notes=""):
        return tracker.follow_up_info(raw, applied, override, notes, TODAY)

    def test_states(self):
        self.assertEqual(self.info(applied="2026-10-20")["state"], "overdue")
        self.assertEqual(self.info(applied="2026-10-24")["state"], "today")
        self.assertEqual(self.info(applied="2026-10-27")["state"], "soon")
        self.assertEqual(self.info(applied="2026-10-30")["state"], "later")

    def test_override_wins_and_can_be_cleared(self):
        info = self.info(override="2026-11-20")
        self.assertEqual((info["date"], info["custom"]), ("2026-11-20", True))
        self.assertEqual(self.info(override="none")["state"], "none")

    def test_nothing_due_on_drafted_or_closed(self):
        for raw in ("drafted", "rejected", "no response", "hired", "withdrawn"):
            self.assertEqual(self.info(raw=raw, applied="2026-01-01")["state"], "none", raw)

    def test_counts_outcome_markers(self):
        self.assertEqual(self.info(notes="followed up 2026-10-01; followed up 2026-10-09")["sent"], 2)


class CsvCompatibility(Base):
    def test_status_change_writes_canonical_value_and_touches_only_its_row(self):
        other = '2026-10-01,"Beta, Inc",,"Analyst, Data",,,applied,,,keep me,,,,2026-12-01'
        self.write_csv(ROW.format(status="applied", notes="n"), other)
        before = self.rows()
        tracker.update("acme_data_analyst", {"status": "interviewing"}, TODAY)
        after = self.rows()
        self.assertEqual(after[0]["status"], "interview")
        self.assertEqual(after[1], before[1])
        self.assertEqual(list(after[0]), tracker.HEADER)
        self.assertEqual(after[0]["source"], "https://example.com/job")

    def test_status_notes_stay_csv_safe(self):
        self.write_csv(ROW.format(status="applied", notes=""))
        tracker.update("acme_data_analyst", {"status": "rejected", "contact": 'Ana, "HR"\nLead'}, TODAY)
        row = self.rows()[0]
        self.assertEqual(row["notes"], "2026-10-31 tracker: status rejected")
        self.assertEqual(row["contact_person"], "Ana HR Lead")
        for ch in (",", '"', "\n"):
            self.assertNotIn(ch, row["notes"])

    def test_free_form_notes_never_reach_the_csv(self):
        self.write_csv(ROW.format(status="applied", notes="old"))
        text = 'Spoke to Ana, she said "soon"\nPrep: SQL'
        view = tracker.update("acme_data_analyst", {"notes": text}, TODAY)
        self.assertEqual(view["notes"], text)
        self.assertEqual(self.rows()[0]["notes"], "old")

    def test_a_same_stage_edit_keeps_the_raw_value(self):
        self.write_csv(ROW.format(status="no response", notes="n"), )
        tracker.update("acme_data_analyst", {"status": "rejected"}, TODAY)
        self.assertEqual(self.rows()[0]["status"], "no response")
        self.assertEqual(self.one()["status"], "rejected")

    def test_a_row_widened_by_a_stray_comma_survives_a_rewrite(self):
        bad = "2026-10-02,Gamma,,Analyst,,,applied,,,rejected, no feedback,cv.tex,,src,"
        self.write_csv(bad, ROW.format(status="applied", notes="n"))
        tracker.update("acme_data_analyst", {"status": "withdrawn"}, TODAY)
        with tracker.TRACKER.open(encoding="utf-8", newline="") as fh:
            table = list(csv.reader(fh))
        self.assertEqual(table[1], next(csv.reader(io.StringIO(bad))))

    def test_extra_columns_and_line_endings_survive(self):
        self.write_csv("2026-10-20,Acme,Data Analyst,applied,x", header="date,company,role,status,future")
        tracker.update("acme_data_analyst", {"date": "2026-10-21"}, TODAY)
        self.assertEqual(tracker.TRACKER.read_bytes().split(b"\r\n")[1], b"2026-10-21,Acme,Data Analyst,applied,x")

    def test_moving_off_drafted_sets_the_submission_date(self):
        self.write_csv(ROW.format(status="drafted", notes=""))
        tracker.update("acme_data_analyst", {"sent": True}, TODAY)
        row = self.rows()[0]
        self.assertEqual((row["status"], row["date"]), ("applied", "2026-10-31"))

    def test_rank_state_still_reads_the_file(self):
        self.write_csv(ROW.format(status="applied", notes="n"))
        tracker.add({"company": "Beta, Inc", "role": "Analyst"}, TODAY)
        sys.path.insert(0, str(REPO / "tools"))
        rank_state = importlib.import_module("rank_state")
        self.assertEqual(len(rank_state.tracker_pairs(tracker.TRACKER)), 2)


class Persistence(Base):
    def test_add_saves_row_sidecar_and_posting_with_default_follow_up(self):
        view = tracker.add({"company": "Acme", "role": "Analyst", "date": "2026-10-25", "location": "Springfield",
                            "salary": "90k", "jd": JD}, TODAY)
        self.assertEqual(view["follow_up"]["date"], "2026-11-01")
        self.assertEqual((view["location"], view["salary"]), ("Springfield", "90k"))
        self.assertTrue((tracker.ARCHIVE / "acme_analyst" / "job_posting.md").is_file())
        self.assertEqual(self.rows()[0]["status"], "applied")
        again = json.loads(tracker.STORE.read_text(encoding="utf-8"))
        self.assertEqual(again["applications"]["acme_analyst"]["salary"], "90k")

    def test_first_run_with_no_files(self):
        snap = tracker.snapshot(TODAY)
        self.assertEqual((snap["applications"], snap["summary"]["total"]), ([], 0))
        tracker.add({"company": "Acme", "role": "Analyst"}, TODAY)
        self.assertEqual(self.rows()[0]["date"], "2026-10-31")
        self.assertTrue(tracker.TRACKER.read_text(encoding="utf-8").startswith(HEADER))

    def test_duplicate_open_application_is_refused_but_reapplying_after_close_is_not(self):
        tracker.add({"company": "Acme", "role": "Analyst"}, TODAY)
        with self.assertRaises(tracker.Conflict):
            tracker.add({"company": "ACME", "role": "analyst"}, TODAY)
        tracker.update("acme_analyst", {"status": "rejected"}, TODAY)
        second = tracker.add({"company": "Acme", "role": "Analyst"}, TODAY)
        self.assertEqual(second["id"], "acme_analyst--2")

    def test_interviews_persist_sorted_and_advance_applied(self):
        tracker.add({"company": "Acme", "role": "Analyst"}, TODAY)
        interviews = [{"date": "2026-11-09", "format": "in_person"},
                      {"date": "2026-11-02", "time": "14:30", "format": "video", "with": "Ana"}]
        view = tracker.update("acme_analyst", {"interviews": interviews}, TODAY)
        self.assertEqual([i["date"] for i in view["interviews"]], ["2026-11-02", "2026-11-09"])
        self.assertEqual(view["status"], "interviewing")
        self.assertEqual(self.rows()[0]["status"], "interview")
        self.assertEqual(tracker.snapshot(TODAY)["summary"]["upcoming"][0]["with"], "Ana")

    def test_bad_input_is_refused_and_changes_nothing(self):
        tracker.add({"company": "Acme", "role": "Analyst"}, TODAY)
        before = tracker.TRACKER.read_bytes()
        for changes in ({"date": "soon"}, {"status": "ghosted"}, {"source": "javascript:alert(1)"},
                        {"interviews": [{"date": "2026-11-02", "format": "carrier pigeon"}]}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                tracker.update("acme_analyst", changes, TODAY)
        self.assertEqual(tracker.TRACKER.read_bytes(), before)

    def test_logging_a_follow_up_uses_the_outcome_marker_and_stops_at_two(self):
        tracker.add({"company": "Acme", "role": "Analyst"}, TODAY)
        first = tracker.log_follow_up("acme_analyst", TODAY)
        self.assertEqual(first["follow_up"]["date"], "2026-11-07")
        self.assertIn("followed up 2026-10-31", self.rows()[0]["notes"])
        self.assertEqual(tracker.log_follow_up("acme_analyst", TODAY)["follow_up"]["state"], "none")

    def test_details_survive_a_dashboard_untick_and_retick(self):
        self.write_csv(ROW.format(status="applied", notes="n"))
        tracker.update("acme_data_analyst", {"notes": "keep"}, TODAY)
        self.write_csv()
        self.assertEqual(tracker.snapshot(TODAY)["detached"], 1)
        self.write_csv(ROW.format(status="applied", notes="n"))
        self.assertEqual(self.one()["notes"], "keep")

    def test_a_damaged_sidecar_is_never_overwritten(self):
        self.write_csv(ROW.format(status="applied", notes="n"))
        tracker.STORE.write_text("{ not json", encoding="utf-8")
        with self.assertRaises(OSError):
            tracker.update("acme_data_analyst", {"notes": "x"}, TODAY)
        self.assertEqual(tracker.STORE.read_text(encoding="utf-8"), "{ not json")


class JobDescriptions(Base):
    def daily_job(self):
        day = tracker.DAILY / "2026-10-27"
        (day / "postings").mkdir(parents=True)
        (day / "jobs.json").write_text(json.dumps([{"n": 3, "posting": "3_acme.md"}]), encoding="utf-8")
        (day / "postings" / "3_acme.md").write_text(JD, encoding="utf-8")

    def test_missing_is_reported_not_invented(self):
        self.write_csv(ROW.format(status="applied", notes="n"))
        self.assertFalse(self.one()["jd_saved"])
        self.assertEqual(tracker.get_posting("acme_data_analyst"), "")

    def test_stub_counts_as_missing(self):
        self.write_csv(ROW.format(status="applied", notes="n"))
        folder = tracker.ARCHIVE / "acme_data_analyst"
        folder.mkdir(parents=True)
        (folder / "job_posting.md").write_text("Posting unavailable.", encoding="utf-8")
        self.assertFalse(self.one()["jd_saved"])

    def test_migration_backs_up_and_copies_from_the_daily_folder(self):
        self.daily_job()
        self.write_csv(ROW.format(status="applied", notes="from daily page 2026-10-27 #3"))
        tracker.APPLIED.write_text('{"2026-10-27#3": "2026-10-27"}', encoding="utf-8")
        before = tracker.TRACKER.read_bytes()
        report = tracker.migrate("t")
        backup = tracker.BACKUPS / "tracker_migration_t"
        self.assertEqual((backup / "job_search_tracker.csv").read_bytes(), before)
        self.assertTrue((backup / "applied.json").is_file())
        self.assertEqual(tracker.TRACKER.read_bytes(), before)
        self.assertEqual((report["csv_rows"], report["store_entries"]), (1, 1))
        self.assertEqual(report["copied_postings"], ["acme_data_analyst"])
        self.assertEqual(tracker.posting_text({"folder": "acme_data_analyst", "notes": ""}), JD.strip())

    def test_migration_is_idempotent(self):
        self.write_csv(ROW.format(status="applied", notes="n"))
        tracker.migrate("a")
        tracker.update("acme_data_analyst", {"notes": "mine"}, TODAY)
        tracker.migrate("b")
        self.assertEqual(self.one()["notes"], "mine")
        self.assertEqual(tracker.migrate("c")["missing_postings"], ["acme_data_analyst"])

    def test_pasted_posting_goes_through_the_guard_and_is_not_overwritten(self):
        self.write_csv(ROW.format(status="applied", notes="n"))
        view = tracker.add_posting("acme_data_analyst", JD + "zero​width", TODAY)
        self.assertTrue(view["jd_saved"])
        saved = tracker.get_posting("acme_data_analyst")
        self.assertIn("## posting_guard", saved)
        self.assertNotIn("​", saved)
        with self.assertRaises(tracker.Conflict):
            tracker.add_posting("acme_data_analyst", JD, TODAY)

    def test_meta_is_read_only_from_what_the_posting_says(self):
        meta = tracker.derive_meta("Analyst\nAcme · Springfield, EX\n\nThe $900-billion industry\n"
                                   "The base salary is $51,000 to $62,000 per annum. Bonus.")
        self.assertEqual(meta, {"location": "Springfield, EX", "salary": "$51,000 to $62,000 per annum"})
        self.assertEqual(tracker.derive_meta("Nothing stated here."), {"location": "", "salary": ""})


class Summary(Base):
    def test_counts_and_follow_ups_due(self):
        self.write_csv(ROW.format(status="applied", notes=""),
                       "2026-10-01,B,,R,,,rejected,,,,,,,",
                       "2026-10-30,C,,R,,,applied,,,,,,,")
        s = tracker.snapshot(TODAY)["summary"]
        self.assertEqual((s["counts"]["applied"], s["counts"]["rejected"], s["total"]), (2, 1, 3))
        self.assertEqual((s["overdue"], [a["company"] for a in s["follow_ups"]]), (1, ["Acme"]))
        self.assertEqual(sum(w["count"] for w in s["weeks"]), 3)


class Code(unittest.TestCase):
    def test_no_application_data_in_the_page_or_code(self):
        rows = list(csv.DictReader((REPO / "job_search_tracker.csv").open(encoding="utf-8"))) \
            if (REPO / "job_search_tracker.csv").is_file() else []
        for name in ("tracker.html", "tracker.js", "tracker.css", "tracker.py", "tracker_web.py", "tracker_cli.py"):
            text = (REPO / "daily" / name).read_text(encoding="utf-8")
            for row in rows:
                self.assertNotIn(row["company"], text, name)

    def test_same_slug_rule_as_the_dashboard(self):
        src = (REPO / "daily" / "server.py").read_text(encoding="utf-8")
        for line in ('re.sub(r"[^a-z0-9_]", "", "_".join(parts).lower().replace(" ", "_"))',
                     'return re.sub(r"_+", "_", s).strip("_")'):
            self.assertIn(line, src)
        self.assertEqual(tracker.slug("Novo Nordisk A/S", "ML"), "novo_nordisk_as_ml")

    def test_sidecar_is_gitignored(self):
        self.assertIn("daily/tracker_data.json", (REPO / ".gitignore").read_text(encoding="utf-8").splitlines())


class RequestGuard(unittest.TestCase):
    def test_only_local_hosts_and_origins(self):
        web = importlib.import_module("tracker_web")
        self.assertTrue(web.allowed({"Host": "127.0.0.1:8765"}))
        self.assertTrue(web.allowed({"Host": "localhost:8765", "Origin": "http://localhost:8765"}))
        self.assertFalse(web.allowed({"Host": "evil.example:8765"}))
        self.assertFalse(web.allowed({"Host": "127.0.0.1:8765", "Origin": "https://evil.example"}))


if __name__ == "__main__":
    unittest.main()
