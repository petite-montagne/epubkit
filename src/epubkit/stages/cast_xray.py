"""The who's who, X-Ray style (recaps.cast_method = "xray").

Built from the Nov 2026 trials on Dungeon Crawler Carl 4 and 5, Harry Potter
1 and 2 and Percy Jackson 6 (research/xray/delta7.py on the
claude/xray-source branch). The book is read part by part, in order, and
three rules keep the list honest:

A. **Code decides who is covered.** A table holds every person and the names
   they go by. For each part, code finds the known people it mentions (two
   mentions, or a speaking line) and asks one narrow question about each:
   CHANGED or SAME, with a quote. Names that speak or look like a person but
   are not in the table yet are put to the model as UNLISTED, so nobody is
   missed because the model did not bring them up.
B. **Claims are checked, not trusted.** A new person needs a quote from the
   part that names them. A change is {name, now, event, other, quote}: the
   quote must be in the text and name the person; a death, killing,
   betrayal, pregnancy or reveal also needs a matching word in it. A first
   description is split into clauses and each big claim in it gets the same
   check: unbacked clauses are softened to the text's own hedge ("suspected
   of stealing") or dropped.
C. **A person is one record with all their names.** A new name is resolved
   against every known name first; the model's DIFFERENT ENTITIES guard
   decides when two could be one person, and family is never merged: a
   surname with a title ("Mr. Malfoy") never matches someone by the surname
   alone, two full names with one surname and different given names are two
   people, and an entry that calls the other a relative is someone else.
   Only person-like types get entries; places, companies and items do not.

Entries are filed where the book says them, and an entry shows only the
names the book has used by then, so a reveal is never given away early.

Rows have the same shape as cast.build's, so the Kobo side does not change.
With ai.seed set, a local model gives the same list for the same book on
every run.
"""
from __future__ import annotations

import collections
import json
import os
import re

from . import cast as C

PASSAGE = 16000
DESC = 90
FIRST_WORDS, CHANGE_WORDS = 24, 16
CHECK_MAX, UNLISTED_MAX, PAIR_MAX = 12, 10, 6
CAP = r"[A-Z][A-Za-z'’\-]+"
TITLE_WORDS = (r"Mr|Mrs|Ms|Miss|Mister|Madam|Madame|Dr|Doctor|Professor|Uncle|Aunt|Auntie|Sir|Lady|Lord|"
               r"Dame|Captain|Coach|King|Queen|Prince|Princess")
TITLED_NAME = re.compile(r"\b(?:%s)\.?\s+%s(?:\s+%s){0,2}" % (TITLE_WORDS, CAP, CAP))
INTRO_NAME = re.compile(r"\b(?:named|called|known as|name is|name was)\s+(%s(?:\s+%s){0,2})"
                        % (CAP, CAP))
#: two to four capitalised words in mid-sentence ("the Mad Dune Mage")
MULTI_NAME = re.compile(r"(?<=[a-z,;] )(%s(?:\s+%s){1,3})" % (CAP, CAP))
#: last words that make a capitalised phrase a place, group, thing or brand
PLACEY = {"ocean", "sea", "river", "lake", "canyon", "island", "islands", "mountain", "mountains",
          "mount", "valley", "street", "avenue", "boulevard", "road", "square", "park", "bridge",
          "city", "town", "village", "county", "state", "states", "kingdom", "empire",
          "university", "college", "school", "academy", "camp", "council", "team", "system",
          "station", "building", "tower", "castle", "hall", "house", "hotel", "casino",
          "restaurant", "cafe", "bar", "pub", "shop", "store", "market", "mall", "inn",
          "airport", "church", "temple", "forest", "woods", "desert", "pole", "beach", "falls",
          "bay", "harbor", "harbour", "port", "district", "quarter", "floor", "level", "zone",
          "dungeon", "games", "show", "revolution", "invaders", "girls", "boys", "rangers",
          "times", "day", "week", "month", "year", "war", "wars", "cup", "prize", "club",
          "guild", "corps", "company", "corporation", "inc", "news", "network", "channel",
          "festival", "party", "army", "navy", "elders", "ii", "iii", "iv"}
PLACE_FIRST = {"mount", "mt", "team", "camp", "lake", "fort", "new", "outer", "upper", "lower",
               "north", "south", "east", "west", "port", "saint", "st", "planet", "operation",
               "project", "you", "this", "that", "what", "when"}
AKA_PAIR = re.compile(r"(%s(?:\s+%s){0,3}),?\s+(?:also known as|aka|a\.k\.a\.|better known as|"
                      r"otherwise known as|who goes by|whose real name (?:is|was))\s+(?:the\s+)?"
                      r"(%s(?:\s+%s){0,3})" % (CAP, CAP, CAP, CAP))
RANKS = (r"^(king|queen|prince|princess|emperor|empress|duke|duchess|count|countess|baron|lady|"
         r"lord|master|mistress|captain|general|chief|saint|st|father|mother|brother|sister|big|"
         r"little|old|young)\s+")
TITLES = (r"^(mr|mrs|ms|miss|mister|madam|madame|professor|prof|sir|uncle|aunt|lord|the|dr|"
          r"doctor|god|goddess|hunter|crawler)\s+")
PERSONLIKE = {"person", "creature", "animal", "ai", "god", "deity", "monster", "character", "pet",
              "spirit", "ghost"}
#: generic words that are never anyone's name
GENERIC = {"ai", "npc", "npcs", "narrator", "player", "players", "crawler", "crawlers"}
BIG = re.compile(r"\b(die[ds]?|dying|dead|death|kill\w*|slain|slay\w*|murder\w*|drown\w*|"
                 r"perish\w*|execut\w*|betray\w*|"
                 r"pregnan\w*|reveal\w*|is actually|is really|secretly|true identity|real name)\b",
                 re.I)
# every way a book says someone died backs a death, not only "died"
BIGQ = re.compile(r"\b(die[ds]?|dying|dead|death|kill\w*|slain|slay\w*|murder\w*|corpse|body|"
                  r"drown\w*|perish\w*|execut\w*|hanged|funeral|buried|lifeless|passed away|"
                  r"betray\w*|pregnan\w*|baby|reveal\w*|actually|really|true|real name|identity|"
                  r"who (he|she) (is|was))\b", re.I)
KIN = {"mom", "mommy", "mum", "mother", "ma", "dad", "daddy", "father", "pa", "papa", "grandma",
       "grandpa", "granny", "grandmother", "grandfather", "nana", "auntie", "aunt", "uncle", "sis",
       "bro", "honey", "baby"}
#: "X's father", "father of X": an entry that names the other as family
RELATIVE = (r"father|mother|dad|mom|mum|parent|son|daughter|child|brother|sister|sibling|twin|"
            r"wife|husband|cousin|uncle|aunt|nephew|niece|grandfather|grandmother|grandson|"
            r"granddaughter|grandparent|grandchild")
ROLE = re.compile(r"^(?:the |a |an )?((?:god|goddess|titan|titaness|spirit|nymph|lord|lady|king|"
                  r"queen|prince|princess) of (?:the )?[a-z]+"
                  r"(?: (?!and\b|or\b|who\b|with\b|in\b|at\b|from\b)[a-z]+)?)\b", re.I)
VERBISH = {"is", "are", "was", "were", "has", "had", "have", "came", "come", "went", "gone", "did",
           "does", "do", "can", "will", "would", "could", "should", "said", "says", "cost", "be",
           "been"}
#: claim kind -> (words that make the claim, words that back it)
CLAIMS = {
    "death": (r"die[ds]?|dying|dead|death|kill\w*|slain|slay\w*|murder\w*",
              r"die[ds]?|dying|dead|death|kill\w*|slain|slay\w*|murder\w*|corpse|body|grave"),
    "crime": (r"stole|steal\w*|stolen|theft|thie[fv]\w*|rob(s|bed|bing|ber\w*)?|crimes?|criminal|"
              r"guilty|culprit|framed",
              r"stole|steal\w*|stolen|theft|thie[fv]\w*|rob(s|bed|bing|ber\w*)?|crimes?|criminal|"
              r"guilty|culprit|framed"),
    "betrayal": (r"betray\w*|traitor\w*|double agent|spy|spies|spying",
                 r"betray\w*|traitor\w*|double agent|spy|spies|spying"),
    "pregnancy": (r"pregnan\w*", r"pregnan\w*|baby|expecting"),
    "reveal": (r"reveal\w*|is actually|is really|secretly|true identity|real name|in disguise",
               r"reveal\w*|actually|really|true|real name|identity|disguise\w*|secret\w*"),
    "romance": (r"lover|girlfriend|boyfriend|fianc\w*|engaged|affair|married|wife|husband|crush|"
                r"romantic\w*|dating",
                r"lover|girlfriend|boyfriend|fianc\w*|engaged|affair|married|wife|husband|crush|"
                r"kiss\w*|love[ds]?|dating|date"),
}
HEDGE = re.compile(r"\b(suspect\w*|accus\w*|allege\w*|blame[ds]?|rumou?r\w*|framed)\b")
GERUND = {"stole": "stealing", "steals": "stealing", "stolen": "stealing", "robbed": "robbing",
          "killed": "killing", "murdered": "murdering", "betrayed": "betraying",
          "kills": "killing", "betrays": "betraying"}
CLAUSE = re.compile(r"(,\s+|;\s+|\s+(?:and|but|who|which|whose)\s+|"
                    r"\s+that\s+(?=(?:was|were|is|are|has|had)\b))")
#: not a claim about the person: someone's stolen thing, dead leaves, a
#: threat or an attempt, a death they only saw
NONCLAIM = re.compile(r"\b(?:(?:his|her|their|its|my|your|[a-z]+ s) (?:stolen|missing)"
                      r"|dead (?:nature|leaves|plants?|flowers?|trees?|wood|skin|end|zone|silence|"
                      r"weight|air|things|animals?|birds?|fish|insects?)"
                      r"|(?:will|would|could|might|may|wants? to|wanted to|tr(?:y|ies|ying|ied) to|"
                      r"attempts? to|attempted to|plans? to|threatens? to|going to|intends? to) "
                      r"(?:\w+ )?(?:kill|murder|steal|rob|slay)\w*"
                      r"|witness\w* (?:\w+ ){0,4}?(?:death|murder|killing|dying))\b")
#: an identity statement backs a reveal: "I am Lord Voldemort"
IDENT = re.compile(r"\bi am\b|\bi m\b|\b[a-z]+ is (?:a|an|the)\b|\b[a-z]+ s (?:a|an)\b|\bnamed\b")
REVEAL = re.compile(r"reveal\w*|is actually|is really|secretly|true identity|real name", re.I)
FIRSTP = re.compile(r"\b(?:i|me|my|i m|we)\b")
SUFFIX = re.compile(r"\s+\d+$")
#: "narrator ..., referred to as 'I'": said once, on the first row only
NARR_I = re.compile(r",?\s*(who is |and is )?(referred to|known|called|identified) as "
                    r"[“\"'‘]?I[”\"'’]?(\s+throughout[^.,;]*)?", re.I)
HONOR = r"^(mr|mrs|ms|miss|mister|madam|madame|sir|dame)\b"
STOPW = {"the", "of", "and", "a", "an", "in", "on", "at", "to", "god", "goddess", "king", "queen",
         "prince", "princess", "lord", "lady", "sir", "miss", "mr", "mrs", "ms", "captain",
         "general", "big", "little", "old", "young", "none"}
EPITHET = re.compile(r"^(.+?),?\s+the\s+(.*)$")
PARTICLES = {"de", "da", "del", "der", "di", "du", "la", "le", "van", "von", "of", "the", "and",
             "al", "bin", "ibn", "y"}
NUM = {w: i + 1 for i, w in enumerate("one two three four five six seven eight nine ten".split())}
SPEECH = re.compile(r"\b(said|asked|says|asks|replied|whispered|shouted|yelled|muttered|called|"
                    r"snapped|cried)\s+([A-Z][a-z'’]+)"
                    r"|\b([A-Z][a-z'’]+)\s+(said|asked|says|asks|replied|whispered|shouted|yelled|"
                    r"muttered|called|snapped|cried)\b")
NOT_NAMES = {"He", "She", "They", "It", "I", "We", "You", "Then", "And", "But", "The", "Someone",
             "Everyone", "Nobody", "Somebody", "Mom", "Dad", "Mum", "Mother", "Father", "Sir",
             "Madam"}
BACK = re.compile(r"^\W*(also by|other (books|titles) by|books (by|from)|more (books|from)|"
                  r"about the authors?|acknowledg|copyright|newsletter|praise for|reading group|"
                  r"discussion (questions|guide)|(an )?excerpt|preview|sneak peek|read on\b|"
                  r"coming soon|a sample|bonus (chapter|content)|titles available|keep reading|"
                  r"turn the page|don.t miss)", re.I)

SYSTEM = ("You keep a spoiler-free list of the people in a novel for a reader. "
          "Work ONLY from the text you are given. Even if you recognise the book, "
          "never use anything you know about it beyond this text.")

STEP = """KNOWN PEOPLE:
{known}

NEW TEXT:
<<<
{text}
>>>
{check}{unlisted}
Return JSON only, in this shape:
{{"new": [{{"name": "...", "type": "...", "aliases": ["..."], "who": "...", "evidence": "..."}}],
  "updates": [{{"name": "...", "status": "SAME or CHANGED", "now": "...", "event": "...", "other": "...", "quote": "..."}}]}}

Rules for "new":
- Every named individual in the NEW TEXT who is not in KNOWN PEOPLE{and_unlisted}.
- "type": one of person, creature, animal, ai, god, monster, company, place, item, group, title.
- "name": the fullest name the text gives. "aliases": other names the text uses for the same individual. Never pronouns. A shared surname is not an alias.
- "who": ONE sentence (under 25 words) on who they are: their lasting role and relation to the main characters, from this text only. Not their mood or what they are doing right now.
- "evidence": a short exact quote (under 20 words) from the NEW TEXT that names them.
Rules for "updates" (one per CHECK name, no others):
- "status": CHANGED only if their role, allegiance, form, rank, relationship or status changes for good in this text; otherwise SAME and leave the other fields empty.
- "now": ONE sentence (under 16 words): who they are now, after the change.
- "event": a few words for the change itself. "other": the other individual involved, or "".
- "quote": a short exact quote (under 25 words) from the NEW TEXT that shows the change and names them.
- If the text shows a person going by a new name, mark them CHANGED and give the new name in "now"."""

GUARD = """Two entries from a character list:

A: {a}
B: {b}

Are A and B the same individual? A parent and child, brothers and sisters, a husband and wife or any two relatives who share a family name are DIFFERENT. If they are different people, the first line of your answer must be exactly DIFFERENT ENTITIES. If they are the same person, the first line must be exactly SAME."""


# ----------------------------------------------------------- name helpers

def low(s: str) -> str:
    """Lower case, titles stripped: "Mr. Malfoy" -> "malfoy"."""
    s = s.lower().replace("’", "'").replace(".", "")
    s = re.sub(r"[_\-·]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    while True:
        t = re.sub(TITLES, "", s)
        if t == s:
            return s
        s = t


def common_words(names) -> set[str]:
    """A word that is a whole name or part of 3+ different names is a title
    or family name, not an identity (koassistant's rule)."""
    c = collections.Counter(w for n in set(names) for w in set(n.split()))
    return {w for w, k in c.items() if k >= 3}


def same(a: str, b: str, common) -> bool:
    """a, b already low(). Exact, or one's words start or end the other's
    (3+ letters, never equal word counts), common words aside."""
    if a == b:
        return True
    wa, wb = a.split(), b.split()
    if len(wa) == len(wb):
        return False
    s, lg = (wa, wb) if len(wa) < len(wb) else (wb, wa)
    if len(" ".join(s)) < 3 or (len(s) == 1 and s[0] in common):
        return False
    return lg[:len(s)] == s or lg[-len(s):] == s


def squash(s: str) -> str:
    return re.sub(r"\W+", " ", s.lower().replace("’", "'")).strip()


def flat(s: str) -> str:
    return re.sub(r"[\W_]+", "", s.lower())


def plain(n: str) -> str:
    """Lower case, punctuation squashed, titles kept (Mr. and Mrs. differ)."""
    return re.sub(r"\s+", " ", re.sub(r"[^\w']+", " ", n.lower().replace("’", "'"))).strip()


def honor(n: str) -> str:
    m = re.match(HONOR, plain(n))
    return m.group(1) if m else ""


def bare(n: str) -> str:
    """low() plus generic ranks."""
    n = low(n)
    while True:
        t = re.sub(RANKS, "", n)
        if t == n or not t:
            return n
        n = t


def titled(n: str) -> bool:
    """The name carries a title or rank (Mr., Queen, Big...)."""
    p = re.sub(r"\s+", " ", re.sub(r"[_\-·]", " ",
                                    n.lower().replace("’", "'").replace(".", ""))).strip()
    return bare(n) != p


def surname_only(n: str) -> bool:
    """A title and one more word: "Mr. Malfoy", "Professor Snape"."""
    return titled(n) and len(bare(n).split()) == 1 and len(plain(n).split()) >= 2


def norm(n) -> str:
    """A name as the table keeps it: spacing tidied, a crawler's " 2" dropped,
    a descriptive tail cut ("Gary the diapered god" -> "Gary")."""
    n = SUFFIX.sub("", re.sub(r"\s+", " ", str(n or "")).strip()).strip()
    m = EPITHET.match(n)
    if m and any(w[:1].islower() and w.lower() not in PARTICLES for w in m.group(2).split()):
        n = m.group(1).strip()
    return n


def proper(n: str) -> bool:
    """A real name, not a description: every word capitalised."""
    ws = n.split()
    if ws and all(w.lower().strip(".,'") in KIN for w in ws):
        return False
    return bool(ws) and all(w[:1].isupper() or w[:1].isdigit() or w.lower() in PARTICLES
                            for w in ws) and ws[0].lower() not in PARTICLES


def in_text(name: str, plain_text: str) -> bool:
    """The name is in the (squashed) text, as written or as "Last, First"."""
    q = squash(name).split()
    return bool(q) and (" ".join(q) in plain_text or
                        (len(q) > 1 and " ".join(q[-1:] + q[:-1]) in plain_text))


def mentions(name: str, ptext: str) -> int:
    q = squash(name)
    return len(re.findall(r"\b%s\b" % re.escape(q), ptext)) if q else 0


def quote_ok(ev: str, text: str) -> bool:
    """The quote is in the text: case, quotes, dashes and spacing aside, an
    ellipsis may skip words, and one word in a quote of five or more may
    differ (the model writes "you" where the book says "we")."""
    f = flat(text)
    bits = [flat(b) for b in re.split(r"\.\s*\.\s*\.|…", ev)]
    bits = [b for b in bits if len(b) >= 8]
    if bits and all(b in f for b in bits):
        return True
    q = squash(ev).split()
    if len(q) < 5:
        return False
    words = squash(text).split()
    n = len(q)
    firsts = {q[0], q[1]}
    for i in range(len(words) - n + 1):
        if words[i] not in firsts and words[i + 1] not in firsts:
            continue
        if sum(a != b for a, b in zip(words[i:i + n], q, strict=True)) <= 1:
            return True
    return False


def sentence(s: str, words: int) -> str:
    """The first sentence, cut to a word budget. "Mr." does not end one."""
    out = []
    for t in s.split():
        out.append(t)
        if re.search(r"[.!?]$", t) and not re.fullmatch(r"[A-Z][a-z]{0,2}\.", t):
            break
    return " ".join(out[:words]).rstrip(",;:") + ("…" if len(out) > words else "")


def kin_of(desc: str, other_forms) -> bool:
    """The description calls one of these names family: "Draco's father",
    "father of Draco", "Harry's aunt"."""
    d = squash(desc)
    for f in other_forms:
        x = squash(f)
        if len(x) < 3:
            continue
        x = re.escape(x)
        if re.search(r"\b%s s (?:\w+ )?(?:%s)\b" % (x, RELATIVE), d) or \
                re.search(r"\b(?:%s) (?:of|to) %s\b" % (RELATIVE, x), d):
            return True
    return False


def same_family(a: str, b: str) -> bool:
    """Two full names, one family name, different given names: two people
    (Draco Malfoy, Lucius Malfoy)."""
    wa, wb = bare(a).split(), bare(b).split()
    return len(wa) >= 2 and len(wb) >= 2 and wa[-1] == wb[-1] and wa[0] != wb[0]


def parse(text: str) -> dict:
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        got = json.loads(m.group(0)) if m else {}
        if isinstance(got, dict):
            return got
    except ValueError:
        pass
    # an answer cut short: keep every complete entry
    got, cut = {"new": [], "updates": []}, (text or "").find('"updates"')
    for o in re.finditer(r"\{[^{}]*\}", text or ""):
        try:
            got["updates" if 0 <= cut < o.start() else "new"].append(json.loads(o.group(0)))
        except ValueError:
            pass
    return got


def _usable_step(t: str) -> bool:
    return bool(re.search(r"\{.*\}", t or "", re.S))


def _usable_guard(t: str) -> bool:
    return (t or "").strip().upper().startswith(("SAME", "DIFFERENT"))


# ----------------------------------------------------------- the book

def chapter_no(label: str, head: str):
    for s in (label, head[:60]):
        m = re.match(r"\W*(?:chapter|ch\.?)\s+(\d+|[a-z]+)\b|\W*(\d+)\b", s, re.I)
        if m:
            w = (m.group(1) or m.group(2)).lower()
            if w.isdigit():
                return int(w)
            if w in NUM:
                return NUM[w]
        if re.match(r"\W*prologue\b", s, re.I):
            return 0
    return None


def story_parts(docs, log: list):
    """The book's own documents: stop at back matter, a sample or the next
    book's chapter 1 in the second half."""
    keep, top, cut = [], 0, None
    for i, (_o, _p, label, ps) in enumerate(docs):
        head = " ".join(t for _n, t in ps[:2])[:200]
        n = chapter_no(label or "", head)
        late = i >= len(docs) // 2
        if late and (BACK.match(label or "") or BACK.match(head)):
            cut = (i, "back matter or sample: %r" % (label or head[:40]))
        elif late and n is not None and n <= 1 and top >= 3:
            cut = (i, "chapter count restarts (%r after chapter %d)" % (label or head[:40], top))
        if cut:
            break
        if n:
            top = max(top, n)
        keep.append(docs[i])
    if cut:
        for o, _p, label, ps in docs[cut[0]:]:
            log.append("cut order %d %r (%d chars): %s"
                       % (o, label, sum(len(t) for _n, t in ps), cut[1]))
    return keep


def heroes(docs) -> dict:
    """The most-mentioned speaking name, and the narrator of a first-person
    book -> {name: hint}."""
    text = "\n".join(t for _o, _p, _l, ps in docs for _n, t in ps)
    talk = collections.Counter(m.group(2) or m.group(3) for m in SPEECH.finditer(text))
    names = [n for n, c in talk.most_common() if n not in NOT_NAMES and c >= 5]
    out = {}
    if names:
        top = max(names[:10], key=lambda n: len(re.findall(r"\b%s\b" % re.escape(n), text)))
        out[top] = ""
    narr = re.sub(r"[“\"][^”\"]*[”\"]", " ", text)
    if len(re.findall(r"\bI\b", narr)) > len(re.findall(r"\b(he|she)\b", narr, re.I)) // 3:
        voc = collections.Counter()
        for q in re.findall(r"[“\"]([^”\"]{0,300})[”\"]", text):
            for m in re.finditer(r"(?:^|[,!?.]\s)([A-Z][a-z'’]+)[,!?.]|,\s([A-Z][a-z'’]+)[.!?,]?$", q):
                n = m.group(1) or m.group(2)
                if n not in NOT_NAMES:
                    voc[n] += 1
        cands = [n for n, c in voc.most_common(12) if c >= 5
                 and len(re.findall(r"[a-z,;]\s+%s\b" % re.escape(n), text)) >= c // 2]
        if cands:
            out[cands[0]] = NARRATOR
    return out


NARRATOR = " They are the narrator, the \"I\" of the story."


def _segments(paras, target: int):
    out, cur, size = [], [], 0
    for n, t in paras:
        cur.append((n, t))
        size += len(t)
        if size >= target:
            out.append(cur)
            cur, size = [], 0
    if cur:
        if out and size < target // 4:
            out[-1].extend(cur)
        else:
            out.append(cur)
    return out


def build(ctx, docs, ask, *, hero: str = "", first_person: bool = False,
          lang: str = "en", view=None, title: str = "", workers: int = 1, names_list=None,
          facts=None, probe=None):
    """Same contract as cast.build. For a book not in English, it is cast.build."""
    if lang != "en" or probe is not None:
        return C.build(ctx, docs, ask, hero=hero, first_person=first_person, lang=lang,
                       view=view, title=title, workers=workers, names_list=names_list,
                       facts=facts, probe=probe)
    return _Run(ctx, docs, ask, hero, first_person).go()


class _Run:
    def __init__(self, ctx, docs, ask, hero, first_person):
        self.ctx, self.ask = ctx, ask
        self.log: list[str] = []
        self.docs = story_parts(docs, self.log)
        self.path_of = {o: p for o, p, _l, _ps in self.docs}
        self.hero = heroes(self.docs)
        if hero:
            self.hero = {hero: NARRATOR if first_person else ""}
        self.lead = hero or next((h for h, hint in self.hero.items() if not hint),
                                 next(iter(self.hero), ""))
        self.asked = collections.Counter()
        self.asked_pairs: set = set()
        self.moved: dict = {}
        self.epithets = collections.defaultdict(set)
        self.known: dict = {}
        self.notpeople: dict = {}
        self.never: set = set()
        self.rows: list = []
        self.seen = ""
        self.calls = collections.Counter()
        self.stats = collections.Counter()
        book_text = "\n".join(t for _o, _p, _l, ps in self.docs for _n, t in ps)
        self.book_sq = squash(book_text)
        # a one-word "name" the book also writes in lower case is a common
        # noun (a species, a job): "changeling", "grull"
        self.lower_words = set(re.findall(r"(?<![\w’'.!?:\"“] )\b([a-z][a-z'’\-]{2,})\b", book_text))
        self.parts = [(o, seg) for o, _p, _l, ps in self.docs for seg in _segments(ps, PASSAGE)]

    # -- the table --------------------------------------------------------

    def who(self, n):
        k = self.known[n]
        return (k["first"] + (" " + k["change"] if k["change"] else "")).strip()

    def entry(self, n):
        k = self.known[n]
        return n + (" (also " + ", ".join(k["aliases"]) + ")" if k["aliases"] else "") + \
            ": " + self.who(n)

    def names(self, k):
        return [k] + self.known[k]["aliases"]

    def shared(self):
        """Words that end the multi-word names of two or more people."""
        own = collections.defaultdict(set)
        for e in self.known:
            for x in self.names(e):
                w = low(x).split()
                if len(w) > 1:
                    own[w[-1]].add(e)
        return {w for w, es in own.items() if len(es) > 1}

    def find(self, name):
        """The person this name is: an exact name or alias; then the same name
        without titles and ranks; then start/end words. Only when exactly one
        person fits. A title with a family name ("Mr. Malfoy") matches only
        a name or alias written that way."""
        p = plain(norm(name))
        for k in self.known:
            if p in {plain(x) for x in self.names(k)}:
                return k
        if surname_only(norm(name)):
            return None
        if len(norm(name).split()) == 1 and low(norm(name)) in self.shared():
            return None
        b = bare(norm(name))
        fits = [k for k in self.known if b and b in {bare(x) for x in self.names(k)}]
        if len(fits) == 1:
            return fits[0]
        n = low(norm(name))
        common = common_words([low(x) for k in self.known for x in self.names(k)])
        fits = [k for k in self.known
                if any(same(n, low(x), common) for x in self.names(k))
                and not (honor(name) and any(honor(x) and honor(x) != honor(name)
                                             for x in self.names(k)))]
        return fits[0] if len(fits) == 1 else None

    def forms(self, k):
        """Ways the text names someone: every alias, plus a first or last word
        that belongs to nobody else."""
        own = {squash(x) for x in self.names(k) if squash(x)}
        owner = collections.defaultdict(set)
        for e in self.known:
            for x in self.names(e):
                for t in low(x).split():
                    owner[t].add(e)
        for x in self.names(k):
            w = low(x).split()
            for t in (w[:1] + w[-1:]) if len(w) > 1 else []:
                if len(t) >= 3 and t not in STOPW and owner[t] == {k}:
                    own.add(squash(t))
        return sorted(own, key=len, reverse=True)

    def count(self, k, ptext):
        f = self.forms(k)
        return len(re.findall(r"\b(?:%s)\b" % "|".join(map(re.escape, f)), ptext)) if f else 0

    def family(self, a_names, a_desc, b_names, b_desc) -> bool:
        """Code's own answer for relatives: never the same person."""
        return any(same_family(x, y) for x in a_names for y in b_names) or \
            kin_of(a_desc, b_names) or kin_of(b_desc, a_names)

    def extends(self, k, name, ptext):
        """A bare given name that starts this one known full name, both used
        so far, and no one else's name starts with that word."""
        a, b = sorted((low(norm(name)), low(k)), key=lambda x: len(x.split()))
        if len(a.split()) != 1 or len(b.split()) < 2 or b.split()[0] != a or len(a) < 3 \
                or a in STOPW:
            return False
        if any(e != k and any(low(x).split()[:1] == [a] for x in self.names(e))
               for e in self.known):
            return False
        return mentions(k, self.seen) > 0 and mentions(name, ptext) > 0

    def guard(self, a, b_name, b_who):
        if self.family(self.names(a), self.who(a), [b_name], b_who):
            self.log.append("family %s | %s -> DIFFERENT (code)" % (a, b_name))
            return False
        self.calls["guard"] += 1
        try:
            r = self.ask(GUARD.format(a=self.entry(a), b=b_name + ": " + b_who), SYSTEM,
                         _usable_guard).strip()
        except Exception:                                    # noqa: BLE001
            r = ""
        self.log.append("guard %s | %s -> %s" % (a, b_name, r.splitlines()[0] if r else ""))
        return r.upper().startswith("SAME")

    def learn_epithets(self, text):
        """ "Hebe, the goddess of youth," ties that epithet to Hebe."""
        for k in self.known:
            for x in self.names(k):
                for m in re.finditer(r"\b%s,\s+(the\s+[a-z][a-z ]{3,40}?)[,.;!?]" % re.escape(x),
                                     text):
                    e = squash(m.group(1))
                    if not VERBISH & set(e.split()) and len(e.split()) <= 5 \
                            and self.book_sq.count(e) >= 2:
                        self.epithets[k].add(e)

    def aka(self, ev, name):
        """Someone the quote itself says this name belongs to."""
        e, n = squash(ev), squash(name)
        for k in self.known:
            for x in self.names(k):
                x = squash(x)
                if not x or x == n:
                    continue
                link = r"(also )?(called|known as|named|nicknamed|aka|or)"
                if re.search(r"\b%s\b %s %s\b" % (re.escape(x), link, re.escape(n)), e) \
                        or re.search(r"\b%s\b %s %s\b" % (re.escape(n), link, re.escape(x)), e) \
                        or re.search(r"\b%s\s*\(\s*%s\s*\)" % (re.escape(x), re.escape(name.lower())),
                                     ev.lower()) \
                        or re.search(r"\b%s\s*\(\s*%s\s*\)" % (re.escape(name.lower()), re.escape(x)),
                                     ev.lower()):
                    return k
        return None

    def common_noun(self, name):
        w = low(name).split()
        return low(name) in GENERIC or (len(w) == 1 and len(name.split()) == 1
                                        and w[0] in self.lower_words)

    def sweep(self, text, talk):
        """Person-like names in this part that are not in the table."""
        def fresh(n):
            return n and n not in NOT_NAMES and low(n) not in KIN and n not in self.notpeople \
                and self.asked[n] < 2 \
                and plain(n) not in {plain(x) for x in self.notpeople} and not self.find(n) \
                and not all(w.strip(".") in STOPW | KIN for w in low(n).split()) \
                and low(n).split()[-1] not in PLACEY and low(n).split()[0] not in PLACE_FIRST \
                and not re.search(r"[’'](?:d|ll|s|re|ve|m)$", n) and not self.common_noun(n)
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

    def _join(self, keep, gone, extra=()):
        """Fold `gone` into `keep`; the untitled, fuller name is the key."""
        main_name = min((keep, gone), key=lambda k: (titled(k), -len(k.split()), k != keep))
        other = gone if main_name == keep else keep
        m, o = self.known.pop(main_name), self.known.pop(other)
        m["aliases"] = sorted({other, *m["aliases"], *o["aliases"], *extra} - {main_name})
        m["narrator"] = m["narrator"] or o["narrator"]
        m["change"] = m["change"] or o["change"]
        self.known[main_name] = m
        self.moved[other] = main_name
        self.epithets[main_name] |= self.epithets.pop(other, set())
        return main_name

    def pairs(self, text, seg, here):
        """Candidate nickname pairs from the text's own evidence."""
        out = []
        for m in AKA_PAIR.finditer(text):
            a, b = self.find(m.group(1)), self.find(m.group(2))
            if a and b and a != b:
                out.append((a, b, "also known as: %s / %s" % (m.group(1), m.group(2))))
        for a in here:
            for b in here:
                if a >= b:
                    continue
                if self.epithets[a] & self.epithets[b]:
                    out.append((a, b, "shared epithet %s" % sorted(self.epithets[a]
                                                                   & self.epithets[b])[0]))
                elif squash(a) in self.epithets[b] or squash(b) in self.epithets[a]:
                    out.append((a, b, "one's name is the other's epithet"))
        # "Mr. Malfoy" may be the one Malfoy with a given name: only when
        # exactly one person has that family name
        for a in here:
            for x in self.names(a):
                if not surname_only(x):
                    continue
                fam = bare(x)
                fits = [b for b in here if b != a and not titled(b)
                        and any(len(bare(y).split()) >= 2 and bare(y).split()[-1] == fam
                                for y in self.names(b))]
                if len(fits) == 1:
                    out.append((a, fits[0], "title and surname: %s / %s" % (x, fits[0])))
        return out

    # -- one answer -------------------------------------------------------

    def add(self, p, order, seg, text, ptext):
        if not isinstance(p, dict):
            return
        name, desc = norm(p.get("name")), str(p.get("who") or "").strip()
        ev, typ = str(p.get("evidence") or "").strip(), str(p.get("type") or "").strip().lower()
        aliases = [norm(a) for a in p.get("aliases") or [] if norm(a) and norm(a) != name]
        if not name or not desc or name in self.notpeople:
            return
        if not in_text(name, ptext) and not any(in_text(a, ptext) for a in aliases):
            self.log.append("drop %s: name not in text" % name)
            return
        if not ev or (squash(ev) not in ptext and not quote_ok(ev, text)):
            if max([mentions(name, self.seen)] + [mentions(a, self.seen) for a in aliases]) >= 3:
                self.log.append("keep %s: quote not in text, but named 3+ times so far" % name)
            else:
                self.log.append("drop %s: evidence not in text" % name)
                return
        if not typ:
            self.log.append("drop %s: no type" % name)
            return
        if self.common_noun(name):
            for n in [name] + aliases:
                self.notpeople[n] = "common noun"
            self.log.append("not a person %s (a word the book also writes in lower case)" % name)
            return
        exact = next((k for k in self.known if plain(name) in {plain(x) for x in self.names(k)}),
                     None)
        # a description word for word someone else's is about them, not this
        # name ("Mr. Malfoy" given Draco's line)
        copied = next((k for k in self.known if k != exact and
                       squash(sentence(desc, FIRST_WORDS)) == squash(self.known[k]["first"])), None)
        if copied:
            self.log.append("drop %s: description is %s's" % (name, copied))
            return
        if not exact and len(name.split()) == 1 and low(name) in self.shared():
            self.log.append("shared family name %s: not added" % name)
            return
        if typ not in PERSONLIKE and not exact:
            for n in [name] + aliases:
                self.notpeople[n] = typ
            self.log.append("not a person %s (%s)" % (name, typ))
            return
        para = next((n for n, t in seg if in_text(name, squash(t))), seg[0][0])
        hit = self.find(name) or next((self.find(a) for a in aliases if self.find(a)), None) \
            or self.aka(ev, name)
        if hit and plain(name) in {plain(x) for x in self.names(hit)}:
            self.known[hit]["aliases"] = sorted(
                set(self.known[hit]["aliases"]) |
                ({a for a in aliases if not self.family(self.names(hit), self.who(hit), [a], "")}
                 - {hit}))
            return
        if hit and self.family(self.names(hit), self.who(hit), [name, *aliases], desc):
            self.log.append("family %s | %s: kept apart" % (hit, name))
            self.never.add(frozenset((hit, name)))
            hit = None
        if hit and self.extends(hit, name, ptext):
            main_name = self._grow(hit, name, aliases)
            self.log.append("joined %s + %s -> %s (given name grows)" % (hit, name, main_name))
            return
        if hit and frozenset((hit, name)) not in self.never:
            if self.guard(hit, name, sentence(desc, FIRST_WORDS)):
                main_name = self._grow(hit, name, aliases)
                self.log.append("joined %s + %s -> %s" % (hit, name, main_name))
                self.rows.append((order, para, main_name, self.who(main_name)))
                return
            self.never.add(frozenset((hit, name)))
        if name in self.known:
            return
        sh = self.shared()
        gone = [a for a in aliases if (len(a.split()) == 1 and low(a) in sh)
                or any(plain(a) in {plain(x) for x in self.names(e)} for e in self.known)]
        if gone:
            self.log.append("aliases dropped for %s: %s (someone else's name or a shared "
                            "family name)" % (name, gone))
            aliases = [a for a in aliases if a not in gone]
        intro = self.check_intro(name, aliases, desc, ev, ptext, text)
        if not intro:
            self.log.append("drop %s: nothing in the description is backed by the text" % name)
            return
        self.known[name] = dict(aliases=aliases, type=typ, first=sentence(intro, FIRST_WORDS),
                                change="", narrator=False)
        m = ROLE.match(desc)
        if m and squash(m.group(1)) in self.book_sq:
            self.epithets[name].add(squash(m.group(1)))
        self.rows.append((order, para, name, self.who(name)))

    def _grow(self, hit, name, aliases):
        k = self.known.pop(hit)
        main_name = name if len(name.split()) > len(hit.split()) else hit
        k["aliases"] = sorted({hit, name, *aliases, *k["aliases"]} - {main_name})
        self.known[main_name] = k
        if main_name != hit:
            self.moved[hit] = main_name
            self.epithets[main_name] |= self.epithets.pop(hit, set())
        return main_name

    def check_intro(self, name, aliases, desc, ev, ptext, text):
        """The first description with each big claim its quote does not back
        softened to the text's own hedge or dropped."""
        gone = {name, *aliases} | {x for e in self.known for x in self.names(e)}

        def strip(s):
            s = squash(s)
            for x in sorted({squash(x) for x in gone if x}, key=len, reverse=True):
                s = re.sub(r"\b%s\b" % re.escape(x), " ", s)
            return s
        sq = squash(ev)
        at = ptext.find(sq[:40]) if sq else -1
        near = ptext[max(0, at - 300):at + len(sq) + 300] if at >= 0 else ""
        q, w = strip(ev), strip(near)
        mine = {squash(x) for x in [name, *aliases] if squash(x)}
        about = [strip(s) for s in re.split(r"[.!?]", text)
                 if any(re.search(r"\b%s\b" % re.escape(x), squash(s)) for x in mine)]
        bits = CLAUSE.split(desc)
        pieces = [("", bits[0])] + [(bits[i], bits[i + 1]) for i in range(1, len(bits) - 1, 2)]
        out, changed = [], []
        for idx, (sep, cl) in enumerate(pieces):
            c = NONCLAIM.sub(" ", strip(cl))
            bad = [] if HEDGE.search(c) else \
                [kind for kind, (say, back) in CLAIMS.items()
                 if re.search(r"\b(%s)\b" % say, c) and not re.search(r"\b(%s)\b" % back, q)
                 and not re.search(r"\b(%s)\b" % back, w)
                 and not any(re.search(r"\b(%s)\b" % back, s) for s in about)
                 and not (kind == "reveal" and IDENT.search(sq))]
            if not bad:
                out.append((sep, cl))
                continue
            hedge = HEDGE.search(q) or HEDGE.search(w)
            verb = re.search(r"\b(?:allegedly |reportedly |supposedly )?(%s)\b" % "|".join(GERUND), cl)
            if hedge and verb and set(bad) <= {"crime", "death"}:
                new = cl[:verb.start()] + "suspected of " + GERUND[verb.group(1)] + cl[verb.end():]
                if sep.strip() in ("who", "which", "that", "and", "but") and \
                        not re.match(r"(is|was|are|were) ", new):
                    new = "is " + new
                out.append((sep, new))
                changed.append("softened %s (%s)" % (cl.strip(" ."), "/".join(bad)))
            else:
                changed.append("dropped %s (%s)" % (cl.strip(" ."), "/".join(bad)))
                # "goose who killed X and attacks" -> "goose who attacks"
                if sep.strip() in ("who", "which", "that") and idx + 1 < len(pieces) \
                        and pieces[idx + 1][0].strip() in ("and", "but"):
                    pieces[idx + 1] = (sep, pieces[idx + 1][1])
        if not changed:
            return desc
        self.stats["first descriptions changed"] += 1
        end = desc.rstrip()[-1:] if desc.rstrip()[-1:] in ".!?" else ""
        if not out:
            new = ""
        else:
            new = out[0][1] + "".join(s + c for s, c in out[1:])
            new = new.rstrip(" ,;.!?") + end
            new = new[:1].upper() + new[1:]
        self.log.append("first description of %s: %s\n    before: %s\n    after:  %s"
                        % (name, "; ".join(changed), desc, new))
        return new

    def verify(self, k, u, text, ptext, seg):
        """Empty when the change is backed by its quote, else why not."""
        q = str(u.get("quote") or "").strip()
        sq = squash(q)
        if not sq:
            return "no quote"
        if sq not in ptext and not quote_ok(q, text):
            return "quote not in text"
        mine = self.forms(k) + sorted(self.epithets[k]) + \
            (["i", "me", "my"] if self.known[k]["narrator"] else [])

        def hit(fs, s):
            return any(re.search(r"\b%s\b" % re.escape(f), s) for f in fs)
        at = ptext.find(sq[:40])
        before = ptext[max(0, at - 300):at] if at >= 0 else ""
        said = FIRSTP.search(sq) and any(
            sq[:40] in squash(t) and hit(self.forms(k) + sorted(self.epithets[k]), squash(t))
            for _n, t in seg)
        if not (hit(mine, sq) or hit(self.forms(k) + sorted(self.epithets[k]), before) or said):
            return "quote does not name them"
        other = str(u.get("other") or "").strip()
        if other and squash(other) not in ("none", "n a", "nobody", "no one", ""):
            o = self.find(other)
            theirs = (self.forms(o) + (["i", "me", "my"] if self.known[o]["narrator"] else [])) \
                if o else [t for t in squash(other).split() if len(t) >= 3 and t not in STOPW]
            if theirs and not (hit(theirs, sq) or hit(theirs, before)):
                self.log.append("%s: quote does not name %s, change kept without them"
                                % (k, other))
                u["other"] = ""
        claim = "%s %s" % (u.get("now") or "", u.get("event") or "")
        for e in self.known:
            for x in sorted(self.names(e), key=len, reverse=True):
                claim = re.sub(r"\b%s\b" % re.escape(x), " ", claim)
        big = [m.group(0) for m in BIG.finditer(claim)]
        if big and all(REVEAL.fullmatch(b) for b in big) and IDENT.search(sq):
            return ""
        if BIG.search(claim) and not BIGQ.search(q):
            return "big claim (%s) the quote does not make" % BIG.search(claim).group(0)
        return ""

    # -- the whole book ---------------------------------------------------

    def go(self):
        ctx = self.ctx
        self.log.append("main character: %s" % (", ".join(sorted(self.hero)) or "none found"))
        total = len(self.parts)
        for i, (order, seg) in enumerate(self.parts):
            ctx.report("who's who: part %d/%d" % (i + 1, total))
            self.one_part(i, order, seg)
        return self.finish()

    def one_part(self, i, order, seg):
        text = "\n".join(t for _n, t in seg)
        ptext = squash(text)
        self.seen += " " + ptext
        self.learn_epithets(text)
        for h, hint in self.hero.items():
            if hint and self.find(h):
                self.known[self.find(h)]["narrator"] = True
        talk = {m.group(2) or m.group(3) for m in SPEECH.finditer(text)} - NOT_NAMES
        speaks = {self.find(n) for n in talk} - {None}
        counts = {k: self.count(k, ptext) for k in self.known}
        check = sorted((k for k in self.known
                        if counts[k] >= 2 or k in speaks or self.known[k]["narrator"]),
                       key=lambda k: (not self.known[k]["narrator"], -counts[k], k))[:CHECK_MAX]
        unl = [(h, hint) for h, hint in sorted(self.hero.items())
               if not self.find(h) and in_text(h, ptext)] + \
              [(n, "") for n in self.sweep(text, talk) if n not in self.hero]
        unl = unl[:UNLISTED_MAX]
        manifest = "\n".join("- " + self.entry(n)[:DESC + len(n)]
                             for n in sorted(self.known)) or "(none yet)"
        ctext = ("\nCHECK (say for each whether they CHANGED or stayed the SAME in this text):\n"
                 + "\n".join("- " + k for k in check) + "\n") if check else "\nCHECK: (none)\n"
        utext = ("\nUNLISTED names in this part: " + "; ".join(n + hint for n, hint in unl) +
                 " -- for each, is it a person, and if so who, with a quote? Put each in \"new\" "
                 "with its real type (a name that is not a person gets its own type: place, "
                 "item, group, title...).\n") if unl else ""
        self.calls["step"] += 1
        try:
            rtext = self.ask(STEP.format(known=manifest, text=text, check=ctext, unlisted=utext,
                                         and_unlisted=", including each UNLISTED name" if unl
                                         else ""), SYSTEM, _usable_step)
        except Exception as exc:                             # noqa: BLE001
            self.log.append("part %d: no answer (%s)" % (i + 1, exc))
            return
        got = parse(rtext)
        for p in got.get("new") or []:
            self.add(p, order, seg, text, ptext)
        for u in got.get("updates") or []:
            if not isinstance(u, dict):
                continue
            k = self.find(str(u.get("name") or ""))
            if not k:
                continue
            if str(u.get("status") or "").strip().upper() != "CHANGED":
                self.stats["same"] += 1
                continue
            why = self.verify(k, u, text, ptext, seg)
            now = str(u.get("now") or "").strip()
            if not now:
                why = why or "no 'now'"
            if why:
                self.stats["changes turned down"] += 1
                self.log.append("change turned down for %s: %s | %s | %s"
                                % (k, why, now, u.get("quote")))
                continue
            self.stats["changes kept"] += 1
            sq = squash(str(u.get("quote")))
            para = next((n for n, t in seg if sq[:40] in squash(t)), seg[0][0])
            self.known[k]["change"] = sentence(now, CHANGE_WORDS)
            self.rows.append((order, para, k, self.who(k)))
        for n, _h in unl:
            if not self.find(n) and n not in self.notpeople:
                self.asked[n] += 1
        here = [k for k in sorted(self.known) if self.count(k, ptext) > 0]
        done = 0
        for a, b, why in self.pairs(text, seg, here):
            fp = frozenset((a, b))
            if done >= PAIR_MAX or a not in self.known or b not in self.known or a == b \
                    or fp in self.never or fp in self.asked_pairs:
                continue
            self.asked_pairs.add(fp)
            done += 1
            self.log.append("pair %s | %s: %s" % (a, b, why))
            if self.guard(a, b, self.who(b)):
                self._join(a, b)
            else:
                self.never.add(fp)

    def finish(self):
        known = self.known

        def cur(n):
            while n in self.moved:
                n = self.moved[n]
            return n
        owners = collections.Counter(e for v in self.epithets.values() for e in v)
        for v in self.epithets.values():
            v -= {e for e in v if owners[e] > 1}
        # leftovers code can join: a short name only one longer name fits
        allnames = {n: {bare(x) for x in self.names(n)} for n in known}
        common = common_words([b for v in allnames.values() for b in v])
        rename = {}
        sh = self.shared()
        for n in known:
            for s in allnames[n]:
                if " " in s or len(s) < 3 or s in common or s in sh:
                    continue
                fits = [m for m in known if m != n and frozenset((m, n)) not in self.never
                        and not (titled(n) and titled(m))
                        and not (honor(n) and honor(n) != honor(m))
                        and not surname_only(n) and not surname_only(m)
                        and not self.family(self.names(n), self.who(n), self.names(m), self.who(m))
                        and any(b == s or (" " in b and same(s, b, common)) for b in allnames[m])]
                if len(fits) == 1 and len(fits[0]) > len(n):
                    rename[n] = fits[0]
                    break
        for a, b in list(rename.items()):
            while b in rename:
                b = rename[b]
            rename[a] = b
        if rename:
            self.log.append("joined at the end: %s" % ", ".join(
                "%s -> %s" % ab for ab in sorted(rename.items())))
        group = collections.defaultdict(set)
        for n in known:
            group[rename.get(n, n)] |= set(self.names(n))
        sq_seen = squash(self.seen)

        def used(x):
            return mentions(x, sq_seen)
        fam = collections.defaultdict(set)
        for t, al in group.items():
            for x in al:
                w = low(x).split()
                fam[w[-1] if w else ""].add(t)

        def ok(x):
            return proper(x) and not self.common_noun(x) and \
                not (len(x.split()) == 1 and len(fam[low(x)]) > 1) and not surname_only(x)

        def pick(al, t):
            return [x for x in al if ok(x) and not titled(x)] or [x for x in al if ok(x)] \
                or [x for x in al if proper(x) and not titled(x)] or [x for x in al if proper(x)] \
                or [t]

        def best_of(cands):
            best = max(cands, key=lambda x: (used(x), len(x.split()), x))
            longer = [x for x in cands if x != best and x.split()[0] == best.split()[0]
                      and len(x.split()) > len(best.split())]
            return max(longer, key=lambda x: (used(x), len(x.split()), x)) if longer else best

        firsts: dict = {}

        def first(x):
            if x not in firsts:
                q = squash(x)
                firsts[x] = next(((o, n) for o, seg in self.parts for n, t in seg
                                  if q and re.search(r"\b%s\b" % re.escape(q), squash(t))),
                                 (10 ** 9, 0))
            return firsts[x]

        grp = {n: rename.get(n, n) for n in known}
        people: dict = {}
        last: dict = {}
        done: set = set()
        for o, pn, w, text in sorted(self.rows, key=lambda r: (r[0], r[1])):
            g = grp.get(cur(w), cur(w))
            if g not in group:
                continue
            # a row shows only names the book has used by then
            al = {x for x in group[g] if first(x) <= (o, pn)} | {w}
            shown = best_of(pick(al, w))
            if g in done:
                text = re.sub(r"\s+([.,;])", r"\1", NARR_I.sub("", text))
            done.add(g)
            if last.get(g) == text:
                continue
            last[g] = text
            p = people.get((g, shown))
            if p is None:
                forms = {shown} | {x for x in group[g] if proper(x) and not surname_only(x)
                                   and not (len(x.split()) == 1 and len(fam[low(x)]) > 1)}
                p = C.Person(shown, forms, True)
                people[(g, shown)] = p
            status = "met" if self.lead and (shown == self.lead or self.lead in group[g]) \
                else "heard"
            p.rows.append((o, self.path_of.get(o, ""), pn, status, text.strip()))
        # one name per person per row set: later names of the same person
        # keep only the forms no earlier name of theirs uses
        by_group = collections.defaultdict(list)
        for (g, _s), p in people.items():
            by_group[g].append(p)
        for ps in by_group.values():
            if len(ps) > 1:
                for p in ps:
                    others = {q.name for q in ps if q is not p}
                    p.forms = sorted({f for f in p.forms if f not in others} | {p.name},
                                     key=len, reverse=True)
        shown_people = list(people.values())
        for p in shown_people:
            p.mentions = C._mentions(self.docs, p.forms)
            p.spoke = C._first_spoken(self.docs, p.forms)
        rows = C._rows(shown_people, self.lead)
        report = ["%d people written; %d questions (%d parts, %d same-person checks); "
                  "%d changes kept, %d turned down; %d first descriptions changed"
                  % (len(shown_people), sum(self.calls.values()), self.calls["step"],
                     self.calls["guard"], self.stats["changes kept"],
                     self.stats["changes turned down"], self.stats["first descriptions changed"])]
        if self.notpeople:
            report.append("not people: " + ", ".join(sorted(self.notpeople)[:60]))
        if os.environ.get("CAST_HISTORY"):
            report.extend(self.log)
        return rows, report, C.seen_rows(shown_people, self.lead)
