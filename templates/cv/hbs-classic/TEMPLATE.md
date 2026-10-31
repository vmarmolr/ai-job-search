# Template: hbs-classic

- **Type:** CV
- **Source extension:** .tex
- **Engine/toolchain:** lualatex
- **Page limit:** 2 page(s)
- **Fonts:** Calibri (system font - must be installed; ships with Windows/Office). On other systems, change `\setmainfont` to a font you have, e.g. Carlito
- **Class/packages:** article + fontspec, geometry, xcolor, titlesec, enumitem, hyperref (all standard TeX Live)

## Compile command

    cd cv && rm -f <file>.pdf && mkdir -p build && lualatex -interaction=nonstopmode -output-directory=build <file>.tex && mv build/<file>.pdf ./

## Style rules

- Single column, black text, no colour except blue hyperlinks.
- Header: centered bold name in UPPERCASE (18pt), then one line `City | Phone | Email`, then a line `LinkedIn | Portfolio`. Email, LinkedIn and Portfolio stay clickable `\href` links. Email and phone must be literal text.
- Section headings: bold UPPERCASE with a full-width rule underneath (`\section{...}` handles this; type headings in normal case).
- Section order: Profile, Technical Skills, Experience, Education, Leadership & Community Experience, then Certifications & Languages as one-line entries at the end. Keep "Experience" in the Leadership heading: some ATS parsers read "Leadership & Community Engagement" as a company name and drop the entries under it.
- No hyphenation (`\hyphenpenalty=10000`, `\exhyphenpenalty=10000`, `\emergencystretch=1.5em` in the preamble): a word split across lines imports into Workday as two fragments.
- Education entries are institution + degree + dates (+ status note for in-progress degrees) only: no bullets under degrees.
- Entries: `\org{Organization}{Location}` (bold org left, location right), then `\role{\textbf{Core Title}, qualifier}{Mon YYYY - Mon YYYY}` for experience. Education uses a plain (non-bold) degree line with status in italics, e.g. `\textit{(Part-time, Thesis phase)}`.
- Bullets: round dot, action verb first, **bold the key metric or keyword** in each bullet (e.g. `\textbf{3-week}`, `\textbf{SQL}`), at most 1-2 bold spans per bullet.
- Skills: one line per bold category label (`\textbf{Business Analysis}: ...`).
- Dates: `Mon YYYY - Mon YYYY` with a single ASCII hyphen (never `--`).
- 10.5pt Calibri, Letter paper, 0.5in top/bottom and 0.6in side margins: do not shrink fonts or margins to fit; cut content instead.

## Known pitfalls

- `\MakeUppercase` must go in the last mandatory argument of `\titleformat`, not in the format argument; otherwise titlesec errors (`\ttl@row@i doesn't match its definition`).
- `article` has no 10.5pt option; the size is set with `\AtBeginDocument{\fontsize{10.5pt}{12.6pt}\selectfont}`.
- Escape `%`, `&`, `$`, `#` in body text (`\%` especially: unescaped it silently truncates the bullet).
- A bullet starting with `[` must be braced: `\item {[...]}`.
- `\org`/`\role` lines are plain paragraphs, so an employer can be stranded at the bottom of a page with its bullets on the next. After a compile shows it, add `\usepackage{needspace}` to the preamble and `\needspace{5\baselineskip}` immediately before that `\org` line only.
