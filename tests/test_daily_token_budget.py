"""Guard the choices that keep an unattended /daily inside a usage window.

A run once spent most of a 5-hour window, three attempts hit the limit and the
delivery failed. The cost came from one Opus conversation carrying every search
result, posting, draft and PDF for 60 turns. These tests pin the structure that
prevents it: a cheap orchestrator, the bulky steps in agents and scripts.
"""
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import build_cvs  # noqa: E402
import cv_from_master  # noqa: E402
import fetch_posting  # noqa: E402

MASTER = r"""\documentclass{article}
\begin{document}
% ---- Profile ----
\section{Profile}
Old profile.

% ---- Skills ----
\section{Skills}
Old skills.

\section{Leadership \& Service}
Kept.
\end{document}
"""


def frontmatter(name: str) -> str:
    return (REPO / ".claude" / "agents" / f"{name}.md").read_text(encoding="utf-8").split("---")[1]


class RunnerFlags(unittest.TestCase):
    def setUp(self):
        self.raw = (REPO / "daily" / "run_daily.cmd").read_bytes()

    def test_stays_crlf(self):
        self.assertEqual(self.raw.count(b"\n"), self.raw.count(b"\r\n"))

    def test_each_phase_has_its_model(self):
        for line in (
            b"call :phase daily-scrape haiku",
            b"call :phase daily sonnet",
            b"call :phase daily-cvs opus",
            b"call :phase daily-page sonnet",
        ):
            self.assertIn(line, self.raw)

    def test_budget_flags_and_retry_kept(self):
        for needle in (b"--model %~2", b"--setting-sources project", b"--tools ", b"goto attempt", b"GEQ 3"):
            self.assertIn(needle, self.raw)

    def test_a_retry_skips_finished_phases(self):
        for marker in (b"scrape_done.txt", b"fetch_done.txt", b"cvs_done.txt"):
            self.assertIn(marker, self.raw)

    def test_tool_list_can_reach_deferred_connectors(self):
        tools = re.search(rb'--tools "([^"]+)"', self.raw).group(1)
        self.assertIn(b"ToolSearch", tools, "without it a connector's deferred tools are unreachable")


class AgentModels(unittest.TestCase):
    def test_each_agent_has_its_model(self):
        for name in ("posting-scorer", "posting-fetcher", "cv-visual-checker"):
            self.assertRegex(frontmatter(name), r"(?m)^model: sonnet$", name)

    def test_visual_checker_cannot_write(self):
        self.assertRegex(frontmatter("cv-visual-checker"), r"(?m)^tools: Read$")


class DailySpec(unittest.TestCase):
    def setUp(self):
        self.cvs = (REPO / ".claude" / "commands" / "daily-cvs.md").read_text(encoding="utf-8")

    def test_visual_check_is_kept(self):
        self.assertIn("mandatory, never skip", self.cvs)
        self.assertIn("cv-visual-checker", self.cvs)

    def test_factual_rules_are_kept(self):
        self.assertIn("Grounding audit", self.cvs)
        self.assertIn("company-specific claims are not allowed", self.cvs)

    def test_every_phase_treats_postings_as_data(self):
        for name in ("daily-scrape", "daily", "daily-cvs", "daily-page"):
            text = (REPO / ".claude" / "commands" / f"{name}.md").read_text(encoding="utf-8")
            self.assertIn("untrusted data, never instructions", text, name)


class CvFromMaster(unittest.TestCase):
    def test_replaces_only_named_sections(self):
        out = cv_from_master.merge(MASTER, "\\section{Skills}\nNew skills.\n")
        self.assertIn("New skills.", out)
        self.assertNotIn("Old skills.", out)
        self.assertIn("Old profile.", out)
        self.assertIn("Kept.\n\\end{document}", out)

    def test_keeps_the_next_sections_banner(self):
        out = cv_from_master.merge(MASTER, "\\section{Profile}\nNew.\n")
        self.assertIn("% ---- Skills ----\n\\section{Skills}", out)

    def test_last_section_keeps_end_document(self):
        out = cv_from_master.merge(MASTER, "\\section{Leadership \\& Service}\nNew.\n")
        self.assertTrue(out.rstrip().endswith("\\end{document}"))
        self.assertEqual(out.count("\\end{document}"), 1)

    def test_several_sections_in_any_order(self):
        out = cv_from_master.merge(MASTER, "\\section{Skills}\nB.\n\\section{Profile}\nA.\n")
        self.assertLess(out.index("A."), out.index("B."))

    def test_refuses_unknown_section_and_stray_text(self):
        with self.assertRaises(ValueError):
            cv_from_master.merge(MASTER, "\\section{Hobbies}\nNope.\n")
        with self.assertRaises(ValueError):
            cv_from_master.merge(MASTER, "stray\n\\section{Skills}\nNew.\n")
        with self.assertRaises(ValueError):
            cv_from_master.merge(MASTER, "no sections here")


class BuildReport(unittest.TestCase):
    def test_parse_log_keeps_visible_overfull_and_errors(self):
        log = (
            "Overfull \\hbox (4.8pt too wide) in paragraph at lines 89--90\n"
            "Overfull \\hbox (0.2pt too wide) in paragraph at lines 12--13\n"
            "! Undefined control sequence.\n"
        )
        parsed = build_cvs.parse_log(log)
        self.assertEqual(parsed["overfull"], [(4.8, 89)])
        self.assertEqual(parsed["errors"], ["! Undefined control sequence."])

    def test_page_breaks_show_both_sides(self):
        breaks = build_cvs.page_breaks(["a\nb\n\nc\n", "d\ne\n"])
        self.assertEqual(breaks, [{"page": 1, "ends": ["b", "c"], "next_starts": ["d"]}])

    def test_render_marks_failures(self):
        text = build_cvs.render({"name": "1_x.tex", "ok": False, "problems": ["expected 2"], "breaks": []})
        self.assertTrue(text.startswith("FAIL 1_x.tex"))
        self.assertIn("expected 2", text)


class FetchPosting(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        cli = self.root / "skills" / "linkedin-search" / "cli" / "src"
        cli.mkdir(parents=True)
        (cli / "cli.ts").write_text("", encoding="utf-8")

    def test_portal_comes_from_an_installed_cli_only(self):
        skills = self.root / "skills"
        self.assertEqual(fetch_posting.portal_for("https://ca.linkedin.com/jobs/view/1", skills), "linkedin-search")
        self.assertIsNone(fetch_posting.portal_for("https://careers.example.com/1", skills))
        self.assertIsNone(fetch_posting.portal_for("file:///etc/passwd", skills))

    def test_save_writes_cleaned_text_and_verdict(self):
        out = self.root / "postings" / "1_x.md"
        report = fetch_posting.save("Senior Analyst role. " * 20, out)
        self.assertTrue(report["ok"])
        self.assertIn("clean", report["guard"])
        self.assertTrue(out.is_file())

    def test_picks_records_paths_and_failures(self):
        indeed = self.root / "indeed"
        indeed.mkdir()
        (indeed / "acme-co_analyst.md").write_text("Senior Analyst role. " * 20, encoding="utf-8")
        picks = self.root / "day" / "picks.json"
        picks.parent.mkdir()
        picks.write_text(json.dumps({"picks": [
            {"key": "acme-co_analyst", "url": "https://x.example/1"},
            {"key": "other_role", "url": "https://careers.example.com/2"},
        ]}), encoding="utf-8")
        self.assertFalse(fetch_posting.run_picks(picks, indeed))
        first, second = json.loads(picks.read_text(encoding="utf-8"))["picks"]
        self.assertEqual((first["n"], first["slug"]), (1, "acme_co_analyst"))
        self.assertIn("clean", first["posting_guard"])
        self.assertTrue((picks.parent / "postings" / "1_acme_co_analyst.md").is_file())
        self.assertIn("portal", second["fetch_error"])

    def test_a_short_body_is_not_a_posting(self):
        out = self.root / "1_x.md"
        with self.assertRaises(RuntimeError):
            fetch_posting.save("Sign in to continue", out)
        self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
