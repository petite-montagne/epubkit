"""delta6b.py -> delta6c.py: code-only fixes, replayed from the same saved answers."""
import sys

src = open(sys.argv[1], encoding="utf-8").read()


def sub(old, new, count=1):
    global src
    assert src.count(old) == count, (src.count(old), old[:80])
    src = src.replace(old, new)


sub('''"""Step 2g (delta6b): delta5 replayed from its saved answers, no new model calls.
''', '''"""Step 2g (delta6c): delta5 replayed from its saved answers, no new model calls.

delta6c, code only:
- A clause the model already hedged ("suspected of stealing") is kept.
- Phrases that only look like claims are not claims: "his stolen ring",
  "dead leaves", "tries to kill", "witnessed the murder".
- A claim is also backed by any sentence of the part that names the person
  and says it.
- An identity statement in the quote ("I am X", "X is a Y", "named X") backs
  a reveal. A first-person quote names the person attributed to it in the
  same paragraph.
- A bare surname that ends two people's names is never merged, never its own
  entity, never an alias of a new one and never a display name. A new
  entity's alias that is another entity's name is dropped (Peter/Percy).
- Species words (AI, Dromedarian, Grull...) are not people.
- Display-name ties break by name, so runs are repeatable.
''')

sub('PRON = re.compile(', '''# not a claim about the person: someone else's stolen thing, dead leaves,
# a threat or an attempt, a death they only saw
NONCLAIM = re.compile(r"\\b(?:(?:his|her|their|its|my|your|[a-z]+ s) (?:stolen|missing)"
                      r"|dead (?:nature|leaves|plants?|flowers?|trees?|wood|skin|end|zone|silence|weight|air|things|"
                      r"animals?|birds?|fish|insects?)"
                      r"|(?:will|would|could|might|may|wants? to|wanted to|tr(?:y|ies|ying|ied) to|attempts? to|"
                      r"attempted to|plans? to|threatens? to|going to|intends? to) (?:\\w+ )?(?:kill|murder|steal|rob|slay)\\w*"
                      r"|witness\\w* (?:\\w+ ){0,4}?(?:death|murder|killing|dying))\\b")
# an identity statement backs a reveal: "I am Lord Voldemort", "it's a basilisk"
IDENT = re.compile(r"\\bi am\\b|\\bi m\\b|\\b[a-z]+ is (?:a|an|the)\\b|\\b[a-z]+ s (?:a|an)\\b|\\bnamed\\b")
REVEAL = re.compile(r"reveal\\w*|is actually|is really|secretly|true identity|real name", re.I)
FIRSTP = re.compile(r"\\b(?:i|me|my|i m|we)\\b")
SPECIES = {"ai", "dromedarian", "dromedarians", "bactrian", "bactrians", "changeling", "changelings", "anser", "ansers",
           "grull", "grulls", "npc", "npcs"}
PRON = re.compile(''')

# shared surnames
sub('''    def find(name):''', '''    def shared():
        """Words that end the multi-word names of two or more entities."""
        own = collections.defaultdict(set)
        for e in known:
            for x in names(e):
                w = low(x).split()
                if len(w) > 1:
                    own[w[-1]].add(e)
        return {w for w, es in own.items() if len(es) > 1}

    def find(name):''')
sub('''                return k
        b = bare(norm(name))
        fits = [k for k in known if b and b in {bare(x) for x in names(k)}]''', '''                return k
        if len(norm(name).split()) == 1 and low(norm(name)) in shared():   # "Mrs. Weasley" is not bare
            return None
        b = bare(norm(name))
        fits = [k for k in known if b and b in {bare(x) for x in names(k)}]''')

sub('''        exact = next((k for k in known if plain(name) in {plain(x) for x in names(k)}), None)
        if typ not in PERSONLIKE and not exact:''', '''        w0 = low(name).split()
        if low(name) in SPECIES or (w0 and w0[0] in SPECIES and not proper(name)):
            for n in [name] + aliases:
                notpeople[n] = "species"
            log.write("  NOTPERSON %s (species)\\n" % name)
            return
        exact = next((k for k in known if plain(name) in {plain(x) for x in names(k)}), None)
        if not exact and len(norm(name).split()) == 1 and low(name) in shared():
            log.write("  SHAREDNAME %s: a surname of two or more people, not added\\n" % name)
            return
        if typ not in PERSONLIKE and not exact:''')

sub('''        if name in known:
            return
        intro = check_intro(name, aliases, desc, ev, ptext)''', '''        if name in known:
            return
        sh = shared()
        gone = [a for a in aliases if (len(norm(a).split()) == 1 and low(a) in sh) or any(plain(a) in {plain(x) for x in names(e)} for e in known)]
        if gone:
            log.write("  ALIASDROP %s: %s (another entity's name or a shared surname)\\n" % (name, gone))
            aliases = [a for a in aliases if a not in gone]
        intro = check_intro(name, aliases, desc, ev, ptext, text)''')

# check_intro: hedged clauses, non-claims, part-wide backing, identity reveals
sub('''    def check_intro(name, aliases, desc, ev, ptext):''', '''    def check_intro(name, aliases, desc, ev, ptext, text):''')
sub('''        q, w = strip(ev), strip(near)
''', '''        q, w = strip(ev), strip(near)
        mine = {squash(x) for x in [name, *aliases] if squash(x)}
        about = [strip(s) for s in re.split(r"[.!?]", text)
                 if any(re.search(r"\\b%s\\b" % re.escape(x), squash(s)) for x in mine)]
''')
sub('''            c = strip(cl)
            bad = [kind for kind, (say, back) in CLAIMS.items()
                   if re.search(r"\\b(%s)\\b" % say, c) and not re.search(r"\\b(%s)\\b" % back, q)
                   and not re.search(r"\\b(%s)\\b" % back, w)]''', '''            c = NONCLAIM.sub(" ", strip(cl))
            bad = [] if HEDGE.search(c) else \\
                [kind for kind, (say, back) in CLAIMS.items()
                 if re.search(r"\\b(%s)\\b" % say, c) and not re.search(r"\\b(%s)\\b" % back, q)
                 and not re.search(r"\\b(%s)\\b" % back, w)
                 and not any(re.search(r"\\b(%s)\\b" % back, s) for s in about)
                 and not (kind == "reveal" and IDENT.search(sq))]''')

# verify: first person in an attributed paragraph, identity reveals
sub('''    def verify(k, u, text, ptext):''', '''    def verify(k, u, text, ptext, seg):''')
sub('''            why = verify(k, u, text, ptext)''', '''            why = verify(k, u, text, ptext, seg)''')
sub('''        if not (hit(mine, sq) or hit(forms(k) + sorted(epithets[k]), before)):
            return "quote does not name them"''', '''        # "I am Lord Voldemort": first person, said by them in that paragraph
        said = FIRSTP.search(sq) and any(sq[:40] in squash(t) and hit(forms(k) + sorted(epithets[k]), squash(t))
                                         for _n, t in seg)
        if not (hit(mine, sq) or hit(forms(k) + sorted(epithets[k]), before) or said):
            return "quote does not name them"''')
sub('''        if BIG.search(claim) and not BIGQ.search(q):''', '''        big = [m.group(0) for m in BIG.finditer(claim)]
        if big and all(REVEAL.fullmatch(b) for b in big) and IDENT.search(sq):
            return ""
        if BIG.search(claim) and not BIGQ.search(q):''')

# code merge never uses a shared surname
sub('''    rename = {}
    for n in known:
        for s in allnames[n]:
            if " " in s or len(s) < 3 or s in common:''', '''    rename = {}
    sh = shared()
    for n in known:
        for s in allnames[n]:
            if " " in s or len(s) < 3 or s in common or s in sh:''')

# display names: no shared one-word names, no species, ties by name
sub('''    shown = {}
    for t, al in group.items():
        cands = [x for x in al if proper(x) and not titled(x)] or [x for x in al if proper(x)] or [t]''', '''    shown = {}
    owners = collections.defaultdict(set)
    for t, al in group.items():
        for x in al:
            w = low(x).split()
            owners[w[-1] if w else ""].add(t)
    one = lambda x: len(x.split()) == 1
    ok = lambda x: proper(x) and low(x) not in SPECIES and not (one(x) and len(owners[low(x)]) > 1)

    def pick(al, t):
        return [x for x in al if ok(x) and not titled(x)] or [x for x in al if ok(x)] \\
            or [x for x in al if proper(x) and not titled(x)] or [x for x in al if proper(x)] or [t]
    for t, al in group.items():
        cands = pick(al, t)''')
sub('''        cands = [x for x in al if proper(x) and not titled(x)] or [x for x in al if proper(x)] or [w]''',
    '''        cands = pick(al, w)''')
sub('''key=lambda x: (used(x), len(x.split())))''', '''key=lambda x: (used(x), len(x.split()), x))''', count=4)

sub('''f.write("delta6b: delta5 replayed; time-aware names, sticky merges, no repeated rows\\n\\n")''',
    '''f.write("delta6c: delta5 replayed; time-aware names, sticky merges, no repeated rows; code-only claim and name fixes\\n\\n")''')

open(sys.argv[2], "w", encoding="utf-8").write(src)
print("ok")
