#!/usr/bin/env bash
#
# build_thesis.sh — regenerate every derived artefact in thesis/ from the
# committed experiment results, then check the log against the data.
#
#   bash scripts/build_thesis.sh          # build + verify
#   bash scripts/build_thesis.sh --check  # verify only, no writes
#
# Everything this produces is deterministic: the bootstrap seed is fixed and
# the figures read committed JSONs. A clean `git status` after a build is the
# reproducibility check.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PY:-.venv/bin/python3}
[ -x "$PY" ] || PY=python3

if [ "${1:-}" != "--check" ]; then
  echo "==> figures      (thesis/figures/*.png|pdf)"
  "$PY" scripts/make_figures.py    >/dev/null
  echo "==> intervals    (thesis/intervals.md)"
  "$PY" scripts/make_intervals.py  >/dev/null
  echo "==> provenance   (thesis/provenance.md)"
  "$PY" scripts/make_provenance.py >/dev/null
fi

echo "==> verifying contributions against committed experiment JSONs"
"$PY" scripts/verify_contributions.py $(seq 1 72) > /tmp/verify_out.txt 2>&1 || true
ok=$(grep -c " OK " /tmp/verify_out.txt || true)
chk=$(grep -c "CHECK" /tmp/verify_out.txt || true)
mis=$(grep -c "MISMATCH" /tmp/verify_out.txt || true)
nod=$(grep -c "NO DATA" /tmp/verify_out.txt || true)
echo "    $ok clean, $chk with unmatched values, $mis flagged, $nod not reachable"
grep -E "MISMATCH" /tmp/verify_out.txt || true

echo "==> cross-reference check"
"$PY" - <<'PYEOF'
import re, glob, os
secs = {}
for f in sorted(glob.glob("thesis/[01]*.md")):
    m = re.match(r"(\d+)_", os.path.basename(f))
    if m and int(m.group(1)):
        secs[int(m.group(1))] = {int(x) for x in
                                 re.findall(r"^## (\d+)\.", open(f).read(), re.M)}
bad = []
for f in sorted(glob.glob("thesis/*.md")):
    t = open(f).read()
    for m in re.finditer(r"Chapter (\d+)(?:'s)? §(\d+)", t):
        ch, s = int(m.group(1)), int(m.group(2))
        if ch in secs and s not in secs[ch]:
            bad.append(f"{os.path.basename(f)}:{t[:m.start()].count(chr(10))+1}  {m.group(0)}")
print("    all Chapter N §M references resolve" if not bad else
      "    BROKEN:\n      " + "\n      ".join(bad))
PYEOF

echo "==> citation check"
"$PY" scripts/check_citations.py

echo "==> figure embedding check"
n=$(grep -ho "](figures/f[0-9]*" thesis/[01]*.md | sort -u | wc -l | tr -d ' ')
echo "    $n of 9 figures embedded in chapters"

echo
echo "Done. A clean 'git status' now means the build is reproducible."
