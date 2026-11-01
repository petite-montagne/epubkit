"""delta6.py -> delta6b.py: first descriptions get the same claim check as changes."""
import sys

src = open(sys.argv[1], encoding="utf-8").read()


def sub(old, new, count=1):
    global src
    assert src.count(old) == count, (src.count(old), old[:80])
    src = src.replace(old, new)


sub('''"""Step 2g (delta6): delta5 replayed from its saved answers, no new model calls.
''', '''"""Step 2g (delta6b): delta5 replayed from its saved answers, no new model calls.

delta6b: a first description gets the B check that changes get. It is split
into clauses; a clause with a big claim (crime, death, reveal, romance,
betrayal), names stripped, must be backed by a word of the same kind in its
quote or the lines around it. If not, it is softened to the text's own hedge
("suspected of stealing") or dropped. Each change is logged as INTRODROP.
''')

sub('PRON = re.compile(', '''# claim kind -> (words that make the claim, words that back it)
CLAIMS = {
    "death": (r"die[ds]?|dying|dead|death|kill\\w*|slain|slay\\w*|murder\\w*",
              r"die[ds]?|dying|dead|death|kill\\w*|slain|slay\\w*|murder\\w*|corpse|body|grave"),
    "crime": (r"stole|steal\\w*|stolen|theft|thie[fv]\\w*|rob(s|bed|bing|ber\\w*)?|crimes?|criminal|guilty|culprit|framed",
              r"stole|steal\\w*|stolen|theft|thie[fv]\\w*|rob(s|bed|bing|ber\\w*)?|crimes?|criminal|guilty|culprit|framed"),
    "betrayal": (r"betray\\w*|traitor\\w*|double agent|spy|spies|spying",
                 r"betray\\w*|traitor\\w*|double agent|spy|spies|spying"),
    "pregnancy": (r"pregnan\\w*", r"pregnan\\w*|baby|expecting"),
    "reveal": (r"reveal\\w*|is actually|is really|secretly|true identity|real name|in disguise",
               r"reveal\\w*|actually|really|true|real name|identity|disguise\\w*|secret\\w*"),
    "romance": (r"lover|girlfriend|boyfriend|fianc\\w*|engaged|affair|married|wife|husband|crush|romantic\\w*|dating",
                r"lover|girlfriend|boyfriend|fianc\\w*|engaged|affair|married|wife|husband|crush|kiss\\w*|love[ds]?|dating|date"),
}
HEDGE = re.compile(r"\\b(suspect\\w*|accus\\w*|allege\\w*|blame[ds]?|rumou?r\\w*|framed)\\b")
# "allegedly stole" -> "suspected of stealing"
GERUND = {"stole": "stealing", "steals": "stealing", "stolen": "stealing", "robbed": "robbing", "killed": "killing",
          "murdered": "murdering", "betrayed": "betraying", "kills": "killing", "betrays": "betraying"}
CLAUSE = re.compile(r"(,\\s+|;\\s+|\\s+(?:and|but|who|which|whose)\\s+|\\s+that\\s+(?=(?:was|were|is|are|has|had)\\b))")
PRON = re.compile(''')

sub('''    def verify(k, u, text, ptext):''', '''    def check_intro(name, aliases, desc, ev, ptext):
        """The intro with each big claim its quote does not back softened or dropped."""
        gone = {name, *aliases} | {x for e in known for x in names(e)}

        def strip(s):
            s = squash(s)
            for x in sorted({squash(x) for x in gone if x}, key=len, reverse=True):
                s = re.sub(r"\\b%s\\b" % re.escape(x), " ", s)
            return s
        sq = squash(ev)
        at = ptext.find(sq[:40]) if sq else -1
        near = ptext[max(0, at - 300):at + len(sq) + 300] if at >= 0 else ""
        q, w = strip(ev), strip(near)
        bits = CLAUSE.split(desc)
        changed = []
        pieces = [("", bits[0])] + [(bits[i], bits[i + 1]) for i in range(1, len(bits) - 1, 2)]
        out = []
        for sep, cl in pieces:
            c = strip(cl)
            bad = [kind for kind, (say, back) in CLAIMS.items()
                   if re.search(r"\\b(%s)\\b" % say, c) and not re.search(r"\\b(%s)\\b" % back, q)
                   and not re.search(r"\\b(%s)\\b" % back, w)]
            if not bad:
                out.append((sep, cl))
                continue
            hedge = HEDGE.search(q) or HEDGE.search(w)
            verb = re.search(r"\\b(?:allegedly |reportedly |supposedly )?(%s)\\b" % "|".join(GERUND), cl)
            if hedge and verb and set(bad) <= {"crime", "death"}:
                new = cl[:verb.start()] + "suspected of " + GERUND[verb.group(1)] + cl[verb.end():]
                if sep.strip() in ("who", "which", "that", "and", "but") and not re.match(r"(is|was|are|were) ", new):
                    new = "is " + new
                out.append((sep, new))
                changed.append("softened %s (%s; text says %s)" % (cl.strip(" ."), "/".join(bad), hedge.group(1)))
            else:
                changed.append("dropped %s (%s)" % (cl.strip(" ."), "/".join(bad)))
                # "goose who killed X and attacks" -> "goose who attacks"
                if sep.strip() in ("who", "which", "that"):
                    nxt = pieces.index((sep, cl)) + 1
                    if nxt < len(pieces) and pieces[nxt][0].strip() in ("and", "but"):
                        pieces[nxt] = (sep, pieces[nxt][1])
        if not changed:
            return desc
        # keep the sentence's own end
        end = desc.rstrip()[-1:] if desc.rstrip()[-1:] in ".!?" else ""
        if not out:
            new = ""
        else:
            new = out[0][1] + "".join(s + c for s, c in out[1:])
            new = new.rstrip(" ,;.!?") + end
            new = new[:1].upper() + new[1:]
        stats["intros changed"] += 1
        log.write("  INTRODROP %s: %s\\n    before: %s\\n    after:  %s\\n" % (name, "; ".join(changed), desc, new))
        return new

    def verify(k, u, text, ptext):''')

sub('''        known[name] = dict(aliases=aliases, type=typ, first=sentence(desc, FIRST_WORDS), change="", narrator=False)
        m = ROLE.match(desc)''', '''        intro = check_intro(name, aliases, desc, ev, ptext)
        known[name] = dict(aliases=aliases, type=typ, first=sentence(intro, FIRST_WORDS), change="", narrator=False)
        m = ROLE.match(desc)''')

sub('''        f.write("delta6: delta5 replayed''', '''        f.write("delta6b: delta5 replayed''')

open(sys.argv[2], "w", encoding="utf-8").write(src)
print("ok")
