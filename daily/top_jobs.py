"""The "Top job" marks from the daily pages and what they do to future searches.

Marks live in daily/top_jobs.json as {"<date>#<n>": {...job facts...}}. Everything else is
derived from that file on each call, so unticking a box undoes its effect on the next run:

  preferences()       recurring titles, sectors, companies, keywords, plus extra search queries
  boost()             a bounded ordering bonus for a job similar to the marks (never changes rank_score)
  order_candidates()  scores similar jobs first when /rank has more candidates than its limit

No marks means no effect anywhere. Facts come from the posting saved on the day; nothing is fetched.
Posting text is untrusted, so keywords and sectors only ever come from the fixed lists below, and
titles and companies are reduced to plain characters before they can reach a search query or prompt.
"""

import json
import os
import re
import threading
from collections import Counter
from datetime import date
from pathlib import Path

DAILY = Path(__file__).resolve().parent
ROOT = DAILY.parent
MARKS = DAILY / "top_jobs.json"
STATE = ROOT / "job_scraper" / "seen_jobs.json"
LOCK = threading.Lock()

MAX_BOOST = 8.0   # points added for ordering; under half a verdict band, so it reorders neighbours only
BEST_OF = 3       # boost = average of the 3 closest marks, so one mark alone gives at most a third of it
MAX_QUERIES = 4   # extra searches per scrape; each one runs on every portal
MIN_BOOST = 0.5   # smaller matches are noise
WEIGHTS = {"title": 0.5, "sector": 0.2, "company": 0.15, "keywords": 0.1, "seniority": 0.05}

# Fixed lists on purpose (see the module docstring). Extend them for your own field.
SECTORS = {
    "market research": r"market research|consumer insights|opinion research|survey research",
    "loyalty": r"loyalty|rewards program",
    "retail and consumer goods": r"retail|cpg|consumer goods|consumer packaged|grocery|shopper|e-?commerce|apparel|beverage",
    "financial services": r"\bbank|insurance|financial|fintech|wealth|payments",
    "healthcare": r"health|hospital|pharma|biotech|clinical",
    "technology": r"software|saas|technology|internet",
    "consulting and advertising": r"consulting|advertising|marketing services|media agency",
    "public sector": r"government|public sector|municipal|non-?profit",
    "travel and hospitality": r"travel|hospitality|airline|hotel|restaurant",
}
KEYWORDS = ("sql", "power bi", "tableau", "python", "excel", "looker", "sas", "spss", "qualtrics", "azure",
            "survey", "segmentation", "market research", "consumer insights", "customer insights",
            "customer analytics", "shopper insights", "retail analytics", "marketing analytics", "loyalty",
            "crm", "campaign", "pricing", "forecasting", "a/b testing", "experimentation",
            "competitive intelligence", "brand", "category management", "dashboard", "data visualization",
            "storytelling", "stakeholder", "recommendations", "strategy", "machine learning", "statistics",
            "regression", "retention", "attribution", "media", "e-commerce")
SENIORITY = (("director", r"\b(director|vp|vice president|head of)\b"), ("manager", r"\bmanager\b"),
             ("lead", r"\b(lead|principal|staff)\b"), ("senior", r"\b(senior|sr)\b"),
             ("junior", r"\b(junior|jr|associate|intern|new grad|recent graduate)\b"))
LEVEL_WORDS = {"senior", "sr", "jr", "junior", "lead", "principal", "staff", "associate", "intermediate"}
ROLE_WORDS = {"analyst", "specialist", "consultant", "manager", "director", "associate", "advisor"}
NOISE = LEVEL_WORDS | ROLE_WORDS | {"and", "of", "the", "for", "in", "at", "to", "a", "an", "new", "recent",
                                    "graduate", "contract", "month", "remote", "hybrid"}
SALARY = re.compile(r"\$\s?(\d[\d,.]*\s?[kK]?)\s*(?:[A-Z]{3}\s*)?(?:-|–|—|to|and)\s*(?:[A-Z]{3}\s*)?\$?\s?(\d[\d,.]*\s?[kK]?)")


def use_paths(marks: Path, state: Path, daily: Path) -> None:
    """Point the module at another file layout (tests)."""
    global MARKS, STATE, DAILY, ROOT
    MARKS, STATE, DAILY, ROOT = marks, state, daily, daily.parent


def read_json(path: Path, default):
    try:
        text = path.read_text(encoding="utf-8")
        return json.loads(text) if text.strip() else default
    except (OSError, ValueError):
        return default


def load_marks() -> dict:
    """Marks, or {} for a missing, empty or unreadable file: a bad file must never stop a daily run."""
    doc = read_json(MARKS, {})
    return doc if isinstance(doc, dict) else {}


def mark_id(day: str, n: int) -> str:
    return f"{day}#{n}"


def plain(text, limit: int = 60) -> str:
    """Letters, digits and a little punctuation: safe to place in a search query or a prompt."""
    return re.sub(r"\s+", " ", re.sub(r"[^\w &+/.'-]", " ", str(text or ""))).strip()[:limit].strip()


def has(pattern: str, text: str) -> bool:
    return re.search(pattern, text, re.IGNORECASE) is not None


def seniority_of(title) -> str:
    return next((name for name, pat in SENIORITY if has(pat, str(title or ""))), "mid")


def keywords_in(text: str, limit: int = 12) -> list[str]:
    low = text.lower()
    hits = Counter({k: len(re.findall(rf"(?<![\w]){re.escape(k)}(?![\w])", low)) for k in KEYWORDS})
    return [k for k, c in hits.most_common(limit) if c]


def sectors_in(text: str) -> list[str]:
    return [name for name, pat in SECTORS.items() if has(pat, text)]


def posting_sector(title, company, posting: str):
    """The posting's Industries line, then title and company. The body is no use: every benefits section says "health"."""
    for head in (" ".join(re.findall(r"^Industries:.*$", posting, re.MULTILINE)), f"{title} {company}"):
        named = sectors_in(head)
        if named:
            return named[0]
    return None


def money(text: str) -> int:
    text = re.sub(r"[.,]\d{2}(?=\s*[kK]?$)", "", text.strip())
    value = int(re.sub(r"\D", "", text) or 0)
    return value * 1000 if text[-1:] in "kK" else value


def salary_in(posting: str):
    """First annual range in the posting (hourly rates and benefit amounts fall below the 20K bar)."""
    for low, high in SALARY.findall(posting):
        low, high = money(low), money(high)
        if 20000 <= low <= high:
            return {"low": low, "high": high}
    return None


def tokens(title) -> set[str]:
    words = re.findall(r"[a-z0-9+/]+", str(title or "").lower().replace("&", " "))
    return {w.rstrip("s") if len(w) > 4 else w for w in words if w not in NOISE}


def core_title(title) -> str:
    """A searchable role: 'Senior Analyst, Pricing Strategy' -> 'Pricing Strategy Analyst'."""
    text = re.sub(r"\([^)]*\)", " ", str(title or ""))
    parts = [p.strip() for p in re.split(r"\s[-–—|]\s|,|:", text) if p.strip()]
    if not parts:
        return ""
    words = [w for w in parts[0].split() if w.lower().strip(".") not in LEVEL_WORDS]
    if len(words) == 1 and words[0].lower() in ROLE_WORDS and len(parts) > 1:
        words = [w for w in parts[1].split() if w.lower() not in NOISE or w == "&"] + words
    if len(words) < 2:
        return ""
    return plain(" ".join(w.capitalize() if w.isupper() and len(w) > 3 else w for w in words))


def build_mark(day: str, job: dict, today: str) -> dict:
    """Facts worth comparing later, from the saved posting and seen_jobs (never the network)."""
    seen = read_json(STATE, {})
    entry = (seen.get("seen", seen) if isinstance(seen, dict) else {}).get(job.get("key")) or {}
    posting_path, posting = None, ""
    if job.get("posting"):
        file = DAILY / day / "postings" / Path(job["posting"]).name
        if file.is_file():
            posting_path = file.relative_to(ROOT).as_posix()
            posting = file.read_text(encoding="utf-8", errors="replace")
    title, company = job.get("title"), job.get("company")
    return {"key": job.get("key"), "date": day, "n": job.get("n"), "title": title, "company": company,
            "sector": posting_sector(title, company, posting), "location": entry.get("location"),
            "seniority": seniority_of(title), "salary": salary_in(posting),
            "keywords": keywords_in(f"{title} {posting}"), "posting": posting_path,
            "url": job.get("url"), "score": job.get("score"), "marked_on": today}


def write_marks(marks: dict) -> None:
    tmp = MARKS.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(marks, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, MARKS)


def set_mark(day: str, n: int, on: bool) -> None:
    """Tick or untick a job. Raises ValueError for an unknown job or a damaged marks file (left as it is)."""
    jobs = read_json(DAILY / day / "jobs.json", None)
    if not isinstance(jobs, list):
        raise ValueError(f"no jobs.json for {day}")
    job = next((j for j in jobs if j.get("n") == n), None)
    if job is None:
        raise ValueError(f"no job #{n} on {day}")
    with LOCK:
        if MARKS.is_file() and MARKS.read_text(encoding="utf-8").strip() and read_json(MARKS, None) is None:
            raise ValueError(f"{MARKS.name} is damaged; fix or move it, then tick again")
        marks = load_marks()
        if on:
            kept = marks.get(mark_id(day, n), {}).get("marked_on")
            marks[mark_id(day, n)] = build_mark(day, job, kept or date.today().isoformat())
        else:
            marks.pop(mark_id(day, n), None)
        write_marks(marks)


def similarity(job: dict, mark: dict) -> float:
    """0..1. A shared seniority or keyword alone never counts: the role, sector or company must match."""
    text = " ".join([str(job.get("title") or ""), str(job.get("company") or "")]
                    + [str(s) for s in job.get("strengths") or []])
    a, b = tokens(job.get("title")), tokens(mark.get("title"))
    parts = {"title": len(a & b) / len(a | b) if a and b else 0.0,
             "sector": float(mark.get("sector") in sectors_in(text)),
             "company": float(plain(job.get("company")).lower() == plain(mark.get("company")).lower() != "")}
    if not any(parts.values()):
        return 0.0
    found = set(keywords_in(text))
    parts["keywords"] = len(found & set(mark.get("keywords") or [])) / len(found) if found else 0.0
    parts["seniority"] = float(seniority_of(job.get("title")) == mark.get("seniority"))
    return sum(WEIGHTS[k] * v for k, v in parts.items())


def closest(job: dict, marks: dict) -> list[tuple[float, dict]]:
    scored = sorted(((similarity(job, m), m) for m in marks.values() if isinstance(m, dict)),
                    key=lambda p: p[0], reverse=True)
    return scored[:BEST_OF]


def boost(job: dict, marks: dict) -> tuple[float, str | None]:
    """(points to add when ordering, the mark it resembles most).

    Only ever ordering: rank_score stays as scored and the score gates read rank_score. A job with
    any veto or warning (location, language, posting guard) gets nothing, so a mark cannot promote it.
    """
    if job.get("location_verdict") in ("FAIL", "FLAG") or job.get("language_gate") in ("FAIL", "FLAG"):
        return 0.0, None
    if job.get("guard") not in (None, "clean"):
        return 0.0, None
    near = closest(job, marks)
    points = round(MAX_BOOST * sum(s for s, _ in near) / BEST_OF, 1)
    if points < MIN_BOOST:
        return 0.0, None
    return points, f"{plain(near[0][1].get('title'))} at {plain(near[0][1].get('company'))}"


def top(values, limit: int) -> list[list]:
    return [[v, c] for v, c in Counter(v for v in values if v).most_common(limit)]


def preferences(marks: dict, existing_queries: str = "") -> dict:
    """What the marks have in common, plus new searches (those not already in existing_queries)."""
    rows = [m for m in marks.values() if isinstance(m, dict)]
    known = existing_queries.lower()
    titles = top((core_title(m.get("title")) for m in rows), 8)
    companies = top((plain(m.get("company")) for m in rows), 8)
    title_queries = [t for t, _ in titles if t.lower() not in known]
    # A company needs two marks before it earns its own search.
    company_queries = [c for c, n in companies if n >= 2]
    return {"active": bool(rows), "marks": len(rows), "titles": titles, "companies": companies,
            "sectors": top((m.get("sector") for m in rows), 5),
            "keywords": top((k for m in rows for k in m.get("keywords") or []), 12),
            "seniority": top((m.get("seniority") for m in rows), 3),
            "locations": top((plain(m.get("location")) for m in rows), 3),
            "queries": (title_queries[:3] + company_queries)[:MAX_QUERIES]}


def order_candidates(doc: dict, marks: dict, limit: int) -> dict:
    """Reorder `rank_state.py candidates --limit 0` output so a limit defers the least similar jobs."""
    selected = doc.get("selected", [])
    if marks:
        selected = sorted(selected, key=lambda j: boost(j, marks)[0], reverse=True)  # stable: ties keep their order
    kept = selected[:limit] if limit > 0 else selected
    return {**doc, "selected": kept, "deferred": len(selected) - len(kept)}
