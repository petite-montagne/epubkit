"""Delta rows plus step 1 cards for people the delta never listed.
A card never replaces an entry. usage: fill.py DELTA BASE CARDS OUT"""
import difflib, os, re, sys
sys.path.insert(0, os.path.expanduser("~/cast-pilot/xray"))
from cards import low, same, common_words

def rows(p):
    return [l for l in open(p, encoding="utf-8").read().splitlines() if re.match(r"^\d+:\d+\t", l)]

delta, base, cards, out = sys.argv[1:5]
d = rows(delta)
card = [l for l in rows(cards) if l not in set(rows(base))]
have = sorted({low(l.split("\t")[1]) for l in d})
common = common_words(have)
add = []
for l in card:
    n = low(l.split("\t")[1])
    if any(same(n, h, common) or difflib.SequenceMatcher(None, n, h).ratio() >= 0.857 for h in have):
        continue
    add.append(l)
with open(out, "w", encoding="utf-8") as f:
    f.write("delta plus cards\n\n" + "\n".join(d + add) + "\n")
print("cards added:", len(add), [l.split("\t")[1] for l in add])
