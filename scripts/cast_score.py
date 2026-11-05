#!/usr/bin/env python3
"""Score a who's-who run from its cast reports, and compare it with another.

Every check a person used to do by hand over three hours of rows:

    python scripts/cast_score.py RUN_DIR                 # one run
    python scripts/cast_score.py OLD_DIR NEW_DIR         # what got better or worse
    python scripts/cast_score.py OLD NEW --key dcc.json  # plus an answer key

RUN_DIR holds the <book>.cast.txt files that recaps.cast_report_dir writes.

Checks with no key at all:
  piled    an entry of 3+ sentences
  fragment an entry that starts in lower case or with who/which/that, or
           has fewer than 4 words
  empty    an entry that says nothing ("A crawler.")
  broken   "is now and ...", the gap a removed level leaves
  long     an entry over 200 characters
  twice    two names in one book that are forms of one name (Princess Donut
           / Donut, Lucia Marr / Lucia Mar)

An answer key (JSON, kept out of the repo and out of books: it is for
scoring only) can add:
  {"same":  [["Uncle Morty", "Mordecai"]],          # one person, two names
   "must":  {"1": ["Carl", "Donut", "Mordecai"]},   # listed in book 1
   "not_before": {"Samantha": 4},                   # a reveal: not listed before book 4
   "wrong": [{"name": "Langley", "text": "corpse head"}],  # a line about someone else
   "cases": [{"book": 6, "name": "Mordecai", "also": ["Uncle Morty"],
              "says": ["cyclops|one-eyed"], "not": ["duende"],
              "stale": ["Tutorial Guild door"]}]}
A case is one hard character in one book, judged on the last entry the
book gives them: it passes when the person is listed once (under name or an
"also" name), the entry matches every "says" pattern, and no "stale"
pattern, and no entry of theirs anywhere in the book matches a "not". Each case reports pass, missing, twice, thin (a "says"
unmet), wrong (a "not" hit) or out-of-date (a "stale" hit).
Books are numbered by the order of the report files' names.

With two runs, a check that got worse is marked "WORSE" and the exit code
is 1, so a change can be turned down before it costs a run on the PC.
"""
from __future__ import annotations

import argparse
import itertools
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from epubkit.stages import cast_xray as X  # noqa: E402

CHECKS = ("piled", "fragment", "empty", "broken", "long", "twice")
KEYED = ("same", "must", "not_before", "wrong")
VERDICTS = ("pass", "missing", "twice", "thin", "wrong", "out-of-date")


def read(folder: Path):
    """[(book number, file name, [(where, name, entry)])] in file name order."""
    books = []
    for i, f in enumerate(sorted(folder.glob("*.cast.txt")), 1):
        rows = []
        for line in f.read_text(encoding="utf-8").splitlines():
            bits = line.split("\t")
            if len(bits) == 5 and re.match(r"\d+:\d+$", bits[0]):
                rows.append((bits[0], bits[1], bits[4]))
        books.append((i, f.name, rows))
    return books


def sentences(entry: str) -> int:
    return len([s for s in re.split(r"(?<=[.!?])\s+(?=[A-Z])", entry.strip()) if s])


def faults(rows):
    """{check: [example, ...]} for one book."""
    out = {c: [] for c in CHECKS}
    seen = {}
    for where, name, entry in rows:
        if entry == seen.get(name):
            continue
        seen[name] = entry
        tag = "%s %s: %s" % (where, name, entry)
        if sentences(entry) >= 3:
            out["piled"].append(tag)
        if entry[:1].islower() or re.match(r"(?:who|which|that|whose)\b", entry, re.I) \
                or len(entry.split()) < 4:
            out["fragment"].append(tag)
        if re.fullmatch(r"(?:An?|The) [\w'-]+(?: [\w'-]+)?\.?", entry.strip()):
            out["empty"].append(tag)
        if X.BROKEN.search(entry):
            out["broken"].append(tag)
        if len(entry) > 200:
            out["long"].append(tag)
    names = sorted(seen)
    for a, b in itertools.combinations(names, 2):
        if X.twice(a, b):
            out["twice"].append("%s / %s" % (a, b))
    return out


def keyed(books, key):
    """{check: [example, ...]} over the whole run, from the answer key."""
    out = {c: [] for c in KEYED}
    if not key:
        return out
    names_in = {i: {n for _w, n, _e in rows} for i, _f, rows in books}
    lines = {i: rows for i, _f, rows in books}
    for i, names in names_in.items():
        low = {X.plain(n) for n in names}
        for a, b in key.get("same", []):
            if X.plain(a) in low and X.plain(b) in low:
                out["same"].append("book %d: %s / %s listed apart" % (i, a, b))
        for name in key.get("must", {}).get(str(i), []):
            if X.plain(name) not in low:
                out["must"].append("book %d: %s missing" % (i, name))
        for name, first in key.get("not_before", {}).items():
            if i < int(first) and X.plain(name) in low:
                out["not_before"].append("book %d: %s shown before book %s" % (i, name, first))
        for w in key.get("wrong", []):
            for where, name, entry in lines[i]:
                if X.plain(name) == X.plain(w["name"]) and re.search(w["text"], entry, re.I):
                    out["wrong"].append("book %d %s %s: %s" % (i, where, name, entry))
                    break
    return out


def judge(rows, case):
    """(verdict, last entry) for one hard case in one book's rows."""
    names = {X.plain(case["name"])} | {X.plain(n) for n in case.get("also", [])}
    last, every = {}, []
    for _w, name, entry in rows:
        if X.plain(name) in names:
            last[X.plain(name)] = entry
            every.append(entry)
    if not last:
        return "missing", ""
    if len(last) > 1:
        return "twice", " | ".join(last.values())
    entry = next(iter(last.values()))
    # a wrong line is wrong wherever in the book it shows, not only last
    bad = next((e for e in every if any(re.search(p, e, re.I) for p in case.get("not", []))), "")
    if bad:
        return "wrong", bad
    if any(re.search(p, entry, re.I) for p in case.get("stale", [])):
        return "out-of-date", entry
    if not all(re.search(p, entry, re.I) for p in case.get("says", [])):
        return "thin", entry
    return "pass", entry


def cases(books, key):
    """[(case, verdict, entry)] for every case whose book is in the run."""
    lines = {i: rows for i, _f, rows in books}
    out = []
    for c in key.get("cases", []) if key else []:
        if int(c["book"]) in lines:
            out.append((c, *judge(lines[int(c["book"])], c)))
    return out


def score(folder: Path, key):
    books = read(folder)
    per = {i: faults(rows) for i, _f, rows in books}
    return books, per, keyed(books, key), cases(books, key)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("runs", nargs="+", type=Path, help="one run folder, or old then new")
    ap.add_argument("--key", type=Path, help="answer key JSON (scoring only)")
    ap.add_argument("--show", type=int, default=5, help="examples shown per check")
    a = ap.parse_args(argv)
    key = json.loads(a.key.read_text(encoding="utf-8")) if a.key else {}
    runs = [score(r, key) for r in a.runs[:2]]
    worse = False
    new_books, new_per, new_key, new_cases = runs[-1]
    old = runs[0] if len(runs) == 2 else None
    print("check       " + "".join("  book %-3d" % i for i, _f, _r in new_books) + "   total")
    for c in CHECKS:
        cells, tot_new, tot_old = [], 0, 0
        for i, _f, _r in new_books:
            n = len(new_per[i][c])
            tot_new += n
            if old and i in old[1]:
                o = len(old[1][i][c])
                tot_old += o
                cells.append("%4d→%-4d" % (o, n))
            else:
                cells.append("%9d" % n)
        mark = ""
        if old:
            mark = "  WORSE" if tot_new > tot_old else ("  better" if tot_new < tot_old else "")
            worse |= tot_new > tot_old
        print("%-10s  %s   %s%s" % (c, "  ".join(cells),
                                    ("%d→%d" % (tot_old, tot_new)) if old else tot_new, mark))
    if key:
        print()
        for c in KEYED:
            n = len(new_key[c])
            if old:
                o = len(old[2][c])
                mark = "  WORSE" if n > o else ("  better" if n < o else "")
                worse |= n > o
                print("%-10s  %d→%d%s" % (c, o, n, mark))
            else:
                print("%-10s  %d" % (c, n))
    if new_cases:
        print()
        tally = lambda cs: sum(v == "pass" for _c, v, _e in cs)
        n, ok = len(new_cases), tally(new_cases)
        if old:
            o = tally(old[3])
            mark = "  WORSE" if ok < o else ("  better" if ok > o else "")
            worse |= ok < o
            print("hard cases  %d→%d of %d pass%s" % (o, ok, n, mark))
        else:
            print("hard cases  %d of %d pass" % (ok, n))
        for v in VERDICTS[1:]:
            k = sum(x == v for _c, x, _e in new_cases)
            if k:
                print("  %-11s %d" % (v, k))
    print()
    for i, f, rows in new_books:
        shown = [(c, new_per[i][c]) for c in CHECKS if new_per[i][c]]
        if not shown:
            continue
        print("== book %d: %s (%d rows)" % (i, f, len(rows)))
        for c, ex in shown:
            for e in ex[:a.show]:
                print("  %-8s %s" % (c, e[:160]))
    for c in KEYED:
        for e in new_key[c][:a.show * 3]:
            print("  %-10s %s" % (c, e[:160]))
    for c, v, e in new_cases:
        if v != "pass":
            print("  case %-11s book %s %s: %s" % (v, c["book"], c["name"], e[:140]))
    return 1 if worse else 0


if __name__ == "__main__":
    sys.exit(main())
