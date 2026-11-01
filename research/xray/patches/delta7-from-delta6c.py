"""delta6c.py -> delta7.py: live, repeatable, catches people named once, code-found nickname pairs."""
import sys

src = open(sys.argv[1], encoding="utf-8").read()


def sub(old, new, count=1):
    global src
    assert src.count(old) == count, (src.count(old), old[:80])
    src = src.replace(old, new)


sub('''"""Step 2g (delta6c): delta5 replayed from its saved answers, no new model calls.
''', '''"""Step 2h (delta7): delta6c, run live ("live" as the third argument) or replayed.

delta7:
- Repeatable: every request sends cache_prompt false, a fixed seed and top_k 1
  (temperature 0), and every list in the prompt is sorted.
- People named once: code sweeps each part for speakers, titled names
  (Mr/Professor/Uncle...), names introduced as names ("named X") and
  mid-sentence capitalised names, and asks about each one not in the table.
  A name asked twice with no result is not asked again.
- Nickname pairs: code finds candidate pairs ("X, also known as Y", a shared
  epithet, Mr. Malfoy vs Lucius Malfoy, two names for one speaker in one
  paragraph) and asks the guard about those pairs only. SAME merges.

delta6c notes follow.
''')

sub('CHECK_MAX, UNLISTED_MAX = 12, 6', '''CHECK_MAX, UNLISTED_MAX, PAIR_MAX = 12, 10, 6
SEED = 7
CAP = r"[A-Z][A-Za-z'’\\-]+"
TITLE_WORDS = (r"Mr|Mrs|Ms|Miss|Mister|Madam|Madame|Dr|Doctor|Professor|Uncle|Aunt|Auntie|Sir|Lady|Lord|Dame|"
               r"Captain|Coach|King|Queen|Prince|Princess")
TITLED_NAME = re.compile(r"\\b(?:%s)\\.?\\s+%s(?:\\s+%s){0,2}" % (TITLE_WORDS, CAP, CAP))
INTRO_NAME = re.compile(r"\\b(?:named|called|known as|name is|name was)\\s+(%s(?:\\s+%s){0,2})" % (CAP, CAP))
# two to four capitalised words in mid-sentence ("the Mad Dune Mage")
MULTI_NAME = re.compile(r"(?<=[a-z,;] )(%s(?:\\s+%s){1,3})" % (CAP, CAP))
# last words that make a capitalised phrase a place, group, thing or brand, not a person
PLACEY = {"ocean", "sea", "river", "lake", "canyon", "island", "islands", "mountain", "mountains", "mount", "valley",
          "street", "avenue", "boulevard", "road", "square", "park", "bridge", "city", "town", "village", "county",
          "state", "states", "kingdom", "empire", "university", "college", "school", "academy", "camp", "council",
          "team", "system", "station", "building", "tower", "castle", "hall", "house", "hotel", "casino", "restaurant",
          "cafe", "bar", "pub", "shop", "store", "market", "mall", "inn", "airport", "church", "temple", "forest", "woods",
          "desert", "pole", "beach", "falls", "bay", "harbor", "harbour", "port", "district", "quarter", "floor", "level",
          "zone", "dungeon", "games", "show", "revolution", "invaders", "girls", "boys", "musketeers", "juice", "tree",
          "rangers", "times", "day", "week", "month", "year", "war", "wars", "cup", "prize", "club", "guild", "corps",
          "company", "corporation", "inc", "news", "network", "channel", "festival", "party", "army", "navy", "elders",
          "three", "two", "four", "ii", "iii", "iv", "ranchers", "fro-yo", "mead", "eagle", "sailor", "treat", "plumbing"}
PLACE_FIRST = {"mount", "mt", "team", "camp", "lake", "fort", "new", "outer", "upper", "lower", "north", "south", "east",
               "west", "port", "saint", "st", "planet", "operation", "project", "you", "this", "that", "what", "when"}
AKA_PAIR = re.compile(r"(%s(?:\\s+%s){0,3}),?\\s+(?:also known as|aka|a\\.k\\.a\\.|better known as|otherwise known as|"
                      r"who goes by|whose real name (?:is|was))\\s+(?:the\\s+)?(%s(?:\\s+%s){0,3})" % (CAP, CAP, CAP, CAP))''')

sub('''class Saved:''', '''class Fixed(OpenAIProvider):
    """Same answer for the same prompt: no reused prompt cache, one seed, greedy."""
    def _post(self, url, payload, headers):
        if url.endswith("/chat/completions"):
            payload = dict(payload, cache_prompt=False, seed=SEED, top_k=1)
        return super()._post(url, payload, headers)


class Saved:''')

sub('''    steps, verdicts = replay(saved)
    ai = Saved(steps)
    moved = {}''', '''    live = saved == "live"
    if live:
        steps, verdicts = [], {}
        ai = Fixed("qwen3.6-35b-a3b", "http://localhost:8081", key(), timeout=600, max_tokens=2000, temperature=0)
    else:
        steps, verdicts = replay(saved)
        ai = Saved(steps)
    asked = collections.Counter()   # unlisted name -> times asked with no result
    asked_pairs = set()
    moved = {}''')

sub('''    def guard(a, b_name, b_who):
''', '''    def guard(a, b_name, b_who):
        if live:
            calls["guard"] += 1
            r = ai.complete(GUARD.format(a=entry(a), b=b_name + ": " + b_who), system=SYSTEM).text.strip()
            log.write("GUARD %s | %s -> %s\\n" % (a, b_name, r.splitlines()[0] if r else ""))
            return r.upper().startswith("SAME")
''')

sub('''    def add(p, order, seg, text, ptext):''', '''    def sweep(text, talk):
        """Person-like names in this part that are not in the table: speakers,
        titled names, names introduced as names, mid-sentence capitalised names."""
        def fresh(n):
            return n and n not in NOT_NAMES and low(n) not in KIN and n not in notpeople and asked[n] < 2 \\
                and plain(n) not in {plain(x) for x in notpeople} and not find(n) \\
                and not all(w.strip(".") in STOPW | KIN for w in low(n).split()) \\
                and low(n).split()[-1] not in PLACEY and low(n).split()[0] not in PLACE_FIRST and not re.search(r"[’'](?:d|ll|s|re|ve|m)$", n)
        groups = [sorted(talk),
                  sorted({m.group(0) for m in TITLED_NAME.finditer(text)}),
                  sorted({m.group(1) for m in INTRO_NAME.finditer(text)}),
                  sorted({m.group(1) for m in MULTI_NAME.finditer(text)
                          if not TITLED_NAME.match(m.group(1))})]
        out = []
        for g in groups:
            for n in g:
                n = norm(n)
                if n not in out and fresh(n):
                    out.append(n)
        return out

    def merge(a, b, why):
        """A SAME verdict on a code-found pair: one entity, the untitled and
        fuller name as its key."""
        main_name = min((a, b), key=lambda k: (titled(k), -len(k.split()), k != a))
        other = b if main_name == a else a
        m, o = known.pop(main_name), known.pop(other)
        m["aliases"] = sorted({other, *m["aliases"], *o["aliases"]} - {main_name})
        m["narrator"] = m["narrator"] or o["narrator"]
        m["change"] = m["change"] or o["change"]
        known[main_name] = m
        moved[other] = main_name
        epithets[main_name] |= epithets.pop(other, set())
        log.write("  PAIRMERGE %s + %s -> %s (%s)\\n" % (a, b, main_name, why))

    def pairs(text, seg, here):
        """Candidate nickname pairs from the text's own evidence, in a fixed order."""
        out = []
        for m in AKA_PAIR.finditer(text):
            a, b = find(m.group(1)), find(m.group(2))
            if a and b and a != b:
                out.append((a, b, "also known as: %s / %s" % (m.group(1), m.group(2))))
        for a in here:
            for b in here:
                if a >= b:
                    continue
                if epithets[a] & epithets[b]:
                    out.append((a, b, "shared epithet %s" % sorted(epithets[a] & epithets[b])[0]))
                elif squash(a) in epithets[b] or squash(b) in epithets[a]:
                    out.append((a, b, "one's name is the other's epithet"))
        # Mr. Malfoy / Lucius Malfoy
        for a in here:
            for x in names(a):
                w = low(x).split()
                if len(w) < 2 or not titled(x):
                    continue
                for b in here:
                    if b != a and not titled(b) and any(len(low(y).split()) >= 2 and not titled(y)
                                                        and low(y).split()[-1] == w[-1] for y in names(b)):
                        out.append((a, b, "title and surname: %s / %s" % (x, b)))
        # one speaker named two ways in one paragraph
        for _n, t in seg:
            if len(re.findall(r"[“\\"][^”\\"]+[”\\"]", t)) > 2:
                continue
            who_ = sorted({find(m.group(2) or m.group(3)) for m in SPEECH.finditer(t)} - {None})
            if len(who_) == 2:
                out.append((who_[0], who_[1], "two speaker names in one paragraph"))
        return out

    def add(p, order, seg, text, ptext):''')

# sorted, stable prompts
sub('''                       key=lambda k: (not known[k]["narrator"], -counts[k]))[:CHECK_MAX]
        unl = [n for n in sorted(talk) if not find(n) and n not in notpeople
               and len(re.findall(r"\\b%s\\b" % re.escape(n), text)) >= 2]
        unl = [(h, hint) for h, hint in hero.items() if not find(h) and in_text(h, ptext)] + \\
              [(n, "") for n in unl if n not in hero]
        unl = unl[:UNLISTED_MAX]
        manifest = "\\n".join("- " + entry(n)[:DESC + len(n)] for n in known) or "(none yet)"''',
    '''                       key=lambda k: (not known[k]["narrator"], -counts[k], k))[:CHECK_MAX]
        unl = [(h, hint) for h, hint in sorted(hero.items()) if not find(h) and in_text(h, ptext)] + \\
              [(n, "") for n in sweep(text, talk) if n not in hero]
        unl = unl[:UNLISTED_MAX]
        manifest = "\\n".join("- " + entry(n)[:DESC + len(n)] for n in sorted(known)) or "(none yet)"''')
sub('''        utext = ("\\nUNLISTED (named in this text, not in KNOWN PEOPLE yet):\\n" +
                 "\\n".join("- " + n + hint for n, hint in unl) + "\\n") if unl else ""''',
    '''        utext = ("\\nUNLISTED names in this part: " + "; ".join(n + hint for n, hint in unl) +
                 " -- for each, is it a person, and if so who, with a quote? Put each in \\"new\\" with its real "
                 "type (a name that is not a person gets its own type: place, item, group, title...).\\n") if unl else ""''')

# after the part: unlisted bookkeeping and nickname pairs
sub('''        if missed:
            stats["unanswered"] += len(missed)
            log.write("  UNANSWERED %s\\n" % missed)
''', '''        if missed:
            stats["unanswered"] += len(missed)
            log.write("  UNANSWERED %s\\n" % missed)
        for n, _h in unl:
            if not find(n) and n not in notpeople:
                asked[n] += 1
                log.write("  NOANSWER %s (asked %d)\\n" % (n, asked[n]))
        here = [k for k in sorted(known) if count(k, ptext) > 0]
        done = 0
        for a, b, why in pairs(text, seg, here):
            fp = frozenset((a, b))
            if done >= PAIR_MAX or a not in known or b not in known or a == b or fp in never or fp in asked_pairs:
                continue
            asked_pairs.add(fp)
            done += 1
            calls["pair"] += 1
            log.write("PAIR %s | %s: %s\\n" % (a, b, why))
            if guard(a, b, who(b)):
                merge(a, b, why)
            else:
                never.add(fp)
''')

sub('''    if ai.steps:''', '''    if getattr(ai, "steps", None):''')
sub('''        f.write("delta6c: delta5 replayed; time-aware names, sticky merges, no repeated rows; code-only claim and name fixes\\n\\n")''',
    '''        f.write(("delta7 live:" if live else "delta7: replayed;") +
                " repeatable, people named once, code-found nickname pairs\\n\\n")''')
sub('''    print("calls:", dict(calls))''', '''    print("calls:", dict(calls), "minutes: %.1f" % ((time.time() - t0) / 60))''')

open(sys.argv[2], "w", encoding="utf-8").write(src)
print("ok")
