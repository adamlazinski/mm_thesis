#!/usr/bin/env python3
"""
Check that every entry in thesis/references.md is cited somewhere, and that
nothing in the chapters cites a work the bibliography does not list.

    .venv/bin/python3 scripts/check_citations.py

A reference counts as cited if its first-listed surname (accent-folded) appears
in a chapter, or failing that in thesis/contributions.md. The reverse direction
finds Author(Year) forms in the chapters and checks the surname appears
somewhere in the bibliography -- any author of a work, not only the first.

Both are string screens, not citation parsing. They catch the failure that
matters here, which is a bibliography drifting away from the text it documents:
before 2026-11-25 this reported 24 of 42 entries uncited, several of whose
annotations promised comparisons the chapters did not contain.
"""
import re, glob, os, unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SURNAME = r"[A-Z][A-Za-zÀ-ſ'-]"


def fold(s):
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


chap_text = " ".join(open(f).read()
                     for f in sorted(glob.glob(os.path.join(ROOT, "thesis", "[0-9]*.md"))))
# dashes join co-authors ("Avellaneda-Stoikov (2008)") and folding would weld
# them into one token, so separate them before the surname regex sees them.
chap_text = fold(re.sub(r"[\u2010-\u2015-]", " ", chap_text)).replace("'s (", " (")
log_text = fold(open(os.path.join(ROOT, "thesis", "contributions.md")).read())
refs = open(os.path.join(ROOT, "thesis", "references.md")).read()

entries, uncited, log_only = [], [], []
for line in refs.split("\n"):
    if not line.startswith("- "):
        continue
    name = fold(re.split(r"[,&(]", line[2:])[0].strip().lstrip("*"))
    if not name:
        continue
    entries.append(name)
    if name in chap_text:
        continue
    (log_only if name in log_text else uncited).append(name)

# any capitalised token in the bibliography is a known surname: a citation in
# the text may name any of a work's authors, not just the first.
known = set(re.findall(SURNAME + "{2,}", fold(re.sub(r"[\u2010-\u2015-]", " ", refs))))
cited = set(re.findall(r"\b(" + SURNAME + r"{3,})\s*\((?:19|20)\d\d[a-z]?\)", chap_text))
dangling = sorted(cited - known)

print(f"    {len(entries)} references: {len(entries) - len(uncited) - len(log_only)} cited in "
      f"chapters, {len(log_only)} only in the log, {len(uncited)} uncited")
for label, xs in (("log-only", log_only), ("UNCITED", uncited), ("NOT IN BIBLIOGRAPHY", dangling)):
    if xs:
        print(f"      {label}: " + ", ".join(sorted(xs)))
