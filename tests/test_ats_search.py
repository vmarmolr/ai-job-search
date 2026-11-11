"""The feed reader filters by the shared file, survives bad feeds and fits scrape_state."""

import contextlib
import email.message
import io
import json
import sys
import tempfile
import unittest
import urllib.error
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import ats_search  # noqa: E402
import scrape_state  # noqa: E402

TODAY = date(2026, 11, 2)
RECENT = "2026-10-30T12:00:00Z"
STALE = "2026-09-01T12:00:00Z"
RECENT_MS = 1793404800000  # 2026-10-31
TITLE = "Product Insights Analyst"

FILTERS = ats_search.Filters({
    "families": {"insights": "product insight|insights? analyst", "pricing": "pricing analyst"},
    "exclude": "^data analyst\\b|\\bintern\\b",
    "locations": {
        "include": "downtown copenhagen|^copenhagen\\b|\\bcopenhagen, ?dk|\\bremote\\b",
        "exclude": "roskilde|ballerup",
        "remote_must_allow": "denmark|zealand|copenhagen|north america",
    },
})


class FakeClient:
    """Answers by URL substring; an Exception value is raised."""

    def __init__(self, routes: dict):
        self.routes, self.calls = routes, []

    def json(self, url, body=None):
        self.calls.append((url, body))
        for fragment, answer in self.routes.items():
            if fragment in url:
                if isinstance(answer, list) and answer and isinstance(answer[0], dict) and "_page" in answer[0]:
                    answer = answer[min(len([c for c in self.calls if fragment in c[0]]), len(answer)) - 1]["_page"]
                if isinstance(answer, Exception):
                    raise answer
                return answer
        raise ats_search.FeedError("HTTP 404 from test")


def search(entry, routes, days=14):
    client = FakeClient(routes)
    hits, report = ats_search.search_company(client, entry, FILTERS, TODAY, days)
    return hits, report, client


class AdapterTests(unittest.TestCase):
    def test_greenhouse(self):
        feed = {"jobs": [
            {"title": TITLE, "absolute_url": "https://job-boards.greenhouse.io/x/jobs/1",
             "location": {"name": "Copenhagen, Denmark"}, "first_published": RECENT},
            {"title": TITLE + " Old", "absolute_url": "https://job-boards.greenhouse.io/x/jobs/2",
             "location": {"name": "Copenhagen, Denmark"}, "first_published": STALE},
        ]}
        hits, report, client = search({"company": "X", "ats": "greenhouse", "slug": "x"}, {"boards-api.greenhouse.io": feed})
        self.assertEqual(hits, [{
            "title": TITLE, "company": "X", "url": "https://job-boards.greenhouse.io/x/jobs/1",
            "location": "Copenhagen, Denmark", "date": "2026-10-30", "portal": "ats-greenhouse", "source": "ats",
        }])
        self.assertEqual(report["read"], 2)
        self.assertIn("/v1/boards/x/jobs?content=true", client.calls[0][0])

    def test_lever(self):
        feed = [{
            "text": TITLE, "hostedUrl": "https://jobs.lever.co/x/abc", "createdAt": RECENT_MS,
            "country": "CA", "workplaceType": "remote",
            "categories": {"location": "Calgary", "allLocations": ["Calgary"]},
        }]
        hits, _, _ = search({"company": "X", "ats": "lever", "slug": "x"}, {"api.lever.co": feed})
        self.assertEqual(hits[0]["portal"], "ats-lever")
        self.assertEqual(hits[0]["location"], "Remote - Calgary")
        self.assertEqual(hits[0]["date"], "2026-10-31")

    def test_ashby_skips_unlisted_and_reads_secondary_locations(self):
        feed = {"jobs": [
            {"title": TITLE, "jobUrl": "https://jobs.ashbyhq.com/x/1", "location": "Vancouver",
             "secondaryLocations": [{"location": "Copenhagen, DK"}], "publishedAt": RECENT, "isListed": True},
            {"title": TITLE + " Hidden", "jobUrl": "https://jobs.ashbyhq.com/x/2", "location": "Copenhagen, DK",
             "publishedAt": RECENT, "isListed": False},
        ]}
        hits, _, _ = search({"company": "X", "ats": "ashby", "slug": "x"}, {"api.ashbyhq.com": feed})
        self.assertEqual([h["url"] for h in hits], ["https://jobs.ashbyhq.com/x/1"])
        self.assertEqual(hits[0]["location"], "Vancouver; Copenhagen, DK")

    def test_smartrecruiters_pages_and_builds_own_url(self):
        job = {"id": "7", "name": TITLE, "releasedDate": RECENT,
               "location": {"city": "Copenhagen", "country": "ca", "fullLocation": "Copenhagen, DK, Denmark"}}
        filler = [{"id": str(i), "name": "Cashier", "releasedDate": RECENT, "location": {}} for i in range(100)]
        routes = {"api.smartrecruiters.com": [
            {"_page": {"totalFound": 101, "content": filler}},
            {"_page": {"totalFound": 101, "content": [job]}},
        ]}
        hits, report, client = search({"company": "X", "ats": "smartrecruiters", "slug": "Xco"}, routes)
        self.assertEqual(report["read"], 101)
        self.assertEqual(len(client.calls), 2)
        self.assertIn("offset=100", client.calls[1][0])
        self.assertEqual(hits[0]["url"], "https://jobs.smartrecruiters.com/Xco/7")

    def workday_entry(self, **extra):
        return {"company": "X", "ats": "workday", "slug": "x", "tenant": "x", "wd": 3, "site": "Ext", **extra}

    def test_workday_pages_posts_search_and_builds_url(self):
        filler = [{"title": "Teller", "externalPath": f"/job/a/{i}", "locationsText": "Copenhagen, DK",
                   "postedOn": "Posted Today"} for i in range(20)]
        last = [{"title": TITLE, "externalPath": "/job/Copenhagen/Analyst_R1", "locationsText": "COPENHAGEN, Zealand, Denmark",
                 "postedOn": "Posted 3 Days Ago"}]
        routes = {"myworkdayjobs.com": [
            {"_page": {"total": 21, "jobPostings": filler}},
            {"_page": {"total": 0, "jobPostings": last}},
        ]}
        hits, _, client = search(self.workday_entry(search="Copenhagen"), routes)
        self.assertEqual(client.calls[0][0], "https://x.wd3.myworkdayjobs.com/wday/cxs/x/Ext/jobs")
        self.assertEqual(client.calls[0][1]["searchText"], "Copenhagen")
        self.assertEqual(client.calls[1][1]["offset"], 20)
        self.assertEqual(hits[0]["url"], "https://x.wd3.myworkdayjobs.com/Ext/job/Copenhagen/Analyst_R1")
        self.assertEqual(hits[0]["date"], "2026-10-30")

    def test_workday_opens_many_locations_only_for_matching_titles(self):
        routes = {
            "/jobs": {"total": 2, "jobPostings": [
                {"title": TITLE, "externalPath": "/job/m/One_R1", "locationsText": "3 Locations", "postedOn": "Posted Today"},
                {"title": "Teller", "externalPath": "/job/m/Two_R2", "locationsText": "3 Locations", "postedOn": "Posted Today"},
            ]},
            "/job/m/One_R1": {"jobPostingInfo": {"location": "Roskilde, DK", "additionalLocations": ["Copenhagen, DK"]}},
        }
        hits, _, client = search(self.workday_entry(), routes)
        self.assertEqual(hits[0]["location"], "Roskilde, DK; Copenhagen, DK")
        self.assertEqual(len(client.calls), 2)

    def test_workday_keeps_a_location_it_cannot_open(self):
        routes = {"/jobs": {"total": 1, "jobPostings": [
            {"title": TITLE, "externalPath": "/job/m/One_R1", "locationsText": "3 Locations", "postedOn": "Posted Today"}]}}
        hits, report, _ = search(self.workday_entry(), routes)
        self.assertEqual(hits[0]["location"], "3 Locations")
        self.assertEqual(report["status"], "ok")

    def test_workday_dates(self):
        day = ats_search.workday_day
        self.assertEqual(day("Posted Today", TODAY), TODAY)
        self.assertEqual(day("Posted Yesterday", TODAY), TODAY - timedelta(days=1))
        self.assertEqual(day("Posted 3 Days Ago", TODAY), TODAY - timedelta(days=3))
        self.assertEqual(day("Posted 30+ Days Ago", TODAY), TODAY - timedelta(days=30))
        self.assertIsNone(day("soon", TODAY))
        self.assertIsNone(day(None, TODAY))


class FilterTests(unittest.TestCase):
    def test_titles(self):
        self.assertTrue(FILTERS.title("Senior Product Insights Lead"))
        self.assertTrue(FILTERS.title("PRICING ANALYST"))
        self.assertFalse(FILTERS.title("Data Analyst, Insights Analyst pool"))
        self.assertFalse(FILTERS.title("Insights Analyst Intern"))
        self.assertFalse(FILTERS.title("Software Engineer"))

    def test_locations(self):
        for place in ("Copenhagen, DK", "COPENHAGEN, Zealand, Denmark", "Copenhagen - Nord", "Denmark, Zealand, Copenhagen",
                      "Roskilde, DK; Copenhagen, DK", "Remote - Denmark", "Copenhagen, DK (Remote)"):
            self.assertTrue(FILTERS.location(place), place)
        for place in ("Roskilde, DK", "Ballerup, Copenhagen, DK", "Vancouver, BC", "Remote - United States", "Remote", ""):
            self.assertFalse(FILTERS.location(place), place)

    def test_remote_uses_the_feed_country(self):
        self.assertTrue(FILTERS.location("Remote", "Denmark"))
        self.assertFalse(FILTERS.location("Remote", "United States"))

    def test_no_date_is_kept_as_null(self):
        feed = {"jobs": [{"title": TITLE, "absolute_url": "https://a.example/1", "location": {"name": "Copenhagen, DK"}}]}
        hits, _, _ = search({"company": "X", "ats": "greenhouse", "slug": "x"}, {"greenhouse": feed})
        self.assertIsNone(hits[0]["date"])

    def test_patterns_come_from_the_file_at_run_time(self):
        spec = json.loads(ats_search.TITLES.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "titles.json"
            spec["families"] = {"only": "zebra wrangler"}
            path.write_text(json.dumps(spec), encoding="utf-8")
            filters = ats_search.load_filters(path)
        self.assertTrue(filters.title("Zebra Wrangler"))
        self.assertFalse(filters.title(TITLE))

    def test_the_real_filter_file_loads(self):
        self.assertTrue(ats_search.load_filters().title(TITLE))

    def test_a_posting_url_that_is_not_web_is_dropped(self):
        feed = {"jobs": [{"title": TITLE, "absolute_url": "javascript:alert(1)", "location": {"name": "Copenhagen, DK"}}]}
        hits, _, _ = search({"company": "X", "ats": "greenhouse", "slug": "x"}, {"greenhouse": feed})
        self.assertEqual(hits, [])

    def test_description_links_never_reach_the_output(self):
        feed = {"jobs": [{"title": TITLE, "absolute_url": "https://a.example/1", "location": {"name": "Copenhagen, DK"},
                          "content": '<a href="https://evil.example/x">apply</a>', "first_published": RECENT}]}
        hits, _, client = search({"company": "X", "ats": "greenhouse", "slug": "x"}, {"greenhouse": feed})
        self.assertNotIn("evil.example", json.dumps(hits))
        self.assertEqual(len(client.calls), 1)


class FailureTests(unittest.TestCase):
    def test_one_failure_does_not_stop_the_run(self):
        good = {"jobs": [{"title": TITLE, "absolute_url": "https://a.example/1", "location": {"name": "Copenhagen, DK"}}]}
        client = FakeClient({"boards/bad": ats_search.FeedError("HTTP 404"), "boards/good": good})
        companies = [{"company": "Bad", "ats": "greenhouse", "slug": "bad"},
                     {"company": "Unknown", "ats": "oracle", "slug": "u"},
                     {"company": "Good", "ats": "greenhouse", "slug": "good"}]
        with contextlib.redirect_stderr(io.StringIO()) as err:
            hits, reports = ats_search.run(client, companies, FILTERS, TODAY, 14)
        self.assertEqual([h["company"] for h in hits], ["Good"])
        self.assertEqual([r["status"] for r in reports], ["failed", "failed", "ok"])
        self.assertEqual(len(err.getvalue().strip().splitlines()), 3)

    def test_rate_limit_is_recorded_without_retry(self):
        hits, report, client = search({"company": "X", "ats": "lever", "slug": "x"},
                                      {"lever": ats_search.RateLimited("429 from api.lever.co")})
        self.assertEqual(report["status"], "rate_limited")
        self.assertEqual(hits, [])
        self.assertEqual(len(client.calls), 1)

    def test_rate_limit_mid_paging_keeps_earlier_hits(self):
        first = [{"title": TITLE, "externalPath": f"/job/a/{i}", "locationsText": "Copenhagen, DK",
                  "postedOn": "Posted Today"} for i in range(20)]
        routes = {"myworkdayjobs.com": [
            {"_page": {"total": 40, "jobPostings": first}},
            {"_page": ats_search.RateLimited("429")},
        ]}
        hits, report, client = search(
            {"company": "X", "ats": "workday", "slug": "x", "tenant": "x", "wd": 3, "site": "Ext"}, routes)
        self.assertEqual(len(hits), 20)
        self.assertEqual(report["status"], "rate_limited")
        self.assertEqual(len(client.calls), 2)

    def test_malformed_feed_is_a_failure(self):
        hits, report, _ = search({"company": "X", "ats": "greenhouse", "slug": "x"}, {"greenhouse": {"unexpected": 1}})
        self.assertEqual((hits, report["status"]), ([], "failed"))


class ClientTests(unittest.TestCase):
    @staticmethod
    def http_error(code):
        return urllib.error.HTTPError("https://h.example/", code, "x", email.message.Message(), io.BytesIO())

    def client(self, answer):
        def opener(request, timeout):
            self.request, self.timeout = request, timeout
            if isinstance(answer, Exception):
                raise answer
            return answer
        return ats_search.Client(opener=opener, sleep=lambda s: None)

    def test_429_raises_rate_limited(self):
        with self.assertRaises(ats_search.RateLimited):
            self.client(self.http_error(429)).json("https://h.example/")

    def test_404_timeout_and_junk_raise_feed_error(self):
        for answer in (self.http_error(404), TimeoutError("timed out"), urllib.error.URLError("dns"),
                       io.BytesIO(b"<html>blocked</html>")):
            with self.assertRaises(ats_search.FeedError):
                self.client(answer).json("https://h.example/")

    def test_post_body_and_timeout(self):
        client = self.client(io.BytesIO(b'{"ok": 1}'))
        self.assertEqual(client.json("https://h.example/", {"a": 1}), {"ok": 1})
        self.assertEqual(self.request.get_method(), "POST")
        self.assertEqual(self.request.data, b'{"a": 1}')
        self.assertEqual(self.timeout, ats_search.TIMEOUT_SECONDS)

    def test_waits_between_requests_to_one_host_only(self):
        slept, now = [], [100.0]
        client = ats_search.Client(opener=lambda r, timeout: io.BytesIO(b"{}"), sleep=slept.append,
                                   clock=lambda: now[0], delay=0.5)
        client.json("https://a.example/1")
        client.json("https://b.example/1")
        self.assertEqual(slept, [])
        client.json("https://a.example/2")
        self.assertEqual(slept, [0.5])


class ContractTests(unittest.TestCase):
    hit = {"title": TITLE, "company": "X", "url": "https://a.example/1", "location": "Copenhagen, DK",
           "date": None, "portal": "ats-lever", "source": "ats"}

    def test_scrape_state_selects_the_hits(self):
        selected, counts = scrape_state.select([self.hit], {}, set(), strict=True)
        self.assertEqual(selected, [self.hit])
        self.assertEqual(counts["invalid"], [])

    def test_company_file_entries_are_runnable(self):
        data = json.loads(ats_search.COMPANIES.read_text(encoding="utf-8"))
        for entry in data["companies"]:
            self.assertIn(entry["ats"], ats_search.ADAPTERS)
            self.assertTrue(entry["company"] and entry["slug"])
            if entry["ats"] == "workday":
                self.assertTrue(entry["tenant"] and entry["site"] and isinstance(entry["wd"], int))
        for entry in data["unmapped"]:
            self.assertTrue(entry["company"] and entry["reason"])

    def test_main_writes_hits_and_one_json_summary(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            companies = root / "c.json"
            companies.write_text('{"companies": []}', encoding="utf-8")
            out = root / "sub" / "hits.json"
            with contextlib.redirect_stdout(io.StringIO()) as stdout:
                code = ats_search.main(["--companies", str(companies), "--out", str(out)])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out.read_text(encoding="utf-8")), [])
            self.assertEqual(json.loads(stdout.getvalue())["hits"], 0)


if __name__ == "__main__":
    unittest.main()
