"""The watchlist note adds companies and positions without touching target-titles.json."""

import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import ats_search  # noqa: E402
import watchlist  # noqa: E402

NOTE = """---
summary: x
---
## Companies
- Acme Research
- [x] Initech | https://jobs.ashbyhq.com/initech
- [Hooli](https://hooli.wd3.myworkdayjobs.com/en-US/Hooli_Careers)
- [ ] Unticked
- ~~Dropped~~
## Posiciones
- Data Analyst
## Notes
- not a title
"""
SPEC = {"families": {"a": "insights"}, "exclude": "^data analyst", "target_companies": "globex",
        "locations": {"include": "copenhagen", "exclude": "$^", "remote_must_allow": "denmark"}}
CARD = '''<div class="organic-job odd"><h2><a class="lk-job-title" data-url="spl/x-1?imo=1" href="#!" title="Insights &amp; Analyst">t</a></h2>
<a class="employer lk-employer" href="#!">Acme</a><span class="location"> <span>Copenhagen, DK</span></span>
<a class="lk lastseen" href="#!">3 days ago</a></div>'''


class WatchlistTest(unittest.TestCase):
    def test_parse(self):
        watch = watchlist.parse(NOTE)
        self.assertEqual(watch["titles"], ["Data Analyst"])
        self.assertEqual([c["company"] for c in watch["companies"]], ["Acme Research", "Initech", "Hooli"])
        self.assertIsNone(watch["companies"][0]["feed"])
        self.assertEqual(watch["companies"][1]["feed"], {"ats": "ashby", "slug": "initech"})
        self.assertEqual(watch["companies"][2]["feed"]["site"], "Hooli_Careers")

    def test_merge_and_feeds(self):
        watch = watchlist.parse(NOTE)
        filters = ats_search.Filters(watchlist.merge(SPEC, watch))
        self.assertTrue(filters.title("Senior Data Analyst"))  # listed by the user: beats `exclude`
        self.assertFalse(ats_search.Filters(SPEC).title("Data Analyst"))
        self.assertTrue(filters.entry_companies.search("Acme Research Inc"))
        self.assertEqual([c["company"] for c in watchlist.feeds([{"company": "hooli"}], watch)], ["Initech"])
        self.assertEqual(watchlist.merge(SPEC, {"companies": [], "titles": []}), SPEC)

    def test_eluta_cards_and_polite_stop(self):
        calls = []

        def fetch(url):
            calls.append(url)
            if len(calls) > 1:
                raise ats_search.FeedError("bot check")
            return CARD

        client = ats_search.Client(sleep=lambda s: None)
        jobs = list(ats_search.eluta(client, {"queries": ["a", "b", "c"]}, date(2026, 11, 11), fetch=fetch))
        self.assertEqual(len(calls), 2)  # stops asking after the refusal, keeps what it read
        self.assertEqual(jobs[0]["company"], "Acme")
        self.assertEqual(jobs[0]["url"], "https://www.eluta.ca/spl/x-1")
        self.assertEqual(jobs[0]["date"], date(2026, 11, 8))


if __name__ == "__main__":
    unittest.main()
