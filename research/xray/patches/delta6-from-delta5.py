"""delta5.py -> delta6.py: replay-only, with the four root fixes and learned epithets."""
import sys

src = open(sys.argv[1], encoding="utf-8").read()


def sub(old, new, count=1):
    global src
    assert src.count(old) == count, (src.count(old), old[:80])
    src = src.replace(old, new)


sub('"""Step 2f (delta5): delta4 rebuilt around three root causes.',
    '''"""Step 2g (delta6): delta5 replayed from its saved answers, no new model calls.

Four root fixes on top of delta5:
1. Display names are time-aware: a row shows only names the book has used at
   or before that row.
2. Merges stick: rows written under a name that later merged are moved to the
   merged entity (delta5 left them under the old key, so a SAME verdict still
   printed as a duplicate). A bare given name that starts a known full name
   ("Chris" -> "Chris Andrews"), when that full name is the only one it fits,
   merges by code rule, not by guard verdict.
3. A row that repeats the entity's last printed text is not printed again.
4. Family words (Mom, Dad, Grandma...) are never a display name.
Plus: epithets ("the goddess of youth") the text or the entity's own
description ties to one entity count as naming it when a quote is checked.

usage: python3 -I delta6.py dcc4|pj6 OUT.cast.txt SAVED.delta5.log  (run from ~/cast-pilot)

delta5 notes follow.''')

sub('PRON = re.compile(', '''KIN = {"mom", "mommy", "mum", "mother", "ma", "dad", "daddy", "father", "pa", "papa", "grandma", "grandpa", "granny",
       "grandmother", "grandfather", "nana", "auntie", "aunt", "uncle", "sis", "bro", "honey", "baby"}
# "Goddess of youth and former cupbearer" -> "goddess of youth"
ROLE = re.compile(r"^(?:the |a |an )?((?:god|goddess|titan|titaness|spirit|nymph|lord|lady|king|queen|prince|princess)"
                  r" of (?:the )?[a-z]+(?: [a-z]+)?)\\b", re.I)
PRON = re.compile(''')

sub('''    return bool(ws) and all(w[:1].isupper() or w[:1].isdigit() or w.lower() in PARTICLES for w in ws) \\
        and ws[0].lower() not in PARTICLES''',
    '''    if ws and all(w.lower().strip(".,'") in KIN for w in ws):
        return False
    return bool(ws) and all(w[:1].isupper() or w[:1].isdigit() or w.lower() in PARTICLES for w in ws) \\
        and ws[0].lower() not in PARTICLES''')

# replay instead of the model
sub('''def main(which, out):
    book = Path(glob.glob(BOOK[which])[0])
    ai = OpenAIProvider("qwen3.6-35b-a3b", "http://localhost:8081", key(),
                        timeout=600, max_tokens=2000, temperature=0)
''', '''class Saved:
    """Hands back delta5's saved step answers in order; never calls a model."""
    def __init__(self, steps):
        self.steps = list(steps)

    def complete(self, prompt, system=None):
        return type("R", (), {"text": self.steps.pop(0) if self.steps else "{}"})()


def main(which, out, saved):
    book = Path(glob.glob(BOOK[which])[0])
    steps, verdicts = replay(saved)
    ai = Saved(steps)
    moved = {}          # old entity key -> the key it merged into
    epithets = collections.defaultdict(set)   # entity -> "goddess of youth", ...
    coderule = []       # merges decided by the code rule, not a saved verdict
''')

sub('''    def guard(a, b_name, b_who):
        calls["guard"] += 1
        r = ai.complete(GUARD.format(a=entry(a), b=b_name + ": " + b_who), system=SYSTEM).text.strip()
        log.write("GUARD %s | %s -> %s\\n" % (a, b_name, r.splitlines()[0] if r else ""))
        return r.upper().startswith("SAME")
''', '''    def extends(k, name, ptext):
        """A bare given name that starts this one known full name, both used in
        the text so far, and no other entity starts with that word."""
        a, b = sorted((low(norm(name)), low(k)), key=lambda x: len(x.split()))
        if len(a.split()) != 1 or len(b.split()) < 2 or b.split()[0] != a or len(a) < 3 or a in STOPW:
            return False
        if any(e != k and any(low(x).split()[:1] == [a] for x in names(e)) for e in known):
            return False
        return mentions(k, seen) > 0 and mentions(name, ptext) > 0

    def guard(a, b_name, b_who):
        if (a, b_name) in verdicts:
            calls["guard (saved)"] += 1
            log.write("GUARD %s | %s -> %s (saved)\\n" % (a, b_name, "SAME" if verdicts[(a, b_name)] else "DIFFERENT"))
            return verdicts[(a, b_name)]
        calls["guard (no saved verdict)"] += 1
        log.write("NOVERDICT %s | %s -> DIFFERENT (would need a new guard call)\\n" % (a, b_name))
        coderule.append(("no verdict, kept apart", a, b_name))
        return False

    def learn_epithets(text):
        """ "Hebe, the goddess of youth," in the text ties that epithet to Hebe."""
        for k in known:
            for x in names(k):
                for m in re.finditer(r"\\b%s,\\s+(the\\s+[a-z][a-z ]{3,40}?)[,.;!?]" % re.escape(x), text):
                    epithets[k].add(squash(m.group(1)))
''')

# epithets from the new entity's own description, if the book uses that phrase
sub('''        known[name] = dict(aliases=aliases, type=typ, first=sentence(desc, FIRST_WORDS), change="", narrator=False)
        rows.append((order, para, name, who(name)))''',
    '''        known[name] = dict(aliases=aliases, type=typ, first=sentence(desc, FIRST_WORDS), change="", narrator=False)
        m = ROLE.match(desc)
        if m and squash(m.group(1)) in squash(book_text):
            epithets[name].add(squash(m.group(1)))
        rows.append((order, para, name, who(name)))''')

# code rule for surname extensions, ahead of the guard
sub('''        if hit and frozenset((hit, name)) not in never:
            if guard(hit, name, sentence(desc, FIRST_WORDS)):''',
    '''        if hit and extends(hit, name, ptext):
            k = known.pop(hit)
            main_name = name if len(name.split()) > len(hit.split()) else hit
            k["aliases"] = sorted({hit, name, *aliases, *k["aliases"]} - {main_name})
            known[main_name] = k
            if main_name != hit:
                moved[hit] = main_name
                epithets[main_name] |= epithets.pop(hit, set())
            coderule.append(("surname extension, merged", hit, name))
            log.write("  CODEMERGE %s + %s -> %s (surname extension)\\n" % (hit, name, main_name))
            return
        if hit and frozenset((hit, name)) not in never:
            if guard(hit, name, sentence(desc, FIRST_WORDS)):''')

sub('''                known[main_name] = k
                log.write("  MERGE %s + %s -> %s\\n" % (hit, name, main_name))''',
    '''                known[main_name] = k
                if main_name != hit:
                    moved[hit] = main_name
                    epithets[main_name] |= epithets.pop(hit, set())
                log.write("  MERGE %s + %s -> %s\\n" % (hit, name, main_name))''')

# a quote naming the epithet names them
sub('''        mine = forms(k) + (["i", "me", "my"] if known[k]["narrator"] else [])''',
    '''        mine = forms(k) + sorted(epithets[k]) + (["i", "me", "my"] if known[k]["narrator"] else [])''')
sub('''        if not (hit(mine, sq) or hit(forms(k), before)):''',
    '''        if not (hit(mine, sq) or hit(forms(k) + sorted(epithets[k]), before)):''')

sub('''    seen = ""
    parts = [''', '''    seen = ""
    book_text = "\\n".join(t for _o, _p, _l, ps in docs for _n, t in ps)
    parts = [''')

sub('''        seen += " " + ptext
''', '''        seen += " " + ptext
        learn_epithets(text)
''')

# output: resolve moved keys, time-aware display, no repeated rows
sub('''    # code-side merge of leftovers, as in delta4''',
    '''    if ai.steps:
        log.write("WARNING %d saved answers left over\\n" % len(ai.steps))
    cur = lambda n: cur(moved[n]) if n in moved else n
    rows = [(o, pn, cur(w), t) for o, pn, w, t in rows]
    log.write("MOVED %s\\n" % sorted(moved.items()))
    log.write("CODERULE %s\\n" % coderule)
    log.write("EPITHETS %s\\n" % sorted((k, sorted(v)) for k, v in epithets.items() if v))
    # code-side merge of leftovers, as in delta4''')

sub('''        shown[t] = best
    log.write("SHOWN %s\\n" % sorted((t, b) for t, b in shown.items() if t != b))
    for n in known:
        rename[n] = shown[rename.get(n, n)]
    rows = [(o, pn, rename.get(w, w), t) for o, pn, w, t in rows]
''', '''        shown[t] = best
    log.write("SHOWN %s\\n" % sorted((t, b) for t, b in shown.items() if t != b))

    # 1: a row shows only names the book has used by then
    firsts = {}

    def first(x):
        if x not in firsts:
            q = squash(x)
            firsts[x] = next(((o, n) for o, seg in parts for n, t in seg
                              if q and re.search(r"\\b%s\\b" % re.escape(q), squash(t))), (10 ** 9, 0))
        return firsts[x]

    def show_at(t, w, at):
        al = {x for x in group[t] if first(x) <= at} | {w}
        cands = [x for x in al if proper(x) and not titled(x)] or [x for x in al if proper(x)] or [w]
        best = max(cands, key=lambda x: (used(x), len(x.split())))
        longer = [x for x in cands if x != best and x.split()[0] == best.split()[0] and len(x.split()) > len(best.split())]
        return max(longer, key=lambda x: (used(x), len(x.split()))) if longer else best

    for n in known:
        rename[n] = shown[rename.get(n, n)]
    out_rows = []
    for o, pn, w, t in rows:
        g = next(g for g in group if w in group[g])
        s = show_at(g, w, (o, pn))
        if s != shown[g]:
            log.write("ROWNAME %d:%d %s shown as %s (final name %s not used yet)\\n" % (o, pn, w, s, shown[g]))
        out_rows.append((o, pn, s, t, shown[g]))
''')

sub('''    done = set()
    with open(out, "w", encoding="utf-8") as f:
        f.write("delta5: code-picked checks, verified changes, typed alias table\\n\\n")
        for o, pn, w, t in rows:
            if w in done:
                t = re.sub(r"\\s+([.,;])", r"\\1", NARR_I.sub("", t))
            done.add(w)
            f.write''', '''    done, last = set(), {}
    with open(out, "w", encoding="utf-8") as f:
        f.write("delta6: delta5 replayed; time-aware names, sticky merges, no repeated rows\\n\\n")
        for o, pn, w, t, ent in out_rows:
            if ent in done:
                t = re.sub(r"\\s+([.,;])", r"\\1", NARR_I.sub("", t))
            done.add(ent)
            # 3: nothing new since this entity's last row
            if last.get(ent) == t:
                stats["repeat rows dropped"] += 1
                log.write("REPEAT %d:%d %s\\n" % (o, pn, w))
                continue
            last[ent] = t
            f.write''')

sub('''    alias_out["_not_people"] = sorted(notpeople)''',
    '''    for k, v in epithets.items():
        t = rename.get(cur(k), cur(k))
        if t in alias_out:
            alias_out[t] = sorted(set(alias_out[t]) | v)
    alias_out["_not_people"] = sorted(notpeople)''')

sub('''    main(sys.argv[1], sys.argv[2])''', '''    main(sys.argv[1], sys.argv[2], sys.argv[3])''')

open(sys.argv[2], "w", encoding="utf-8").write(src)
print("ok")
