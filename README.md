<p align="center">
  <img src="assets/readme/hero.svg" alt="AI Job Search. Pip the courier bird carries an application along a flight path to its destination. The job search that runs on your machine." width="100%">
</p>

<p align="center">
  <a href="https://github.com/ai-job-search-dev/ai-job-search/actions/workflows/ci.yml"><img src="https://github.com/ai-job-search-dev/ai-job-search/actions/workflows/ci.yml/badge.svg" alt="CI" height="20"></a>
  &nbsp;
  <a href="https://claude.com/claude-code"><img src="https://img.shields.io/badge/built_on-Claude_Code-2A9D8F?style=flat" alt="Built on Claude Code" height="20"></a>
  &nbsp;
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-2A9D8F?style=flat" alt="MIT license" height="20"></a>
</p>

<p align="center">
  <a href="https://trendshift.io/repositories/43622?utm_source=trendshift-badge&amp;utm_medium=badge&amp;utm_campaign=badge-trendshift-43622" target="_blank" rel="noopener noreferrer"><img src="https://trendshift.io/api/badge/trendshift/repositories/43622/daily" alt="MadsLorentzen%2Fai-job-search | Trendshift" width="250" height="55"/></a>
</p>

<p align="center">
  An AI-powered job application framework built on <a href="https://claude.com/claude-code">Claude Code</a>.<br>
  Fork it, fill in your profile, and let Claude evaluate job postings, tailor your CV,<br>
  write cover letters, and prepare you for interviews.
</p>

<p align="center">
  <a href="#what-this-fork-adds"><b>What this fork adds</b></a>
  &nbsp;&nbsp;&nbsp;
  <a href="#quick-start"><b>Quick start</b></a>
  &nbsp;&nbsp;&nbsp;
  <a href="#commands"><b>Commands</b></a>
  &nbsp;&nbsp;&nbsp;
  <a href="#how-apply-works"><b>How /apply works</b></a>
  &nbsp;&nbsp;&nbsp;
  <a href="#customization"><b>Customization</b></a>
  &nbsp;&nbsp;&nbsp;
  <a href="SETUP.md"><b>Setup guide</b></a>
</p>

> [!NOTE]
> This is an independent open-source project and is not affiliated with, endorsed by, sponsored by, or maintained by Anthropic. Anthropic and Claude Code are referenced only to describe the toolchain this workflow uses.
>
> This project has **no affiliated cryptocurrency, token, or paid sponsorship program**. Anything claiming otherwise is unauthorized and should be treated as a scam. The only ways to support the project are the Ko-fi link below and contributing on GitHub.

## What this fork adds

This repository is a fork of [ai-job-search-dev/ai-job-search](https://github.com/ai-job-search-dev/ai-job-search), created by Mads Lorentzen and developed by its contributors. The framework, its workflow and most of this README are theirs, so "I" in the next section means the original author. This fork is maintained separately and the original project does not support it.

The original gives you `/scrape`, `/rank`, `/apply`, `/interview`, `/outcome`, a CSV tracker and the `/html-report` dashboard, each started by hand. Those commands all remain. The fork adds a scheduled morning run and two local pages on top of them, plus scripts that move bulky work out of the model's context. The licence stays [MIT](LICENSE), with the original copyright notice kept.

**Unattended daily delivery** *(Windows only: Task Scheduler and `daily/run_daily.cmd`)*. Each run has four phases. Every phase is a fresh Claude Code conversation with its own model:

| Phase | Model | Work | Leaves behind |
|---|---|---|---|
| `/daily-scrape` | Haiku | Searches the job portals | `scrape_done.txt` |
| `/daily` | Sonnet | Ranks new jobs, picks 5-10 never shown before, saves their postings | `picks.json`, `fetch_done.txt` |
| `/daily-cvs` | Opus | Writes one tailored CV per pick, compiles and checks them | `cvs_done.txt` |
| `/daily-page` | Sonnet | Writes the jobs page and records what was delivered | `index.html` |

If a run dies, for example on an API overload or a usage limit, the script waits about 20 minutes and tries again, up to 3 attempts a day. A phase whose output file already exists is skipped, and a CV whose PDF already exists is not rebuilt, so a retry keeps finished work. Nothing is ever submitted or sent: you read the page and apply yourself.

**Daily jobs page** at `http://localhost:8765/`. Each job card shows the score, strengths, gaps, an Apply link and the tailored CV, and the local server adds these controls:

- **I applied** adds a row to `job_search_tracker.csv` and archives the saved posting and CV under `documents/applications/`. Unticking undoes this, unless `/outcome` has already moved the row on.
- **Top job** marks the jobs you like best (see below).
- **Write cover letter** starts a headless Claude Code run for that job and links the PDF when it finishes.

**Top job marks.** Marks feed future runs in three ways, and unticking a job removes its effect on the next run:

- Up to 4 extra searches per scrape: role titles from marked jobs that your search queries do not already cover, then any company with 2 or more marks.
- When there are more new jobs than `/rank` will score, jobs similar to the marks are scored first.
- An ordering bonus of at most 8 points, the average of the 3 closest marks, so one mark alone gives at most a third of that.

Marks never change a job's score, a score cut-off or a deal-breaker. A job with a location or language flag, or a posting flagged by the integrity gate, gets no bonus. With no marks, nothing changes.

**Application tracker** at `http://localhost:8765/applications`.

- **Fields:** company, job title, date applied, status, location, salary, recruiter or contact, posting link, follow-up date, notes and the full job description. `job_search_tracker.csv` keeps its 14 columns, and fields it has no column for live in `daily/tracker_data.json`, so `/apply`, `/outcome` and `/gmail-sync` keep working. `/apply` and `/outcome` record the extra fields through `daily/tracker_cli.py`.
- **Views:** a list with search, status filters and four sort orders, and a pipeline board with five stages (applied, interviewing, offer received, rejected, withdrawn) where you drag a card to change its stage. An overview above both shows follow-ups due, upcoming interviews and applications per week for the last 8 weeks.
- **Follow-ups:** due 7 days after applying by default. You can move a date, mark it not needed, or log one as sent, which sets the next date 7 days later. After the second logged follow-up, no more are scheduled.
- **Interviews:** date, time, format (phone, video, in person), who with, and notes. Adding one to an application still at "applied" moves it to "interviewing".
- **Saved job descriptions:** kept as `documents/applications/<company>_<role>/job_posting.md`, because postings disappear. Text you paste goes through the same integrity gate as fetched postings, and a saved copy is never overwritten. Location and salary are filled from the saved posting when you have not entered them.

**Token reduction tooling.** A single conversation carrying every search result, posting, draft and PDF is expensive, because each turn resends all of it. These tools keep that material out of the conversation:

| Tool | What it replaces |
|---|---|
| [`tools/fetch_posting.py`](tools/fetch_posting.py) | An agent per posting: a script fetches through the portal CLI, runs the integrity gate and saves the text. Other hosts still fall back to the `posting-fetcher` agent. |
| [`tools/cv_from_master.py`](tools/cv_from_master.py) | Retyping a whole CV: only changed sections are written, and the rest is copied from the master CV byte for byte. |
| [`tools/build_cvs.py`](tools/build_cvs.py) | A model turn per compile and check: one call compiles and checks every CV and prints a short PASS or FAIL report. |
| [`cv-visual-checker`](.claude/agents/cv-visual-checker.md) | Page images in the main conversation: a read-only agent looks at the PDFs and returns one line per file. |

The savings are estimates. They have not been measured on a real run, and this repo publishes no token figures.

**Optional `hbs-classic` CV template** in `templates/cv/hbs-classic/`: single column with no hyphenation, written for ATS imports such as Workday. It uses Letter paper and `lualatex`, and needs Calibri, or change `\setmainfont` to a font you have, such as Carlito. The stock templates stay the default until you switch with `/add-template --use hbs-classic`.

**Smaller changes to existing commands.** `/scrape` can also search Indeed through the optional Indeed connector for Claude. `/rank` scores from the Indeed copies `/scrape` saved, and orders its shortlist with Top job marks. The `posting-fetcher` and `posting-scorer` agents are set to Sonnet.

### Requirements for the fork features

| | |
|---|---|
| **[Claude Code](https://claude.com/claude-code)** | Logged in, and on `PATH` or at the default per-user install location. A daily run uses Haiku, Sonnet and Opus. |
| **Python 3.10+** | The page server and tracker use only the standard library. On Windows the scripts call `python` and `pythonw`. |
| **pypdf** | `pip install pypdf`. Optional in the original, but `tools/build_cvs.py` needs it. |
| **[Bun](https://bun.sh)** | Runs the portal CLIs. Install them as in [Quick start](#2-install-job-search-tools). |
| **LaTeX** | `lualatex` for CVs, `xelatex` for cover letters. |
| **Poppler** | For visual PDF checks. `tools/verify_layout.py` needs `pdftotext -bbox`, and without it `build_cvs.py` skips the layout check. If Claude Code cannot render a PDF, `cv-visual-checker` reports `NOT-RENDERED` rather than guessing. Windows: `choco install poppler`. |
| **Windows** | Only for the scheduled run, `daily/Open daily jobs.cmd` and the optional launcher. |

Commands are in [Fork features: quick start](#fork-features-quick-start).

## Does it actually work?

I'm a geophysicist by training. When my position was cut in late 2025, I built this framework to run my own job search - the same `/scrape`, `/apply`, and `/interview` workflow in this repo, used weekly, on my own career. I was upfront about it with every employer I spoke to, and instead of counting against me, it usually sparked a genuine technical conversation.

<p align="center">
  <img src="assets/readme/letters.svg" alt="69 envelopes for 69 tailored applications. 20 of them light up as first interviews, and one is sealed as the signed contract." width="100%">
</p>

Sixty-nine tailored applications, twenty first interviews, and one signed contract later, I started as an AI engineer in June 2026. People kept asking whether this actually works. It got me hired. Now it's yours.

*The longer version, including the full application funnel, is on [LinkedIn](https://www.linkedin.com/in/mads-lorentzen/).*

<p align="center">
  <i>Did this save you a Sunday of cover-letter writing? Consider a coffee.<br>
  Did it land you the job? Maybe two.</i> ☕
</p>

<p align="center">
  <a href="https://ko-fi.com/madslorentzen">
    <img src="https://storage.ko-fi.com/cdn/kofi3.png?v=6" alt="Buy me a coffee at ko-fi.com" height="40">
  </a>
</p>

## What this is

A structured workflow that turns Claude Code into a full-stack job application assistant. Six commands carry you from an empty profile to a tracked result:

<p align="center">
  <img src="assets/readme/route.svg" alt="The workflow in order: /setup builds your profile, /scrape finds new postings, /rank shortlists the fits, /apply tailors a CV and cover letter, /interview preps every round, /outcome tracks each result." width="100%">
</p>

The core workflow (self-profiling, fit evaluation, and the drafter-reviewer application pipeline) is **language- and country-agnostic**. The job portal search skills are built for the Danish market (Jobindex, Jobnet, Akademikernes Jobbank, etc.), but the pattern is designed to be swapped for your local job boards.

The framework encodes career guidance best practices, including structured evaluation criteria, forward-looking cover letter framing, and optional salary benchmarking.

## Quick start

> 🎥 **Prefer to see it in action first?** [The Next New Thing did a hands-on walkthrough](https://www.youtube.com/watch?v=HoVxjMNFYv4) of how the workflow is actually used, from setup to a finished application (recorded August 2026 - commands may have evolved since).

### What you need

| | |
|---|---|
| **[Claude Code](https://claude.com/claude-code)** | The CLI. No free tier: a Claude Pro/Max/Team subscription or Anthropic API credits (pay-per-token, usually cheaper for occasional use). |
| **Python 3.10+** | For the tools in `tools/`. |
| **[Bun](https://bun.sh)** | Runs the job search CLI tools. |
| **LaTeX** | A distribution with `lualatex` and `xelatex`: [TeX Live](https://tug.org/texlive/), [MacTeX](https://tug.org/mactex/), [TinyTeX](https://yihui.org/tinytex/), or [MiKTeX](https://miktex.org/). |
| **pypdf** *(optional)* | `pip install pypdf` for `/apply`'s ATS parseability check. |

<details>
<summary>Fine print: other agents, LaTeX engines, PDF text extraction</summary>

- **Using a different agent tool** (Codex, Antigravity, Gemini CLI)? Start at [`AGENTS.md`](AGENTS.md) - the portal search skills work there out of the box, and [community forks](https://github.com/ai-job-search-dev/ai-job-search/discussions/78) adapt the full workflow.
- **LaTeX engines.** The CV compiles with `lualatex` (pdflatex often fails on modern MiKTeX installs with `fontawesome5` font-expansion errors); the cover letter compiles with `xelatex` because `cover.cls` requires `fontspec`. If using a minimal TeX install such as TinyTeX or BasicTeX, install the extra packages listed in [SETUP.md](SETUP.md#minimal-tex-install-tinytexbasictex).
- **PDF text extraction.** `pypdf` is BSD-licensed and needs no Poppler. Poppler `pdftotext` remains a fallback (macOS: `brew install poppler`, Debian/Ubuntu: `apt install poppler-utils`, Windows: `choco install poppler`). If both are missing, the check degrades to a visual keyword review.

</details>

### 1. Fork and clone

```bash
gh repo fork ai-job-search-dev/ai-job-search --clone
cd ai-job-search
```

> [!IMPORTANT]
> **A fork of this repo is always public** — GitHub does not allow private forks of
> public repositories — and `/setup` (step 3 below) writes your personal data (name,
> contact details, employment history, salary expectations) into **tracked** files.
> If this copy is for your own job search rather than for contributing changes back,
> use a **private repository** with this repo as `upstream` instead — the two-minute
> recipe is in [SETUP.md section 8](SETUP.md#8-pulling-upstream-updates-into-your-fork),
> and every update workflow works identically. Fork only to contribute.

### 2. Install job search tools

```bash
python3 tools/install_portal_clis.py   # Windows: python tools\install_portal_clis.py
```

<details>
<summary>What the installer does</summary>

It runs `bun install` in every portal CLI under `.agents/skills/*/cli/` - discovered, not listed, so a portal you add with `/add-portal` or copy from another fork is included on a fresh clone. Every install runs with `--ignore-scripts`, and a CLI whose `package.json` declares an install-time lifecycle script, `trustedDependencies` or `workspaces`, or that has a `bunfig.toml` or `.npmrc` beside it, is skipped and reported rather than run. `--dry-run` shows what it would install.

For `linkedin-search` and `freehire-search` the install is optional: both have zero runtime dependencies and run with plain `bun`; `bun install` only pulls TypeScript dev types.

</details>

### 3. Set up your profile

```bash
claude
# Then inside Claude Code:
/setup
```

`/setup` offers three paths: read your `documents/` folder if you have one populated (CV PDF, LinkedIn export, diplomas, reference letters, past applications), import a single CV pasted in chat, or walk through an interview. It auto-detects what you have and asks. Documents-folder mode is idempotent and safe to re-run as you add more material; see `documents/README.md` for the layout.

### 4. Search for jobs

```bash
/scrape
```

This searches multiple job portals for positions matching your profile, deduplicates results, and presents them sorted by fit. Pick a match to run `/apply` on it directly — or, when a scrape returns more jobs than you want to eyeball, run `/rank` to batch-score them all against the fit framework and get a ranked shortlist first.

### 5. Apply to a job

```bash
/apply https://jobindex.dk/job/1234567
```

If the URL can't be fetched (some job portals block automated access), you can paste the job description directly instead:

```bash
/apply <paste the full job description here>
```

This runs the full workflow: evaluate fit, draft CV + cover letter, review with a second agent, revise, and present the final output. The posting passes a deterministic integrity gate first (hidden text, invisible characters, instruction-shaped lines, hidden links), and its one-line verdict opens the evaluation; the agents that fetch and review read-only.

> [!WARNING]
> Postings are treated as untrusted input (the workflow follows no instructions embedded in them and fetches no links from their body), but agentic defenses are instruction-level, not a sandbox - on an unfamiliar job board, skim what was fetched and written before you hit send. Details in [SECURITY.md](SECURITY.md).

## Commands

`/setup`, `/scrape`, and `/apply` form the core workflow. Twelve more commands extend it once your profile is in place.

| Command | What it does |
|---|---|
| **`/setup`** | Builds your profile from your documents, a pasted CV, or an interview |
| **`/scrape`** | Searches job portals for postings that match your profile |
| **`/apply`** | Evaluates fit, then drafts, reviews, and compiles a tailored CV and cover letter |
| `/rank` | Batch-scores a scrape into a ranked shortlist |
| `/daily` | This fork: unattended morning delivery of new jobs, tailored CVs and a local page (see [Fork features: quick start](#fork-features-quick-start)) |
| `/interview` | Builds a stage-specific prep pack and runs a mock interview |
| `/outcome` | Records results, archives what you sent, and drafts follow-ups |
| `/gmail-sync` | Proposes application status updates from your Gmail |
| `/notion-sync` | Publishes a read-only view of your pipeline to Notion |
| `/html-report` | Generates an offline dashboard of your applications |
| `/expand` | Adds competencies found in your public profiles and course syllabi |
| `/upskill` | Maps your skill gaps and builds a learning plan |
| `/add-template` | Registers your own CV or cover letter template |
| `/add-portal` | Generates a search skill for a job board in your market |
| `/reset` | Wipes profile data or documents - see [Starting over](#starting-over) |

<details>
<summary><b>Full command reference</b></summary>

- **`/interview`** preps you for a scheduled interview on a tracked application. It builds a stage-specific prep pack from the application's archive (the exact posting, the CV and cover letter the interviewer actually read, feedback recorded from earlier rounds), researches the company and interviewers with a verify-before-use rule, maps likely questions to your STAR examples, and offers a mock interview following the roleplay protocol in `07-interview-prep.md`. Gaps get honest bridge answers, never invented experience.
- **`/outcome`** records what happened to an application - interview stages, offers, rejections, silence. It archives the submitted CV, cover letter, and posting text into `documents/applications/<company>_<role>/`, keeps `outcome.md` in the format `/setup` Path A parses, and updates the tracker. It also owns the stretch before there is an outcome to record: `/outcome followup` surfaces open applications that have gone quiet (default 10 days), drafts a short channel-appropriate follow-up in your writing style using only claims from the materials you already submitted (drafts only, never sends; at most twice per application), and offers a thank-you note in the same turn an interview stage is recorded. Once a few applications resolve, it points you back to `/setup` to calibrate the fit framework from what actually got interviews.
- **`/notion-sync`** publishes a one-way, read-only view of the pipeline into a Notion database via the official Notion MCP server (OAuth, no API keys) - one row per ranked job plus every tracked application, with a write-once briefing page per row. The repo files stay the system of record: nothing syncs back, and documents sync as filenames only. Complements `/html-report`: that is the deep offline dashboard you regenerate at your desk; this is the glanceable live view from anywhere Notion runs (desktop, web, phone).
- **`/gmail-sync`** reads your Gmail (via the Gmail connector) for status signals on your open applications - interview invites, assessment links, offers, rejections - and proposes them as a batch for you to approve before anything is written to the tracker or `outcome.md`, citing the source email on every proposed change. Offers stop short of proposing `hired`/`offer_declined` since that's your call; conflicting or unmatched signals get flagged for a manual `/outcome` pass instead of guessed.
- **`/rank`** bridges `/scrape` and `/apply`: it batch-scores all newly scraped postings against the fit framework (parallel agents fetch each posting and score the five evaluation dimensions) and returns a ranked shortlist with honest per-job strengths and gaps. Deal-breakers veto, deadlines get urgency flags, dead postings get marked expired. Pick a number and it hands off to the full `/apply` workflow.
- **`/expand`** enriches your profile by scanning public sources you've already linked in it (GitHub repos, portfolio site, Kaggle, Google Scholar) and looking up syllabi for named courses and certifications. Discovered competencies are added to your profile with a source tag. Useful right after `/setup` to surface skills that documents alone don't make explicit.
- **`/upskill`** analyzes the gap between your profile, your tracked job postings, and your ranked-but-untracked postings (`/rank`'s recorded gaps in `job_scraper/seen_jobs.json`) — or a single posting via `/upskill <URL>`. Produces a prioritized heatmap of skill gaps and a learning plan with web-searched study resources and time estimates. Useful for career planning between applications.
- **`/html-report`** generates a self-contained HTML dashboard from `job_search_tracker.csv` and the application archives — stat cards, status/sector/channel/funnel charts (inline SVG, no external dependencies), and a filterable applications table. Opens directly in a browser, fully offline. Re-run it any time after `/apply` or `/outcome` adds new entries.
- **`/add-template`** registers your own CV or cover letter template (LaTeX, Typst, or another toolchain) in place of the stock ones. It captures the template's instructions (source extension, compile command, fonts, style rules, page limit), runs a mandatory test compile, and wires the template into `/apply`. See [Custom templates](#custom-templates) below.
- **`/add-portal`** generates a job-portal search skill for a job board in your market. It investigates the portal (search URL pattern, result structure, access rules), scaffolds the CLI skill from the same structure as the shipped ones, and test-runs a live query before registering. See [Job search tools](#job-search-tools) below.

</details>

## How `/apply` works

<p align="center">
  <img src="assets/readme/apply.svg" alt="A job posting passes an integrity gate and fit evaluation, then loops through draft, review, revise, and compile plus inspect until the CV is exactly two pages, the cover letter one page, and the ATS text layer is checked." width="100%">
</p>

The `/apply` command runs a **drafter-reviewer workflow** with mandatory PDF compilation:

1. **Parse** the job posting (URL or text)
2. **Evaluate fit** against your profile (skills, experience, culture, location, career alignment)
3. **Draft** a tailored CV and cover letter in LaTeX
4. **Spawn a reviewer agent** that researches the company and critiques the drafts
5. **Revise** based on the reviewer's feedback
6. **Compile and inspect** both PDFs: lualatex for the CV, xelatex for the cover letter. Claude reads the rendered pages and iterates on the LaTeX until the CV is exactly 2 pages with no orphaned entry titles, and the cover letter is exactly 1 page with the signature visible and fonts consistent.
7. **ATS-check the CV**: extract the PDF's text layer (`pdftotext`, optional dependency) and verify it the way an ATS parser sees it — contact details present as literal text, no garbled glyphs, sane reading order — then score the posting's keyword coverage against the extraction. Keywords the profile genuinely supports get added; genuine gaps stay visible, never stuffed.
8. **Present** the final output with a verification checklist

All claims in the CV and cover letter are verified against your actual profile. The system never fabricates skills or experience.

<details>
<summary><b>What makes this workflow different</b></summary>

- **PDF verification loop.** Most LaTeX-resume templates produce "looks fine in the .tex" output that breaks in the PDF: job titles orphan to the next page, cover letters spill onto page 2, bullet fonts silently fall back to the body font. The `/apply` command compiles and visually inspects every PDF and applies targeted fixes (`\needspace`, `\enlargethispage`, font-matching wrappers for list items) until the layout is clean. This runs automatically on every application.
- **ATS verification on the PDF text layer.** An ATS reads the PDF's embedded text, not the rendered page — and LaTeX can silently produce PDFs whose text extracts as garbage (icon glyphs where the email should be, interleaved lines from multi-column layouts). `/apply` extracts the compiled CV's text layer with `pdftotext` and verifies contact details, reading order, and the posting's keyword coverage against what a parser actually sees. Honesty rule enforced: a keyword the profile doesn't support is acknowledged as a gap, never stuffed in.
- **Relevance-weighted CV cutting.** When a CV overflows 2 pages, the workflow does not cut mechanically from the "oldest" section. It scores each candidate line by (a) relevance to the target posting, (b) uniqueness in the document, and (c) whether the cover letter depends on it, and cuts the lowest-total-score line first. An older-role bullet that hits posting keywords survives ahead of a recent-role bullet that does not.
- **Drafter-reviewer separation.** The drafter writes; a second Claude agent, spawned with a fresh context, researches the company and critiques the drafts. The drafter then revises. This catches missed keywords, weak framing, and generic language that a single pass often leaves in.
- **Token-efficient reviewer dispatch.** The reviewer agent receives drafts inline rather than re-reading them, and the verification checklist runs once at the end of the workflow rather than being duplicated by both agents. Note: the new compile-and-inspect step in Step 5 spends some of those savings on PDF rendering and layout iteration — the workflow trades some end-to-end token cost for a real reduction in broken PDFs reaching the user.

</details>

## Fork features: quick start

What these features do is described in [What this fork adds](#what-this-fork-adds). Commands below use `python3`; on Windows use `python`.

**1. Get this fork.** The quick start above clones the original project, which does not have these features.

```bash
git clone https://github.com/vmarmolr/ai-job-search.git
cd ai-job-search
python3 tools/install_portal_clis.py
pip install pypdf
```

Then run `/setup` as in [step 3](#3-set-up-your-profile). `/daily-cvs` tailors from `cv/main_example.tex`, so that file must hold your real CV first.

> [!IMPORTANT]
> `/setup` writes personal data into tracked files, so do not push it to a public fork. Use a private repository, as [SETUP.md section 8](SETUP.md#8-pulling-upstream-updates-into-your-fork) describes. Everything `daily/` writes is gitignored: day folders, logs, backups, `applied.json`, `delivered.json`, `top_jobs.json`, `tracker_data.json` and `focus_roles.txt`.

**2. Open the pages.**

```bash
python3 daily/server.py        # then open http://localhost:8765/
```

The tracker is at http://localhost:8765/applications. The server listens on `127.0.0.1` only, and tracker requests naming any other host or origin are refused. It works before any daily run, so you can use the tracker on its own.

*Windows only:* double-click `daily/Open daily jobs.cmd` instead. It finds the repo from its own location, starts the server and opens the page. The optional `daily/launcher/OpenDailyJobs.cs` builds a small `.exe` that does the same (build command at the top of the file; the `.exe` is not committed).

If you already have rows in `job_search_tracker.csv`, give them tracker data. This backs up the CSV to `daily/backups/` first and is safe to re-run:

```bash
python3 daily/tracker_cli.py migrate
```

**3. Run a delivery by hand** *(Windows only)*. Do this once before you schedule it. It takes the same steps as the scheduled run, so it uses Opus and real tokens:

```powershell
daily\run_daily.cmd
```

Progress goes to `daily\logs\runner.log` and `daily\logs\<date>.log`. The page appears at `http://localhost:8765/<date>/`.

**4. Schedule it** *(Windows only)*. From the repo root in PowerShell, with the time you want:

```powershell
$action  = New-ScheduledTaskAction -Execute "$PWD\daily\run_daily.cmd"
$trigger = New-ScheduledTaskTrigger -Daily -At 7am
Register-ScheduledTask -TaskName "AI Job Search Daily" -Action $action -Trigger $trigger
```

**5. Optional settings.**

- To put some roles first, list title fragments one per line in `daily/focus_roles.txt`. Without the file every role is treated alike.
- To see what your Top job marks have in common, and the extra searches they add: `python3 daily/daily_state.py top prefs`.
- To use the `hbs-classic` CV template, run `/add-template --use hbs-classic` in Claude Code.
- To record tracker fields from the command line, on a row that already exists: `python3 daily/tracker_cli.py capture --company "Acme" --role "Data Analyst" --follow-up 2026-11-15`.

The token tools also work by hand:

```bash
python3 tools/fetch_posting.py --url <URL> --out daily/<date>/postings/<n>_<slug>.md
python3 tools/cv_from_master.py --sections <n>.sections.tex --out <n>.tex
python3 tools/build_cvs.py daily/<date> --only 2 5
```

**Outside Windows.** The page server and tracker are plain Python, but there is no scheduler script. You can call `claude -p "/daily"` from cron with an `--allowedTools` list adapted from `daily/run_daily.cmd`. That runs all four phases in one conversation on one model, so the per-phase models and retries do not apply, and the step that opens the page uses `cmd`, so open it yourself. No test covers this route.

**What the scheduled run may do.** `daily/run_daily.cmd` runs Claude Code with `--permission-mode acceptEdits`, an explicit `--allowedTools` list and `--setting-sources project`, which skips your user plugins, hooks and instructions. Read that list before you schedule it. Postings stay untrusted input, as described in [SECURITY.md](SECURITY.md), and portal terms still apply to a daily search, so keep query volume low on portals marked personal use only.

## Customization

### Which files to edit manually

If you prefer editing files directly instead of using `/setup`:

| File | What to change |
|------|---------------|
| `CLAUDE.md` | Your full profile (name, education, experience, skills, goals) |
| `01-candidate-profile.md` | Structured version of your CV data |
| `02-behavioral-profile.md` | Your behavioral assessment or self-assessment |
| `04-job-evaluation.md` | Skill match areas, career goals, motivation filters |
| `05-cv-templates.md` | Profile statement templates for different role types |
| `07-interview-prep.md` | Your STAR examples from actual experience |
| `search-queries.md` | Job search queries for your skills and location |

### Updating your search queries

As your priorities evolve, you can reconfigure just the job search without re-running the full profile setup:

```
/setup --section search
```

This re-runs the search configuration interview: which roles to target, which skills to search for, which locations, and which portals. It also suggests role types you may not have considered based on your profile.

### Custom templates

The CV uses [moderncv](https://ctan.org/pkg/moderncv) (banking style). The cover letter uses a custom `cover.cls` with Lato/Raleway fonts. Both are LaTeX — the reference engine this repo ships and maintains.

To use your own template instead — LaTeX, [Typst](https://typst.app/), or any other toolchain that compiles to PDF from the command line — run:

```
/add-template
```

Point it at your source file (a `.tex` file plus any `.cls`/`.sty` files or bundled fonts; a `.typ` file plus any local packages; or an equivalent for another toolchain). The command interviews you for the template's instructions — source extension, compile command, fonts and where they live, style rules to preserve, hard page limit — stores everything under `templates/`, runs a mandatory test compile, and activates the template so `/apply` drafts and compiles from it. Templates are stored with `[PLACEHOLDER]` tokens instead of personal data, so they're safe to commit and share.

- `/add-template --list` shows registered templates
- `/add-template --use <name>` switches between them
- `/add-template --use default` reverts to the stock moderncv / cover.cls templates

If you prefer doing it by hand, the manual route still works: update the guidance in `05-cv-templates.md` and `06-cover-letter-templates.md`.

### Job search tools

The four Danish CLI tools in `.agents/skills/` (Jobbank, Jobdanmark, Jobindex, Jobnet) demonstrate the pattern for building a job-portal integration for a specific market. If you're in a different country, run:

```
/add-portal
```

Give it your local job board's URL. The command investigates the portal (search-URL pattern, result-page structure, robots.txt/access rules), scaffolds a CLI skill with the same structure, commands, and output contract as the shipped ones, and test-runs a live query before registering anything. Auth-walled portals are declined, and portals with restrictive terms get a prominent personal-use-only warning in the generated skill. The generated skill is market-specific and lives in your fork; the generator itself is the universal part.

Maintaining a fork adapted to your market or language? Add it to the [Community forks & adaptations](https://github.com/ai-job-search-dev/ai-job-search/discussions/78) thread so others can find it.

For **country-agnostic** starting points outside Denmark, the repo ships two portal skills alongside the Danish demos:

- **`linkedin-search`** — built on LinkedIn's public, unauthenticated `jobs-guest` endpoints. Field-agnostic, **zero runtime dependencies** (runs with just `bun`), and takes the search location as an explicit flag, so it works for any market out of the box (`-l "Berlin, Germany"`, `-l "Mumbai, Maharashtra, India"`, `-l "Remote"`, …). Intended for **personal use only** — automated access is against LinkedIn's Terms of Service, so keep volume low. See `.agents/skills/linkedin-search/SKILL.md`.
- **`freehire-search`** — queries the [freehire.me](https://freehire.me) aggregator's public REST API (JSON, no API key). Tech-focused (software, data, engineering, DevOps, remote), multi-market via facet flags (`--region`, `--country`, `--remote`), and **zero runtime dependencies**. Unlike the HTML-scraping Danish portals, results come back structured (skills, seniority, category). The backend is MIT-licensed and [self-hostable](https://github.com/strelov1/freehire) — point `FREEHIRE_API_URL` at your own instance if you prefer. See `.agents/skills/freehire-search/SKILL.md`.

### Extending the framework: portals, templates, criteria - and borrowing from other forks

Everything above adds up to an extension model, so here it is stated plainly. The framework has three extension points, and none of them require touching upstream:

1. **Portal skills** - the module system for job boards. Every `*-search` skill is a self-contained folder under `.agents/skills/` with the same contract (a `search`/`detail` CLI, `--format json|table|plain` output, an `enabled:` flag in its `SKILL.md`, its own tests). `/scrape` auto-discovers any installed skill that follows the contract - nothing to register, nothing to wire up. `/add-portal` generates new ones; the [community portal index](https://github.com/ai-job-search-dev/ai-job-search/discussions/78) catalogs the ones other forks have built.
2. **Document templates** - `/add-template` registers any CV or cover-letter toolchain that compiles to PDF from the command line, LaTeX or otherwise.
3. **Evaluation criteria** - deal-breakers and preferences in your profile are free-form, and the evaluation rubric scores against whatever you put there. "Strong parental-leave terms", "minimum salary X per my union's scale", "no on-call" - each is one profile line, no code, and it carries real weight in `/rank` and `/apply` fit evaluations.

<details>
<summary>How the Language Gate handles language deal-breakers</summary>

Language is the one deal-breaker type with dedicated, structured handling: `/setup` captures every language you work in and your level (asked directly, or inferred from your CV/LinkedIn export) into a `Languages` table, and the Language Gate (`04-job-evaluation.md`) hard-rejects a posting that requires a language you haven't declared at all, while flagging - not auto-rejecting - one that asks for a higher level than you declared in a language you do work in, so a borderline case (a strict "fluent" bar against your own B1/B2, say) gets your judgment instead of a silent drop.

</details>

**Borrowing a portal skill from another fork** is the intended way to get a board that upstream doesn't ship: find it in the [portal index](https://github.com/ai-job-search-dev/ai-job-search/discussions/78), open that fork, and copy the one folder into your own `.agents/skills/`. Before you run it:

- **Read the code.** All of it - these CLIs run pre-approved on your machine (`.claude/settings.json` allowlists them) against your career data. Check that the only network calls go to the job board it claims to search, that `package.json` has no `dependencies` and no lifecycle scripts (`postinstall` etc.), and that nothing reads or writes outside its own folder.
- **Run its tests offline** (`bun test` in the skill's `cli/` directory) - a well-built skill's tests pass with no network access.
- Check the `enabled:` flag and the skill's own ToS notes.

The copy step is manual on purpose. Your settings already allow installed portal skills to run without asking each time - so an installer that fetched them from third-party repos for you would skip the one check that matters: you, reading the code first. There isn't one, and that's a security decision rather than a missing feature.

Market-specific *data sources* (a national salary database, local award-rate tables) follow the same pattern as portals: they belong in a market fork, shared via [#78](https://github.com/ai-job-search-dev/ai-job-search/discussions/78), not upstream.

### Salary benchmarking

The salary tool works with any salary data you provide (union statistics, Glassdoor exports, personal research, etc.). See `tools/README_SALARY_TOOL.md` for the expected format and setup. If you don't have salary data, the salary step is simply skipped.

### Starting over

To wipe your profile data and start fresh:

```
/reset profile    # clears skill files, preserves framework rules
/reset documents  # deletes files from documents/ folder
/reset all        # both
```

`/reset` shows exactly what will be deleted and requires you to type `RESET` to confirm. Nothing is deleted until you do.

### Staying up to date

Upstream moves fast. Rather than pulling raw `master` and hoping, update your fork to a tagged [release](../../releases) - a weekly checkpoint that passed CI, with its changes listed on the release page. `python3 tools/check_upstream_updates.py` previews exactly which of your personalized files an update touches before you merge, and `python3 tools/upstream_triage.py` sorts the commits you're behind into "worth reviewing" vs "probably skip" (a weekly workflow can post this to a rolling issue). Full walkthrough in [SETUP.md, section 8](SETUP.md#8-pulling-upstream-updates-into-your-fork).

## Tips for better results

### Profile depth matters

The single biggest factor in output quality is how much detail you put into your profile. A thin profile produces generic applications; a detailed one enables genuinely tailored results.

- **Role descriptions:** Don't just list job titles. Describe what you actually did in each position: specific projects, tools used, responsibilities, and measurable achievements. The more material you provide, the more precisely the system can reframe your experience for different roles.
- **Skills in context:** Instead of listing "Python" or "project management," describe how and where you applied them. "Built ML pipelines for customer churn prediction in Python using scikit-learn" gives the system far more to work with than "Python, machine learning."
- **All onboarding paths work:** Whether you point `/setup` at your `documents/` folder, paste a single CV, or walk through the interview, the principle is the same: richer input produces sharper output.

### Career path discovery

The framework supports two distinct modes of job searching:

- **Explicit targeting:** You know which roles or sectors you want. The system helps refine and prioritize based on fit.
- **Latent opportunity discovery:** By analyzing your full history (not just job titles, but the actual work you did), the system can surface career paths you haven't considered. Transferable skills that map to unexpected industries, patterns in what you enjoyed or excelled at, or emerging roles that combine your domain expertise with new technology.

To get the most from this, invest time during `/setup` in describing not just your experience, but what energized you, what drained you, and what you'd want more of. This context directly shapes how the system evaluates fit and which roles it surfaces during `/scrape`.

## File structure

<details>
<summary>Show the repository layout</summary>

```
ai-job-search/
├── CLAUDE.md                          # Main candidate profile + workflow rules
├── .claude/
│   ├── commands/
│   │   ├── apply.md                   # /apply workflow (drafter-reviewer)
│   │   ├── setup.md                   # /setup onboarding (documents folder, CV import, or interview)
│   │   ├── expand.md                  # /expand competency enrichment from documents and online presence
│   │   ├── add-template.md            # /add-template register custom templates (LaTeX, Typst, ...)
│   │   ├── add-portal.md              # /add-portal generate a job-portal search skill for your market
│   │   ├── rank.md                    # /rank triage scraped jobs into a ranked shortlist
│   │   ├── daily*.md                  # This fork: the four phases of the /daily run
│   │   ├── outcome.md                 # /outcome record application results, archive materials
│   │   ├── gmail-sync.md              # /gmail-sync auto-detect application status from Gmail
│   │   ├── interview.md               # /interview stage-specific prep pack + mock interview
│   │   ├── html-report.md             # /html-report generate application tracker dashboard
│   │   ├── notion-sync.md             # /notion-sync one-way pipeline view in a Notion database
│   │   └── reset.md                   # /reset wipe profile data or documents folder
│   ├── skills/
│   │   ├── job-application-assistant/  # Core application skill
│   │   │   ├── SKILL.md               # Skill definition
│   │   │   ├── 01-candidate-profile.md # Your education, experience, skills
│   │   │   ├── 02-behavioral-profile.md# PI/DISC/personality assessment
│   │   │   ├── 03-writing-style.md    # Tone, structure, do's and don'ts
│   │   │   ├── 04-job-evaluation.md   # Scoring framework for job fit
│   │   │   ├── 05-cv-templates.md     # LaTeX CV structure + tailoring rules
│   │   │   ├── 06-cover-letter-templates.md # LaTeX cover letter templates
│   │   │   └── 07-interview-prep.md   # STAR examples + interview framework
│   │   ├── job-scraper/               # Job search orchestration
│   │   └── upskill/                   # /upskill skill gap analysis and learning plan
│   └── settings.json                  # Claude Code permissions (shared, scoped)
├── .agents/skills/                    # Job portal CLI tools
│   ├── jobbank-search/                # Akademikernes Jobbank (Denmark)
│   ├── jobdanmark-search/             # Jobdanmark.dk (Denmark)
│   ├── jobindex-search/               # Jobindex.dk (Denmark)
│   ├── jobnet-search/                 # Jobnet.dk (Denmark, government portal)
│   ├── linkedin-search/               # LinkedIn public job listings (country-agnostic)
│   └── freehire-search/               # freehire.me tech job aggregator (multi-market, REST API)
├── assets/                            # README artwork (Pip the mascot, animated SVG diagrams)
├── cv/
│   └── main_example.tex               # moderncv LaTeX template
├── cover_letters/
│   ├── cover.cls                      # Custom cover letter LaTeX class
│   ├── cover_example.tex              # Example cover letter (structural reference + CI smoke test)
│   └── OpenFonts/                     # Lato + Raleway fonts
├── daily/                             # This fork: /daily delivery, local jobs page server, application tracker
├── templates/                         # Custom templates registered via /add-template
│   ├── cv/hbs-classic/                # This fork: optional single-column CV template
│   └── README.md                      # Folder layout instructions
├── documents/                         # Career source materials for /setup Path A and /expand
│   ├── README.md                      # Folder layout instructions
│   ├── cv/                            # Master CV (PDF or .tex)
│   ├── linkedin/                      # LinkedIn profile export (PDF)
│   ├── diplomas/                      # Degree certificates and transcripts
│   ├── references/                    # Reference letters
│   └── applications/                  # Past application records (<company>_<role>/)
├── .github/workflows/ci.yml           # CI: LaTeX smoke compiles, skill lint, CLI typechecks
├── salary_lookup.py                   # Salary benchmarking tool (BYO data)
├── tools/
│   ├── build_cvs.py                   # This fork: compile and check every CV in a folder in one call
│   ├── check_framework_version.py     # CI check: framework_version bumped when skill files change
│   ├── check_upstream_updates.py      # Preview which personalized files an upstream update touches
│   ├── convert_salary_excel.py        # Convert salary Excel to JSON
│   ├── cv_from_master.py              # This fork: build a CV from the master plus changed sections
│   ├── fetch_page.py                  # GET-only browser-header retry for 403s (robots.txt enforced)
│   ├── fetch_posting.py               # This fork: fetch, gate and save a posting without an agent
│   ├── install_portal_clis.py         # Install every discovered portal CLI (bun install)
│   ├── lint_skills.py                 # CI lint for skills, commands, settings.json
│   ├── posting_guard.py               # Integrity gate: strip hidden text, flag injection-shaped lines
│   ├── robots_check.py                # Gate the browser-header retry against robots.txt
│   ├── security_guards.py             # CI guards: permission allow/ask/deny, skill grants, gitignore, manifests
│   ├── upstream_triage.py             # Sort upstream commits into worth-reviewing vs probably-skip
│   ├── verify_layout.py               # Measure a compiled PDF's page layout (holes, orphans, footer collisions)
│   ├── verify_pdf.py                  # Verify a compiled PDF's page count and extractable text
│   └── README_SALARY_TOOL.md          # Salary tool setup instructions
├── job_scraper/                       # Scraper state (seen jobs, results)
├── gmail_sync/                        # /gmail-sync state (processed message IDs, last sync date)
├── upskill/                           # /upskill report output (markdown reports per run)
├── job_search_tracker.csv             # Application tracking spreadsheet
└── SETUP.md                           # Detailed setup guide
```

</details>

## Contributing

Thinking about a PR? Read [CONTRIBUTING.md](CONTRIBUTING.md) first - it explains what gets merged, what lives in forks, and why, and where changes to this fork's features go.

## Acknowledgements

- [Mikkel Krogholm](https://github.com/mikkelkrogsholm) ([skills repo](https://github.com/mikkelkrogsholm/skills)) for the job search CLI skills
- Built with [Claude Code](https://claude.com/claude-code) by [Anthropic](https://anthropic.com)
- This fork builds on [ai-job-search-dev/ai-job-search](https://github.com/ai-job-search-dev/ai-job-search)

## License

MIT. This fork keeps the original licence.

<p align="center">
  <img src="assets/mascot/pip_flight_loop.gif" alt="Pip, the courier bird" width="120"><br>
  <sub>Pip delivers. Good luck out there.</sub>
</p>
