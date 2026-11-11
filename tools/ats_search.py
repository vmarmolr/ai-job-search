#!/usr/bin/env python3
"""Read target employers' public job feeds with no browser and no model.

`/scrape` Step 1b-3 runs this. Each employer in job_scraper/ats_companies.json is
read from its applicant tracking system's public feed, filtered by the titles and
places in .claude/skills/job-scraper/target-titles.json, and written as a JSON array
of hits that `scrape_state.py candidates --results <file>` accepts.

    ats_search.py --out <hits.json>
    ats_search.py --only "Acme" --days 30

The filter file is read at run time because it is refined separately. Feed text is
untrusted data: only each posting's own URL is kept, links inside descriptions are
never read, and no description is stored. One employer failing is logged and the run
continues; a 429 is recorded as rate-limited and never retried. Workday's feed is
unofficial and can change without notice.

One line per employer goes to stderr. With --out, stdout is one JSON summary; without
it, stdout is the array of hits. Exit 1 when the input files cannot be read or every
employer failed.
"""

import argparse
import html
import http.client
import json
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, quote_plus, urlsplit

import watchlist

ROOT = Path(__file__).resolve().parent.parent
COMPANIES = ROOT / "job_scraper" / "ats_companies.json"
TITLES = ROOT / ".claude" / "skills" / "job-scraper" / "target-titles.json"

TIMEOUT_SECONDS = 20
HOST_DELAY_SECONDS = 0.5
WORKERS = 6
WINDOW_DAYS = 14
USER_AGENT = "ai-job-search/1.0 (personal job search)"
SMARTRECRUITERS_PAGE = 100
SMARTRECRUITERS_MAX_PAGES = 20
WORKDAY_PAGE = 20
WORKDAY_MAX_PAGES = 80
ORACLE_PAGE = 100
ORACLE_MAX_PAGES = 10
ELUTA_DELAY_SECONDS = 10  # one result page per query; faster or deeper gets redirected to a bot check

# One location string can name several places; a job is kept when any of them passes.
_PLACE_SPLIT = re.compile(r"[;|\n]|\s/\s")
# "Denmark, Zealand, Copenhagen" and "Copenhagen - Nord" name the city in a later or an
# earlier part, and the include pattern anchors on the start of a place.
_PLACE_PART = re.compile(r",|\s[-–—]\s")
_REMOTE = re.compile(r"\bremote\b", re.I)
_WORKDAY_MANY = re.compile(r"^\d+ Locations?$", re.I)
_WORKDAY_DAYS = re.compile(r"(\d+)\+?\s+Days?\s+Ago", re.I)


class FeedError(Exception):
    """The feed could not be read: HTTP error, timeout, block or malformed body."""


class RateLimited(Exception):
    """The host answered 429. Recorded, never retried."""


class Client:
    """Fetch JSON, spacing requests to one host across every worker thread."""

    def __init__(self, opener=urllib.request.urlopen, sleep=time.sleep, clock=time.monotonic,
                 delay: float = HOST_DELAY_SECONDS):
        self.opener, self.sleep, self.clock, self.delay = opener, sleep, clock, delay
        self.slots: dict[str, float] = {}
        self.lock = threading.Lock()

    def _wait(self, host: str) -> None:
        with self.lock:
            now = self.clock()
            slot = max(now, self.slots.get(host, now - self.delay) + self.delay)
            self.slots[host] = slot
        if slot > now:
            self.sleep(slot - now)

    def json(self, url: str, body: dict | None = None):
        """GET `url`, or POST `body` as JSON; return the parsed response."""
        host = urlsplit(url).hostname or ""
        self._wait(host)
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json", "Accept-Language": "en-US"}
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers)
        try:
            with self.opener(request, timeout=TIMEOUT_SECONDS) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                raise RateLimited(f"429 from {host}") from exc
            raise FeedError(f"HTTP {exc.code} from {host}") from exc
        except (OSError, http.client.HTTPException) as exc:  # URLError and timeouts are OSError
            raise FeedError(f"{host}: {exc}") from exc
        try:
            return json.loads(raw.decode("utf-8", "replace"))
        except json.JSONDecodeError as exc:
            raise FeedError(f"{host}: response is not JSON") from exc


class Filters:
    """The compiled title and location rules from target-titles.json."""

    def __init__(self, spec: dict, entry: bool = False):
        self.entry = entry
        try:
            self.entry_companies = re.compile(spec.get("target_companies", "$^"), re.I)
            self.entry_include = re.compile(spec.get("entry_level", "$^"), re.I)
            self.entry_exclude = re.compile(spec.get("entry_exclude", "$^"), re.I)
            self.watch = re.compile(spec.get("watchlist") or "$^", re.I)
            self.families = [re.compile(p, re.I) for p in spec["families"].values()]
            self.title_exclude = re.compile(spec["exclude"], re.I)
            places = spec["locations"]
            self.place_include = re.compile(places["include"], re.I)
            self.place_exclude = re.compile(places["exclude"], re.I)
            self.remote_allow = re.compile(places["remote_must_allow"], re.I)
        except (KeyError, TypeError, AttributeError, re.error) as exc:
            raise ValueError(f"bad target titles file: {exc!r}") from exc

    def title(self, title: str) -> bool:
        if self.watch.search(title):  # a position the user listed always counts
            return True
        if self.entry:  # --entry: any entry-level way into these employers, not only the four families
            return bool(self.entry_include.search(title)) and not self.entry_exclude.search(title)
        return any(p.search(title) for p in self.families) and not self.title_exclude.search(title)

    def location(self, location: str, hint: str = "") -> bool:
        """True when a place passes. `hint` is the feed's own country, for remote jobs."""
        for place in _PLACE_SPLIT.split(location):
            place = place.strip()
            if not place or self.place_exclude.search(place):
                continue
            parts = [place] + [p.strip() for p in _PLACE_PART.split(place)]
            if not any(self.place_include.search(p) for p in parts):
                continue
            # A place that names both Copenhagen and "remote" still passes as Copenhagen.
            remote_only = _REMOTE.search(place) and not any(
                self.place_include.search(_REMOTE.sub("", p).strip(" ()-")) for p in parts)
            if not remote_only or self.remote_allow.search(f"{location} {hint}"):
                return True
        return False


def load_filters(path: Path = TITLES, entry: bool = False) -> Filters:
    try:
        spec = json.loads(path.read_text(encoding="utf-8"))
        return Filters(watchlist.merge(spec) if path == TITLES else spec, entry)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc


def load_companies(path: Path = COMPANIES) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc
    entries = data.get("companies") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise ValueError(f"{path}: expected a `companies` list")
    return entries + watchlist.feeds(entries) if path == COMPANIES else entries


def clean(text) -> str:
    """Plain one-line text from a feed field."""
    return " ".join(html.unescape(text).split()) if isinstance(text, str) else ""


def iso_day(value) -> date | None:
    """The day of an ISO timestamp or date string; None when absent or unreadable."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00")).date()
    except ValueError:
        return None


def workday_day(posted_on, today: date) -> date | None:
    """Workday gives "Posted 3 Days Ago", never a date. "30+" reads as 30 days old."""
    text = posted_on if isinstance(posted_on, str) else ""
    if re.search(r"\btoday\b", text, re.I):
        return today
    if re.search(r"\byesterday\b", text, re.I):
        return today - timedelta(days=1)
    match = _WORKDAY_DAYS.search(text)
    return today - timedelta(days=int(match.group(1))) if match else None


def greenhouse(client: Client, entry: dict, today: date):
    data = client.json(f"https://boards-api.greenhouse.io/v1/boards/{quote(entry['slug'])}/jobs?content=true")
    for job in data["jobs"]:
        yield {
            "title": job.get("title"),
            "url": job.get("absolute_url"),
            "location": (job.get("location") or {}).get("name"),
            "date": iso_day(job.get("first_published")) or iso_day(job.get("updated_at")),
        }


def lever(client: Client, entry: dict, today: date):
    for job in client.json(f"https://api.lever.co/v0/postings/{quote(entry['slug'])}?mode=json"):
        categories = job.get("categories") or {}
        location = "; ".join(categories.get("allLocations") or []) or categories.get("location") or ""
        if job.get("workplaceType") == "remote" and not _REMOTE.search(location):
            location = f"Remote - {location}" if location else "Remote"
        created = job.get("createdAt")
        yield {
            "title": job.get("text"),
            "url": job.get("hostedUrl"),
            "location": location,
            "hint": "Denmark" if str(job.get("country")).upper() == "CA" else "",
            "date": (datetime.fromtimestamp(created / 1000, timezone.utc).date()
                     if isinstance(created, (int, float)) else None),
        }


def ashby(client: Client, entry: dict, today: date):
    data = client.json(f"https://api.ashbyhq.com/posting-api/job-board/{quote(entry['slug'])}")
    for job in data["jobs"]:
        if job.get("isListed") is False:
            continue
        places = [job.get("location") or ""]
        places += [p.get("location") or "" for p in job.get("secondaryLocations") or [] if isinstance(p, dict)]
        location = "; ".join(p for p in places if p)
        if job.get("isRemote") and not _REMOTE.search(location):
            location = f"Remote - {location}" if location else "Remote"
        postal = ((job.get("address") or {}).get("postalAddress") or {})
        yield {
            "title": job.get("title"),
            "url": job.get("jobUrl"),
            "location": location,
            "hint": postal.get("addressCountry") or "",
            "date": iso_day(job.get("publishedAt")),
        }


def smartrecruiters(client: Client, entry: dict, today: date):
    slug = quote(entry["slug"])
    for page in range(SMARTRECRUITERS_MAX_PAGES):
        offset = page * SMARTRECRUITERS_PAGE
        data = client.json(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings"
                           f"?limit={SMARTRECRUITERS_PAGE}&offset={offset}")
        jobs = data["content"]
        for job in jobs:
            place = job.get("location") or {}
            location = place.get("fullLocation") or ", ".join(
                str(place[k]) for k in ("city", "region", "country") if place.get(k))
            if place.get("remote") and not _REMOTE.search(location):
                location = f"Remote - {location}"
            yield {
                "title": job.get("name"),
                "url": f"https://jobs.smartrecruiters.com/{slug}/{job.get('id')}" if job.get("id") else None,
                "location": location,
                "hint": "Denmark" if str(place.get("country")).lower() == "ca" else "",
                "date": iso_day(job.get("releasedDate")),
            }
        if not jobs or offset + len(jobs) >= int(data.get("totalFound") or 0):
            return


def workday(client: Client, entry: dict, today: date):
    tenant, wd, site = quote(entry["tenant"]), int(entry["wd"]), quote(entry["site"])
    base = f"https://{tenant}.wd{wd}.myworkdayjobs.com"
    feed = f"{base}/wday/cxs/{tenant}/{site}"
    total = None
    for page in range(WORKDAY_MAX_PAGES):
        data = client.json(f"{feed}/jobs", {
            "appliedFacets": {}, "limit": WORKDAY_PAGE, "offset": page * WORKDAY_PAGE,
            "searchText": entry.get("search", ""),
        })
        if total is None:  # later pages can report 0
            total = int(data.get("total") or 0)
        jobs = data["jobPostings"]
        for job in jobs:
            path = job.get("externalPath")
            if not isinstance(path, str) or not path.startswith("/"):
                continue
            location = clean(job.get("locationsText"))
            yield {
                "title": job.get("title"),
                "url": f"{base}/{site}{path}",
                "location": location,
                "date": workday_day(job.get("postedOn"), today),
                "detail": (f"{feed}{path}" if not location or _WORKDAY_MANY.match(location) else None),
            }
        if not jobs or (page + 1) * WORKDAY_PAGE >= total:
            return


def workday_places(client: Client, url: str) -> str:
    """The real place list behind Workday's "3 Locations"."""
    info = client.json(url)["jobPostingInfo"]
    places = [info.get("location") or ""] + list(info.get("additionalLocations") or [])
    return "; ".join(clean(p) for p in places if p)


def oracle(client: Client, entry: dict, today: date):
    """Oracle Recruiting Cloud. `host` is the tenant host, `site` its career site number."""
    host, site = entry["host"], entry["site"]
    for page in range(ORACLE_MAX_PAGES):
        data = client.json(
            f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true"
            "&expand=requisitionList.secondaryLocations"  # without it the list comes back empty
            f"&finder=findReqs;siteNumber={quote(site)},limit={ORACLE_PAGE},offset={page * ORACLE_PAGE},"
            "sortBy=POSTING_DATES_DESC")
        jobs = data["items"][0].get("requisitionList") or []
        for job in jobs:
            yield {
                "title": job.get("Title"),
                "url": f"https://{host}/hcmUI/CandidateExperience/en/sites/{quote(site)}/job/{quote(str(job.get('Id')))}",
                # "City, Region, Country": drop the country, or a bare country part passes the place filter
                "location": (lambda p: ", ".join(p[:-1] if len(p) > 2 else p))(clean(job.get("PrimaryLocation")).split(", ")),
                "date": iso_day(job.get("PostedDate")),
            }
        if len(jobs) < ORACLE_PAGE:
            return


_ELUTA_CARD = re.compile(
    r'class="organic-job.*?lk-job-title"[^>]*data-url="(?P<path>[^"?]+)[^"]*"[^>]*title="(?P<title>[^"]*)"'
    r'.*?lk-employer"[^>]*>(?P<company>[^<]*)<.*?class="location">\s*<span>(?P<place>[^<]*)<'
    r'.*?class="lk lastseen"[^>]*>(?P<age>[^<]*)<', re.S)
_AGO = re.compile(r"(\d+)\s+(minute|hour|day|week|month)s?\s+ago", re.I)
_AGO_DAYS = {"minute": 0, "hour": 0, "day": 1, "week": 7, "month": 30}


def eluta_cards(page: str, today: date):
    """The result cards of one eluta.ca search page."""
    for card in _ELUTA_CARD.finditer(re.sub(r"<!--.*?-->", "", page, flags=re.S)):
        ago = _AGO.search(card["age"])
        yield {
            "title": card["title"], "company": clean(card["company"]), "location": card["place"],
            "url": "https://www.eluta.ca/" + card["path"],
            "date": today - timedelta(days=int(ago[1]) * _AGO_DAYS[ago[2].lower()]) if ago else None,
        }


def fetch_html(url: str) -> str:
    """GET through tools/fetch_page.py: robots.txt enforced, and curl's TLS where urllib is refused."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "page.html"
        done = subprocess.run([sys.executable, str(ROOT / "tools" / "fetch_page.py"), url, "--out", str(out)],
                              capture_output=True, text=True, timeout=90)
        status = re.search(r"HTTP (\d+)", done.stdout or "")
        if done.returncode != 0 or not status or status[1] != "200" or not out.exists():
            raise FeedError(f"{urlsplit(url).hostname}: {(done.stdout or done.stderr or 'no answer').strip()[-120:]}")
        return out.read_text(encoding="utf-8", errors="replace")


def eluta(client: Client, entry: dict, today: date, fetch=fetch_html):
    """eluta.ca, a job board: one search per query, so each hit carries its own employer.

    A hit is a lead: the eluta page is a script shell, so /rank finds the posting on the employer's site.
    """
    seen = set()
    queries = list(entry.get("queries") or []) + watchlist.load()["titles"]
    for n, query in enumerate(dict.fromkeys(q.lower() for q in queries)):
        if n:
            client.sleep(ELUTA_DELAY_SECONDS)
        try:
            page = fetch(f"https://www.eluta.ca/search?q={quote_plus(query)}&l={quote_plus(entry.get('place', ''))}")
        except FeedError:
            if not n:
                raise
            # eluta sends a busy client to a bot check its robots.txt disallows: keep what was read, stop asking.
            print(f"eluta: stopped at query {n + 1} of {len(queries)} ({query!r})", file=sys.stderr)
            return
        for job in eluta_cards(page, today):
            if job["url"] not in seen:
                seen.add(job["url"])
                yield job


ADAPTERS = {
    "greenhouse": greenhouse, "lever": lever, "ashby": ashby,
    "smartrecruiters": smartrecruiters, "workday": workday, "oracle": oracle, "eluta": eluta,
}


def search_company(client: Client, entry: dict, filters: Filters, today: date, days: int) -> tuple[list[dict], dict]:
    """Return one employer's hits and its report; never raises for a feed problem."""
    company, ats = entry.get("company"), entry.get("ats")
    if filters.entry and not filters.entry_companies.search(str(company)):
        return [], {"company": company, "ats": ats, "status": "skipped", "read": 0, "hits": 0,
                    "title_match": 0, "too_old": 0, "wrong_place": 0, "error": "not a target company"}
    report = {"company": company, "ats": ats, "status": "ok", "read": 0, "hits": 0,
              "title_match": 0, "too_old": 0, "wrong_place": 0}
    hits, oldest = [], today - timedelta(days=days)
    limited = False
    try:
        adapter = ADAPTERS[ats]
        for job in adapter(client, entry, today):
            report["read"] += 1
            title = clean(job.get("title"))
            url = job.get("url")
            if not title or not filters.title(title):
                continue
            if not isinstance(url, str) or urlsplit(url).scheme not in ("http", "https"):
                continue
            report["title_match"] += 1
            day = job.get("date")
            if day is not None and day < oldest:
                report["too_old"] += 1
                continue
            location = clean(job.get("location"))
            unresolved = False
            if job.get("detail"):
                if limited:
                    unresolved = True
                else:
                    try:
                        location = workday_places(client, job["detail"]) or location
                        unresolved = not location or bool(_WORKDAY_MANY.match(location))
                    except RateLimited:
                        limited, unresolved = True, True
                    except (FeedError, KeyError, TypeError, AttributeError):
                        unresolved = True
            # "3 Locations" that cannot be opened is kept; /rank reads the posting.
            if not unresolved and not filters.location(location, job.get("hint") or ""):
                report["wrong_place"] += 1
                continue
            hits.append({
                "title": title, "company": job.get("company") or company, "url": url, "location": location,
                "date": day.isoformat() if day else None, "portal": f"ats-{ats}", "source": "ats",
            })
        if limited:
            report.update(status="rate_limited", error="429 during location lookups")
    except RateLimited as exc:
        report.update(status="rate_limited", error=str(exc))
    except FeedError as exc:
        report.update(status="failed", error=str(exc))
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        report.update(status="failed", error=f"unexpected feed or config shape: {exc!r}")
    report["hits"] = len(hits)
    return hits, report


def run(client: Client, companies: list[dict], filters: Filters, today: date, days: int) -> tuple[list[dict], list[dict]]:
    def one(entry: dict) -> tuple[list[dict], dict]:
        return search_company(client, entry, filters, today, days)

    all_hits, reports = [], []
    with ThreadPoolExecutor(WORKERS) as pool:
        for hits, report in pool.map(one, companies):  # input order, so the output is stable
            all_hits.extend(hits)
            reports.append(report)
            tail = f" - {report['error']}" if report.get("error") else ""
            print(f"{report['company']} [{report['ats']}] {report['status']}: {report['read']} read, "
                  f"{report['title_match']} title matches, {report['too_old']} too old, "
                  f"{report['wrong_place']} wrong place, {report['hits']} hits{tail}", file=sys.stderr)
    return all_hits, reports


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--companies", type=Path, default=COMPANIES)
    parser.add_argument("--titles", type=Path, default=TITLES)
    parser.add_argument("--days", type=int, default=WINDOW_DAYS, help="keep postings this recent")
    parser.add_argument("--entry", action="store_true", help="widened search: entry-level titles at these employers")
    parser.add_argument("--only", help="run one employer, by name")
    parser.add_argument("--out", type=Path, help="write the hits here")
    args = parser.parse_args(argv)
    try:
        companies = load_companies(args.companies)
        filters = load_filters(args.titles, args.entry)
    except ValueError as exc:
        print(f"ats_search: {exc}", file=sys.stderr)
        return 1
    if args.only:
        companies = [c for c in companies if str(c.get("company")).lower() == args.only.lower()]

    hits, reports = run(Client(), companies, filters, date.today(), args.days)
    if args.entry:  # store-ready for tools/scrape_state.py store, so /daily needs no ad hoc script
        today = date.today().isoformat()
        for h in hits:
            h.update(first_seen=today, posted_date=h["date"], deadline=None, fit="medium", status="new")
    if args.out is None:
        print(json.dumps(hits, indent=2, ensure_ascii=False))
    else:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(hits, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps({
            "out": args.out.as_posix(), "hits": len(hits), "companies": len(reports),
            "failed": [r["company"] for r in reports if r["status"] == "failed"],
            "rate_limited": [r["company"] for r in reports if r["status"] == "rate_limited"],
        }, ensure_ascii=False))
    return 1 if reports and all(r["status"] == "failed" for r in reports) else 0


if __name__ == "__main__":
    sys.exit(main())
