"""Voted list as is, plus delta rows only for people the voted list lacks.
usage: gaps.py BASE DELTA OUT [--aliases DELTA.aliases.json]
With --aliases, a delta person counts as present when the voted list has any
of their names or aliases, and names delta typed as not people are left out
on both sides."""
import difflib, json, os, re, sys
sys.path.insert(0, os.path.expanduser("~/cast-pilot/xray"))
from cards import low, same, common_words
rows = lambda p: [l for l in open(p, encoding="utf-8").read().splitlines() if re.match(r"^\d+:\d+\t", l)]
a = sys.argv[1:]
table = json.load(open(a[a.index("--aliases") + 1], encoding="utf-8")) if "--aliases" in a else {}
base, delta, out = [x for x in a if not x.endswith(".json") and x != "--aliases"][:3]
notp = {low(n) for n in table.pop("_not_people", [])}
also = {}
for e, al in table.items():
    for n in [e] + al:
        also[low(n)] = {low(x) for x in [e] + al}
b = [l for l in rows(base) if low(l.split("\t")[1]) not in notp]
have = sorted({low(l.split("\t")[1]) for l in b})
common = common_words(have)
add, names = [], set()
for l in rows(delta):
    n = low(l.split("\t")[1])
    if n in notp:
        continue
    if any(same(m, h, common) or difflib.SequenceMatcher(None, m, h).ratio() >= 0.857
           for m in also.get(n, {n}) for h in have):
        continue
    add.append(l); names.add(l.split("\t")[1])
open(out, "w", encoding="utf-8").write("voted list plus delta for gaps\n\n" + "\n".join(b + add) + "\n")
print("people added:", len(names), "| voted rows left out as not people:", len(rows(base)) - len(b))
