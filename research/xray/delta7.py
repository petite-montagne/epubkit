"""Step 2h (delta7): delta6c, run live ("live" as the third argument) or replayed.

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

delta6b: a first description gets the B check that changes get. It is split
into clauses; a clause with a big claim (crime, death, reveal, romance,
betrayal), names stripped, must be backed by a word of the same kind in its
quote or the lines around it. If not, it is softened to the text's own hedge
("suspected of stealing") or dropped. Each change is logged as INTRODROP.

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

delta5 notes follow.

The model used to decide who it talked about and wrote free text; code only
checked that a quote existed. Now:

A. Coverage is decided by code. An entity table holds every person and their
   aliases. Per part, code finds the known people the text mentions (any
   alias 2+ times, or a speaking line) and asks one narrow question for each,
   batched into the part's one call: CHANGED or SAME, with a quote. Names
   that speak but are not listed yet (and the narrator of a first-person book)
   are put to the model as UNLISTED, so the hero is covered by the same rule.
   No timer, no special hero ask.
B. Claims are structured and checked. A change is {name, status, now, event,
   other, quote}. Code checks the quote is in the part, names the person (or
   opens with a pronoun right after their name), and names the other person
   when there is one. Big claims (death, killing, betrayal, pregnancy, "is
   revealed to be") also need a matching word in the quote. Entries are
   written only from checked facts; failures are logged as BLOCK.
C. Identity is an entity with aliases. Every new name is normalised (titles,
   " 2" crawler suffixes, short forms) and resolved against all aliases, plus
   "X, also called Y" / "Y (X)" in its quote; then the DIFFERENT ENTITIES
   guard decides and a merge adds the alias. A new entity needs a type: only
   person, creature, animal, AI, god or monster get entries; companies,
   places, items and groups are kept in a not-people list. The alias table is
   saved next to the report (OUT.aliases.json) for gaps.py.

usage: python3 -I delta5.py dcc4|pj6|... OUT.cast.txt   (run from ~/cast-pilot)
"""
import collections, glob, json, os, re, sys, time
from pathlib import Path

H = os.path.expanduser("~")
sys.path.insert(0, H + "/cast-pilot/xray/epubkit/src")
sys.path.insert(0, H + "/cast-pilot/xray")
from epubkit.stages.recaps import _documents, _segments  # noqa: E402
from epubkit.ai.providers import OpenAIProvider  # noqa: E402
from cards import low, same, common_words  # noqa: E402

BOOK = {"dcc5": H + "/cast-pilot/books-dcc5-r17/*.epub",
        "hp1": H + "/cast-pilot/books-hp1-r17/*.epub",
        "hp2": H + "/cast-pilot/xray/hp2/books/*.epub",
        "dcc4": H + "/cast-pilot/xray/dcc4/books/*.epub",
        "pj6": H + "/cast-pilot/xray/pj6/books/*.epub"}
PASSAGE = 16000
DESC = 90
FIRST_WORDS, CHANGE_WORDS = 24, 16
CHECK_MAX, UNLISTED_MAX, PAIR_MAX = 12, 10, 6
SEED = 7
CAP = r"[A-Z][A-Za-z'’\-]+"
TITLE_WORDS = (r"Mr|Mrs|Ms|Miss|Mister|Madam|Madame|Dr|Doctor|Professor|Uncle|Aunt|Auntie|Sir|Lady|Lord|Dame|"
               r"Captain|Coach|King|Queen|Prince|Princess")
TITLED_NAME = re.compile(r"\b(?:%s)\.?\s+%s(?:\s+%s){0,2}" % (TITLE_WORDS, CAP, CAP))
INTRO_NAME = re.compile(r"\b(?:named|called|known as|name is|name was)\s+(%s(?:\s+%s){0,2})" % (CAP, CAP))
# two to four capitalised words in mid-sentence ("the Mad Dune Mage")
MULTI_NAME = re.compile(r"(?<=[a-z,;] )(%s(?:\s+%s){1,3})" % (CAP, CAP))
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
AKA_PAIR = re.compile(r"(%s(?:\s+%s){0,3}),?\s+(?:also known as|aka|a\.k\.a\.|better known as|otherwise known as|"
                      r"who goes by|whose real name (?:is|was))\s+(?:the\s+)?(%s(?:\s+%s){0,3})" % (CAP, CAP, CAP, CAP))
RANKS = r"^(king|queen|prince|princess|emperor|empress|duke|duchess|count|countess|baron|lady|lord|master|mistress|captain|general|chief|saint|st|father|mother|brother|sister|big|little|old|young)\s+"
PERSONLIKE = {"person", "creature", "animal", "ai", "god", "deity", "monster", "character", "pet", "spirit", "ghost"}
# a claim this big needs a quote that says so
BIG = re.compile(r"\b(die[ds]?|dying|dead|death|kill\w*|slain|slay\w*|murder\w*|betray\w*|pregnan\w*|"
                 r"reveal\w*|is actually|is really|secretly|true identity|real name)\b", re.I)
BIGQ = re.compile(r"\b(die[ds]?|dying|dead|death|kill\w*|slain|slay\w*|murder\w*|corpse|body|betray\w*|"
                  r"pregnan\w*|baby|reveal\w*|actually|really|true|real name|identity|who (he|she) (is|was))\b", re.I)
KIN = {"mom", "mommy", "mum", "mother", "ma", "dad", "daddy", "father", "pa", "papa", "grandma", "grandpa", "granny",
       "grandmother", "grandfather", "nana", "auntie", "aunt", "uncle", "sis", "bro", "honey", "baby"}
# "Goddess of youth and former cupbearer" -> "goddess of youth"
ROLE = re.compile(r"^(?:the |a |an )?((?:god|goddess|titan|titaness|spirit|nymph|lord|lady|king|queen|prince|princess)"
                  r" of (?:the )?[a-z]+(?: (?!and\b|or\b|who\b|with\b|in\b|at\b|from\b)[a-z]+)?)\b", re.I)
# a phrase with a verb in it is a sentence, not an epithet ("Carl, the game is cheating")
VERBISH = {"is", "are", "was", "were", "has", "had", "have", "came", "come", "went", "gone", "did", "does", "do",
           "can", "will", "would", "could", "should", "said", "says", "cost", "be", "been"}
# claim kind -> (words that make the claim, words that back it)
CLAIMS = {
    "death": (r"die[ds]?|dying|dead|death|kill\w*|slain|slay\w*|murder\w*",
              r"die[ds]?|dying|dead|death|kill\w*|slain|slay\w*|murder\w*|corpse|body|grave"),
    "crime": (r"stole|steal\w*|stolen|theft|thie[fv]\w*|rob(s|bed|bing|ber\w*)?|crimes?|criminal|guilty|culprit|framed",
              r"stole|steal\w*|stolen|theft|thie[fv]\w*|rob(s|bed|bing|ber\w*)?|crimes?|criminal|guilty|culprit|framed"),
    "betrayal": (r"betray\w*|traitor\w*|double agent|spy|spies|spying",
                 r"betray\w*|traitor\w*|double agent|spy|spies|spying"),
    "pregnancy": (r"pregnan\w*", r"pregnan\w*|baby|expecting"),
    "reveal": (r"reveal\w*|is actually|is really|secretly|true identity|real name|in disguise",
               r"reveal\w*|actually|really|true|real name|identity|disguise\w*|secret\w*"),
    "romance": (r"lover|girlfriend|boyfriend|fianc\w*|engaged|affair|married|wife|husband|crush|romantic\w*|dating",
                r"lover|girlfriend|boyfriend|fianc\w*|engaged|affair|married|wife|husband|crush|kiss\w*|love[ds]?|dating|date"),
}
HEDGE = re.compile(r"\b(suspect\w*|accus\w*|allege\w*|blame[ds]?|rumou?r\w*|framed)\b")
# "allegedly stole" -> "suspected of stealing"
GERUND = {"stole": "stealing", "steals": "stealing", "stolen": "stealing", "robbed": "robbing", "killed": "killing",
          "murdered": "murdering", "betrayed": "betraying", "kills": "killing", "betrays": "betraying"}
CLAUSE = re.compile(r"(,\s+|;\s+|\s+(?:and|but|who|which|whose)\s+|\s+that\s+(?=(?:was|were|is|are|has|had)\b))")
# not a claim about the person: someone else's stolen thing, dead leaves,
# a threat or an attempt, a death they only saw
NONCLAIM = re.compile(r"\b(?:(?:his|her|their|its|my|your|[a-z]+ s) (?:stolen|missing)"
                      r"|dead (?:nature|leaves|plants?|flowers?|trees?|wood|skin|end|zone|silence|weight|air|things|"
                      r"animals?|birds?|fish|insects?)"
                      r"|(?:will|would|could|might|may|wants? to|wanted to|tr(?:y|ies|ying|ied) to|attempts? to|"
                      r"attempted to|plans? to|threatens? to|going to|intends? to) (?:\w+ )?(?:kill|murder|steal|rob|slay)\w*"
                      r"|witness\w* (?:\w+ ){0,4}?(?:death|murder|killing|dying))\b")
# an identity statement backs a reveal: "I am Lord Voldemort", "it's a basilisk"
IDENT = re.compile(r"\bi am\b|\bi m\b|\b[a-z]+ is (?:a|an|the)\b|\b[a-z]+ s (?:a|an)\b|\bnamed\b")
REVEAL = re.compile(r"reveal\w*|is actually|is really|secretly|true identity|real name", re.I)
FIRSTP = re.compile(r"\b(?:i|me|my|i m|we)\b")
SPECIES = {"ai", "dromedarian", "dromedarians", "bactrian", "bactrians", "changeling", "changelings", "anser", "ansers",
           "grull", "grulls", "npc", "npcs"}
PRON = re.compile(r"^\W*(he|she|they|him|her|his|hers|their|them)\b", re.I)
SUFFIX = re.compile(r"\s+\d+$")
# "narrator ..., referred to as 'I'": said once, on the first row only
NARR_I = re.compile(r",?\s*(who is |and is )?(referred to|known|called|identified) as [“\"'‘]?I[”\"'’]?(\s+throughout[^.,;]*)?", re.I)

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

Are A and B the same individual? If they are different people, the first line of your answer must be exactly DIFFERENT ENTITIES. If they are the same person, the first line must be exactly SAME."""

# back matter and other books' samples, matched on the TOC title or the opening line
BACK = re.compile(r"^\W*(also by|other (books|titles) by|books (by|from)|more (books|from)|about the authors?|acknowledg|"
                  r"copyright|newsletter|praise for|reading group|discussion (questions|guide)|"
                  r"(an )?excerpt|preview|sneak peek|read on\b|coming soon|a sample|bonus (chapter|content)|"
                  r"titles available|keep reading|turn the page|don.t miss)", re.I)
NUM = {w: i + 1 for i, w in enumerate("one two three four five six seven eight nine ten".split())}
SPEECH = re.compile(r"\b(said|asked|says|asks|replied|whispered|shouted|yelled|muttered|called|snapped|cried)\s+([A-Z][a-z'’]+)"
                    r"|\b([A-Z][a-z'’]+)\s+(said|asked|says|asks|replied|whispered|shouted|yelled|muttered|called|snapped|cried)\b")
NOT_NAMES = {"He", "She", "They", "It", "I", "We", "You", "Then", "And", "But", "The", "Someone", "Everyone", "Nobody",
             "Somebody", "Mom", "Dad", "Mum", "Mother", "Father", "Sir", "Madam"}


def chapter_no(label, head):
    """The chapter number a part opens with, from its TOC title or first words."""
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


def story_parts(docs, log):
    """The real book's documents: stop at back matter, a sample or the next
    book's chapter 1. Cut parts are logged."""
    keep, top, cut = [], 0, None
    for i, (o, p, label, ps) in enumerate(docs):
        head = " ".join(t for _n, t in ps[:2])[:200]
        n = chapter_no(label, head)
        late = i >= len(docs) // 2
        if late and (BACK.match(label) or BACK.match(head)):
            cut = (i, "back matter or sample: %r" % (label or head[:40]))
        elif late and n is not None and n <= 1 and top >= 3:
            cut = (i, "chapter count restarts (%r after chapter %d)" % (label or head[:40], top))
        if cut:
            break
        if n:
            top = max(top, n)
        keep.append(docs[i])
    if cut:
        for o, p, label, ps in docs[cut[0]:]:
            log.write("CUT order %d %r (%d chars): %s\n" % (o, label, sum(len(t) for _n, t in ps), cut[1]))
    return keep


def heroes(docs):
    """The most-mentioned speaking name, and the narrator of a first-person book."""
    text = "\n".join(t for _o, _p, _l, ps in docs for _n, t in ps)
    talk = collections.Counter(m.group(2) or m.group(3) for m in SPEECH.finditer(text))
    names = [n for n, c in talk.most_common() if n not in NOT_NAMES and c >= 5]
    out = {}
    if names:
        top = max(names[:10], key=lambda n: len(re.findall(r"\b%s\b" % re.escape(n), text)))
        out[top] = ""
    # first person: "I" outside dialogue, then the name others call the narrator by
    narr = re.sub(r"[“\"][^”\"]*[”\"]", " ", text)
    if len(re.findall(r"\bI\b", narr)) > len(re.findall(r"\b(he|she)\b", narr, re.I)) // 3:
        voc = collections.Counter()
        for q in re.findall(r"[“\"]([^”\"]{0,300})[”\"]", text):
            for m in re.finditer(r"(?:^|[,!?.]\s)([A-Z][a-z'’]+)[,!?.]|,\s([A-Z][a-z'’]+)[.!?,]?$", q):
                n = m.group(1) or m.group(2)
                if n not in NOT_NAMES:
                    voc[n] += 1
        # the narrator speaks as "I said", so they need not be among the tagged speakers
        # a name also turns up capitalised mid-sentence ("asked Percy", "to Carl");
        # "Oh", "Yes", "Look" open sentences and nearly never do
        cands = [n for n, c in voc.most_common(12) if c >= 5
                 and len(re.findall(r"[a-z,;]\s+%s\b" % re.escape(n), text)) >= c // 2]
        if cands:
            out[cands[0]] = " They are the narrator, the \"I\" of the story."
    return out


def flat(s):
    """Letters and digits only: quotes, dashes, spacing and case flattened."""
    return re.sub(r"[\W_]+", "", s.lower())


def quote_ok(ev, text):
    f = flat(text)
    bits = [flat(b) for b in re.split(r"\.\s*\.\s*\.|…", ev)]
    bits = [b for b in bits if len(b) >= 8]
    return bool(bits) and all(b in f for b in bits)


def mentions(name, ptext):
    q = squash(name)
    return len(re.findall(r"\b%s\b" % re.escape(q), ptext)) if q else 0


def code_quote(name, seg):
    """A short quote around the first place the text names this person."""
    q = squash(name).split()
    for _n, t in seg:
        if in_text(name, squash(t)):
            w = t.split()
            at = next((i for i, x in enumerate(w) if squash(x) == q[0]), 0)
            return " ".join(w[max(0, at - 6):at + 12])
    return ""


def key():
    """The llama-server key, from the environment only (OPENAI_API_KEY or LLAMA_KEY)."""
    return os.environ.get("OPENAI_API_KEY") or os.environ.get("LLAMA_KEY")


def parse(text):
    m = re.search(r"\{.*\}", text, re.S)
    try:
        return json.loads(m.group(0)) if m else {}
    except ValueError:
        pass
    # a log line cut short: keep every complete entry
    got, cut = {"new": [], "changed": []}, text.find('"changed"')
    for o in re.finditer(r"\{[^{}]*\}", text):
        try:
            got["changed" if 0 <= cut < o.start() else "new"].append(json.loads(o.group(0)))
        except ValueError:
            pass
    return got


def squash(s):
    return re.sub(r"\W+", " ", s.lower().replace("’", "'")).strip()


HONOR = r"^(mr|mrs|ms|miss|madam|madame|sir|dame)\b"


def sentence(s, words):
    """The first sentence, cut to a word budget. A full stop after a short
    capitalised word (Mr., Mrs., Dr., St., initials) does not end a sentence."""
    w, out = s.split(), []
    for t in w:
        out.append(t)
        if re.search(r"[.!?]$", t) and not re.fullmatch(r"[A-Z][a-z]{0,2}\.", t):
            break
    w = out
    return " ".join(w[:words]).rstrip(",;:") + ("…" if len(w) > words else "")


def plain(n):
    """Lower case, punctuation squashed, titles kept (Mr. and Mrs. differ)."""
    return re.sub(r"\s+", " ", re.sub(r"[^\w']+", " ", n.lower().replace("’", "'"))).strip()


def in_text(name, plain_text):
    """The name is in the text, as written or as "Last, First"."""
    q = squash(name).split()
    return bool(q) and (" ".join(q) in plain_text or
                        (len(q) > 1 and " ".join(q[-1:] + q[:-1]) in plain_text))


def honor(n):
    m = re.match(HONOR, plain(n))
    return m.group(1) if m else ""


def replay(log):
    """The saved step answers (in order) and guard answers from a delta2 log."""
    steps, guards = [], {}
    for line in open(log, encoding="utf-8"):
        if line.startswith("PART "):
            steps.append(line.split(": ", 1)[1])
        elif line.startswith("GUARD "):
            pair, ans = line[6:].rsplit(" -> ", 1)
            a, b = pair.split(" | ", 1)
            guards[(a, b)] = ans.strip().upper().startswith("SAME")
    return steps, guards


def bare(n):
    """low() plus generic ranks, for the code-side merge only."""
    n = low(n)
    while True:
        t = re.sub(RANKS, "", n)
        if t == n or not t:
            return n
        n = t


def titled(n):
    """True when the name carries a title or rank (Mr., Queen, Big...)."""
    plain = re.sub(r"\s+", " ", re.sub(r"[_\-·]", " ", n.lower().replace("’", "'").replace(".", ""))).strip()
    return bare(n) != plain


STOPW = {"the", "of", "and", "a", "an", "in", "on", "at", "to", "god", "goddess", "king", "queen", "prince", "princess",
         "lord", "lady", "sir", "miss", "mr", "mrs", "ms", "captain", "general", "big", "little", "old", "young", "none"}


def parse5(text):
    m = re.search(r"\{.*\}", text, re.S)
    try:
        got = json.loads(m.group(0)) if m else {}
        return got if isinstance(got, dict) else {}
    except ValueError:
        pass
    # an answer cut short: keep every complete entry
    got, cut = {"new": [], "updates": []}, text.find('"updates"')
    for o in re.finditer(r"\{[^{}]*\}", text):
        try:
            got["updates" if 0 <= cut < o.start() else "new"].append(json.loads(o.group(0)))
        except ValueError:
            pass
    return got


EPITHET = re.compile(r"^(.+?),?\s+the\s+(.*)$")
PARTICLES = {"de", "da", "del", "der", "di", "du", "la", "le", "van", "von", "of", "the", "and", "al", "bin", "ibn"}


def norm(n):
    """A name as the table keeps it: spacing tidied, crawler " 2" suffix dropped,
    and a descriptive tail cut ("Gary the diapered god" -> "Gary"; "Jack the
    Ripper" keeps its capitalised title)."""
    n = SUFFIX.sub("", re.sub(r"\s+", " ", str(n or "")).strip()).strip()
    m = EPITHET.match(n)
    if m and any(w[:1].islower() and w.lower() not in PARTICLES for w in m.group(2).split()):
        n = m.group(1).strip()
    return n


def proper(n):
    """A real name, not a description: every word capitalised (particles aside)."""
    ws = n.split()
    if ws and all(w.lower().strip(".,'") in KIN for w in ws):
        return False
    return bool(ws) and all(w[:1].isupper() or w[:1].isdigit() or w.lower() in PARTICLES for w in ws) \
        and ws[0].lower() not in PARTICLES


class Fixed(OpenAIProvider):
    """Same answer for the same prompt: no reused prompt cache, one seed, greedy."""
    def _post(self, url, payload, headers):
        if url.endswith("/chat/completions"):
            payload = dict(payload, cache_prompt=False, seed=SEED, top_k=1)
        return super()._post(url, payload, headers)


class Saved:
    """Hands back delta5's saved step answers in order; never calls a model."""
    def __init__(self, steps):
        self.steps = list(steps)

    def complete(self, prompt, system=None):
        return type("R", (), {"text": self.steps.pop(0) if self.steps else "{}"})()


def main(which, out, saved):
    book = Path(glob.glob(BOOK[which])[0])
    live = saved == "live"
    if live:
        steps, verdicts = [], {}
        ai = Fixed("qwen3.6-35b-a3b", "http://localhost:8081", key(), timeout=600, max_tokens=2000, temperature=0)
    else:
        steps, verdicts = replay(saved)
        ai = Saved(steps)
    asked = collections.Counter()   # unlisted name -> times asked with no result
    asked_pairs = set()
    moved = {}          # old entity key -> the key it merged into
    epithets = collections.defaultdict(set)   # entity -> "goddess of youth", ...
    coderule = []       # merges decided by the code rule, not a saved verdict
    known = {}          # entity -> dict(aliases, type, first, change, narrator)
    notpeople = {}      # name -> type, for names that are not individuals
    never = set()       # frozenset pairs the guard said are different
    rows, log = [], open(out + ".log", "w", encoding="utf-8")
    docs = story_parts(_documents(book, 2000), log)
    hero = heroes(docs)
    log.write("HEROES %s\n" % sorted(hero))
    seen = ""
    book_text = "\n".join(t for _o, _p, _l, ps in docs for _n, t in ps)
    book_sq = squash(book_text)
    parts = [(o, seg) for o, _p, _l, ps in docs for seg in _segments(ps, PASSAGE)]
    t0, calls, stats = time.time(), collections.Counter(), collections.Counter()

    def who(n):
        k = known[n]
        return (k["first"] + (" " + k["change"] if k["change"] else "")).strip()

    def entry(n):
        k = known[n]
        return n + (" (also " + ", ".join(k["aliases"]) + ")" if k["aliases"] else "") + ": " + who(n)

    def names(k):
        return [k] + known[k]["aliases"]

    def shared():
        """Words that end the multi-word names of two or more entities."""
        own = collections.defaultdict(set)
        for e in known:
            for x in names(e):
                w = low(x).split()
                if len(w) > 1:
                    own[w[-1]].add(e)
        return {w for w, es in own.items() if len(es) > 1}

    def find(name):
        """The entity this name is: an exact name or alias; then the same name
        once titles and ranks are stripped; then start/end words (common words
        never count). Only when exactly one entity fits."""
        p = plain(norm(name))
        for k in known:
            if p in {plain(x) for x in names(k)}:
                return k
        if len(norm(name).split()) == 1 and low(norm(name)) in shared():   # "Mrs. Weasley" is not bare
            return None
        b = bare(norm(name))
        fits = [k for k in known if b and b in {bare(x) for x in names(k)}]
        if len(fits) == 1:
            return fits[0]
        n = low(norm(name))
        common = common_words([low(x) for k in known for x in names(k)])
        fits = [k for k in known if any(same(n, low(x), common) for x in names(k))
                and not (honor(name) and any(honor(x) and honor(x) != honor(name) for x in names(k)))]
        return fits[0] if len(fits) == 1 else None

    def forms(k):
        """Squashed ways the text names an entity: every alias, plus a first or
        last word that belongs to no other entity."""
        own = {squash(x) for x in names(k) if squash(x)}
        owner = collections.defaultdict(set)
        for e in known:
            for x in names(e):
                for t in low(x).split():
                    owner[t].add(e)
        for x in names(k):
            w = low(x).split()
            for t in (w[:1] + w[-1:]) if len(w) > 1 else []:
                if len(t) >= 3 and t not in STOPW and owner[t] == {k}:
                    own.add(squash(t))
        return sorted(own, key=len, reverse=True)

    def count(k, ptext):
        f = forms(k)
        return len(re.findall(r"\b(?:%s)\b" % "|".join(map(re.escape, f)), ptext)) if f else 0

    def extends(k, name, ptext):
        """A bare given name that starts this one known full name, both used in
        the text so far, and no other entity starts with that word."""
        a, b = sorted((low(norm(name)), low(k)), key=lambda x: len(x.split()))
        if len(a.split()) != 1 or len(b.split()) < 2 or b.split()[0] != a or len(a) < 3 or a in STOPW:
            return False
        if any(e != k and any(low(x).split()[:1] == [a] for x in names(e)) for e in known):
            return False
        return mentions(k, seen) > 0 and mentions(name, ptext) > 0

    def guard(a, b_name, b_who):
        if live:
            calls["guard"] += 1
            r = ai.complete(GUARD.format(a=entry(a), b=b_name + ": " + b_who), system=SYSTEM).text.strip()
            log.write("GUARD %s | %s -> %s\n" % (a, b_name, r.splitlines()[0] if r else ""))
            return r.upper().startswith("SAME")
        if (a, b_name) in verdicts:
            calls["guard (saved)"] += 1
            log.write("GUARD %s | %s -> %s (saved)\n" % (a, b_name, "SAME" if verdicts[(a, b_name)] else "DIFFERENT"))
            return verdicts[(a, b_name)]
        calls["guard (no saved verdict)"] += 1
        log.write("NOVERDICT %s | %s -> DIFFERENT (would need a new guard call)\n" % (a, b_name))
        coderule.append(("no verdict, kept apart", a, b_name))
        return False

    def learn_epithets(text):
        """ "Hebe, the goddess of youth," in the text ties that epithet to Hebe."""
        for k in known:
            for x in names(k):
                for m in re.finditer(r"\b%s,\s+(the\s+[a-z][a-z ]{3,40}?)[,.;!?]" % re.escape(x), text):
                    e = squash(m.group(1))
                    if not VERBISH & set(e.split()) and len(e.split()) <= 5 and book_sq.count(e) >= 2:
                        epithets[k].add(e)

    def aka(ev, name):
        """An entity the quote itself says this name belongs to:
        "X, also called Y", "Y (X)", "X (Y)"."""
        e = squash(ev)
        n = squash(name)
        for k in known:
            for x in names(k):
                x = squash(x)
                if not x or x == n:
                    continue
                if re.search(r"\b%s\b (also )?(called|known as|named|nicknamed|aka|or) %s\b" % (re.escape(x), re.escape(n)), e) \
                        or re.search(r"\b%s\b (also )?(called|known as|named|nicknamed|aka|or) %s\b" % (re.escape(n), re.escape(x)), e) \
                        or re.search(r"\b%s\s*\(\s*%s\s*\)" % (re.escape(x), re.escape(name.lower())), ev.lower()) \
                        or re.search(r"\b%s\s*\(\s*%s\s*\)" % (re.escape(name.lower()), re.escape(x)), ev.lower()):
                    return k
        return None

    def sweep(text, talk):
        """Person-like names in this part that are not in the table: speakers,
        titled names, names introduced as names, mid-sentence capitalised names."""
        def fresh(n):
            return n and n not in NOT_NAMES and low(n) not in KIN and n not in notpeople and asked[n] < 2 \
                and plain(n) not in {plain(x) for x in notpeople} and not find(n) \
                and not all(w.strip(".") in STOPW | KIN for w in low(n).split()) \
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
        log.write("  PAIRMERGE %s + %s -> %s (%s)\n" % (a, b, main_name, why))

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
            if len(re.findall(r"[“\"][^”\"]+[”\"]", t)) > 2:
                continue
            who_ = sorted({find(m.group(2) or m.group(3)) for m in SPEECH.finditer(t)} - {None})
            if len(who_) == 2:
                out.append((who_[0], who_[1], "two speaker names in one paragraph"))
        return out

    def add(p, order, seg, text, ptext):
        if not isinstance(p, dict):
            return
        name, desc = norm(p.get("name")), str(p.get("who") or "").strip()
        ev, typ = str(p.get("evidence") or "").strip(), str(p.get("type") or "").strip().lower()
        aliases = [norm(a) for a in p.get("aliases") or [] if norm(a) and norm(a) != name]
        if not name or not desc:
            return
        if name in notpeople:
            return
        if not in_text(name, ptext) and not any(in_text(a, ptext) for a in aliases):
            log.write("  drop %s: name not in text\n" % name)
            return
        if not ev or squash(ev) not in ptext:
            if ev and quote_ok(ev, text):
                pass
            elif max([mentions(name, seen)] + [mentions(a, seen) for a in aliases]) >= 3:
                log.write("  keep %s: quote not in text, but named 3+ times so far; code quote: %s\n"
                          % (name, code_quote(name, seg)))
            else:
                log.write("  drop %s: evidence not in text\n" % name)
                return
        if not typ:
            log.write("  drop %s: no type\n" % name)
            return
        w0 = low(name).split()
        if low(name) in SPECIES or (w0 and w0[0] in SPECIES and not proper(name)):
            for n in [name] + aliases:
                notpeople[n] = "species"
            log.write("  NOTPERSON %s (species)\n" % name)
            return
        exact = next((k for k in known if plain(name) in {plain(x) for x in names(k)}), None)
        if not exact and len(norm(name).split()) == 1 and low(name) in shared():
            log.write("  SHAREDNAME %s: a surname of two or more people, not added\n" % name)
            return
        if typ not in PERSONLIKE and not exact:
            for n in [name] + aliases:
                notpeople[n] = typ
            log.write("  NOTPERSON %s (%s)\n" % (name, typ))
            return
        para = next((n for n, t in seg if in_text(name, squash(t))), seg[0][0])
        hit = find(name) or next((find(a) for a in aliases if find(a)), None) or aka(ev, name)
        if hit and plain(name) in {plain(x) for x in names(hit)}:
            # already listed under this name: just learn any new aliases
            known[hit]["aliases"] = sorted(set(known[hit]["aliases"]) | ({*aliases} - {hit}))
            return
        if hit and hit in notpeople:
            hit = None
        if hit and extends(hit, name, ptext):
            k = known.pop(hit)
            main_name = name if len(name.split()) > len(hit.split()) else hit
            k["aliases"] = sorted({hit, name, *aliases, *k["aliases"]} - {main_name})
            known[main_name] = k
            if main_name != hit:
                moved[hit] = main_name
                epithets[main_name] |= epithets.pop(hit, set())
            coderule.append(("surname extension, merged", hit, name))
            log.write("  CODEMERGE %s + %s -> %s (surname extension)\n" % (hit, name, main_name))
            return
        if hit and frozenset((hit, name)) not in never:
            if guard(hit, name, sentence(desc, FIRST_WORDS)):
                k = known.pop(hit)
                main_name = name if len(name.split()) > len(hit.split()) else hit
                k["aliases"] = sorted({hit, name, *aliases, *k["aliases"]} - {main_name})
                known[main_name] = k
                if main_name != hit:
                    moved[hit] = main_name
                    epithets[main_name] |= epithets.pop(hit, set())
                log.write("  MERGE %s + %s -> %s\n" % (hit, name, main_name))
                rows.append((order, para, main_name, who(main_name)))
                return
            never.add(frozenset((hit, name)))
        if name in known:
            return
        sh = shared()
        gone = [a for a in aliases if (len(norm(a).split()) == 1 and low(a) in sh) or any(plain(a) in {plain(x) for x in names(e)} for e in known)]
        if gone:
            log.write("  ALIASDROP %s: %s (another entity's name or a shared surname)\n" % (name, gone))
            aliases = [a for a in aliases if a not in gone]
        intro = check_intro(name, aliases, desc, ev, ptext, text)
        known[name] = dict(aliases=aliases, type=typ, first=sentence(intro, FIRST_WORDS), change="", narrator=False)
        m = ROLE.match(desc)
        if m and squash(m.group(1)) in book_sq:
            epithets[name].add(squash(m.group(1)))
        rows.append((order, para, name, who(name)))

    def check_intro(name, aliases, desc, ev, ptext, text):
        """The intro with each big claim its quote does not back softened or dropped."""
        gone = {name, *aliases} | {x for e in known for x in names(e)}

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
        changed = []
        pieces = [("", bits[0])] + [(bits[i], bits[i + 1]) for i in range(1, len(bits) - 1, 2)]
        out = []
        for sep, cl in pieces:
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
        log.write("  INTRODROP %s: %s\n    before: %s\n    after:  %s\n" % (name, "; ".join(changed), desc, new))
        return new

    def verify(k, u, text, ptext, seg):
        """Empty when the claimed change is backed by its quote, else why not."""
        q = str(u.get("quote") or "").strip()
        sq = squash(q)
        if not sq:
            return "no quote"
        if sq not in ptext and not quote_ok(q, text):
            return "quote not in text"
        mine = forms(k) + sorted(epithets[k]) + (["i", "me", "my"] if known[k]["narrator"] else [])
        hit = lambda fs, s: any(re.search(r"\b%s\b" % re.escape(f), s) for f in fs)
        at = ptext.find(sq[:40])
        before = ptext[max(0, at - 300):at] if at >= 0 else ""
        # the quote names them, or they are named in the lines just before it
        # (dialogue: "You must defeat me", spoken right after "Gary said")
        # "I am Lord Voldemort": first person, said by them in that paragraph
        said = FIRSTP.search(sq) and any(sq[:40] in squash(t) and hit(forms(k) + sorted(epithets[k]), squash(t))
                                         for _n, t in seg)
        if not (hit(mine, sq) or hit(forms(k) + sorted(epithets[k]), before) or said):
            return "quote does not name them"
        other = str(u.get("other") or "").strip()
        if other and squash(other) not in ("none", "n a", "nobody", "no one", ""):
            o = find(other)
            theirs = (forms(o) + (["i", "me", "my"] if known[o]["narrator"] else [])) if o else \
                [t for t in squash(other).split() if len(t) >= 3 and t not in STOPW]
            # the quote backs the change for them; an "other" it does not name
            # is the model's extra, so it is dropped rather than blocking
            if theirs and not (hit(theirs, sq) or hit(theirs, before)):
                log.write("  OTHERDROP %s: quote does not name %s, change kept\n" % (k, other))
                u["other"] = ""
        claim = "%s %s" % (u.get("now") or "", u.get("event") or "")
        # a name is not a claim: "Li'l Killer" does not say anyone was killed
        for e in known:
            for x in sorted(names(e), key=len, reverse=True):
                claim = re.sub(r"\b%s\b" % re.escape(x), " ", claim)
        big = [m.group(0) for m in BIG.finditer(claim)]
        if big and all(REVEAL.fullmatch(b) for b in big) and IDENT.search(sq):
            return ""
        if BIG.search(claim) and not BIGQ.search(q):
            return "big claim (%s) the quote does not make" % BIG.search(claim).group(0)
        return ""

    for i, (order, seg) in enumerate(parts):
        text = "\n".join(t for _n, t in seg)
        ptext = squash(text)
        seen += " " + ptext
        learn_epithets(text)
        for h, hint in hero.items():
            if hint and find(h):
                known[find(h)]["narrator"] = True
        # A: code picks who this part must answer for
        talk = {m.group(2) or m.group(3) for m in SPEECH.finditer(text)} - NOT_NAMES
        speaks = {find(n) for n in talk} - {None}
        counts = {k: count(k, ptext) for k in known}
        check = sorted((k for k in known if counts[k] >= 2 or k in speaks or known[k]["narrator"]),
                       key=lambda k: (not known[k]["narrator"], -counts[k], k))[:CHECK_MAX]
        unl = [(h, hint) for h, hint in sorted(hero.items()) if not find(h) and in_text(h, ptext)] + \
              [(n, "") for n in sweep(text, talk) if n not in hero]
        unl = unl[:UNLISTED_MAX]
        manifest = "\n".join("- " + entry(n)[:DESC + len(n)] for n in sorted(known)) or "(none yet)"
        ctext = ("\nCHECK (say for each whether they CHANGED or stayed the SAME in this text):\n" +
                 "\n".join("- " + k for k in check) + "\n") if check else "\nCHECK: (none)\n"
        utext = ("\nUNLISTED names in this part: " + "; ".join(n + hint for n, hint in unl) +
                 " -- for each, is it a person, and if so who, with a quote? Put each in \"new\" with its real "
                 "type (a name that is not a person gets its own type: place, item, group, title...).\n") if unl else ""
        calls["step"] += 1
        rtext = ai.complete(STEP.format(known=manifest, text=text, check=ctext, unlisted=utext,
                                        and_unlisted=", including each UNLISTED name" if unl else ""),
                            system=SYSTEM).text
        got = parse5(rtext)
        log.write("PART %d/%d order %d CHECK %s UNLISTED %s: %s\n" % (i + 1, len(parts), order, check,
                                                                    [n for n, _h in unl], rtext.replace("\n", " ")))
        for p in got.get("new") or []:
            add(p, order, seg, text, ptext)
        # B: a change is written only from a checked fact
        for u in got.get("updates") or []:
            if not isinstance(u, dict):
                continue
            k = find(str(u.get("name") or ""))
            if not k:
                continue
            if str(u.get("status") or "").strip().upper() != "CHANGED":
                stats["same"] += 1
                continue
            why = verify(k, u, text, ptext, seg)
            now = str(u.get("now") or "").strip()
            if not now:
                why = why or "no 'now'"
            if why:
                stats["blocked"] += 1
                log.write("  BLOCK %s: %s | %s | %s\n" % (k, why, now, u.get("quote")))
                continue
            stats["changed"] += 1
            if k not in check:
                log.write("  OFFLIST %s (kept, quote checks out)\n" % k)
            sq = squash(str(u.get("quote")))
            para = next((n for n, t in seg if sq[:40] in squash(t)), seg[0][0])
            known[k]["change"] = sentence(now, CHANGE_WORDS)
            rows.append((order, para, k, who(k)))
        missed = [k for k in check if not any(isinstance(u, dict) and find(str(u.get("name") or "")) == k
                                              for u in got.get("updates") or [])]
        if missed:
            stats["unanswered"] += len(missed)
            log.write("  UNANSWERED %s\n" % missed)
        for n, _h in unl:
            if not find(n) and n not in notpeople:
                asked[n] += 1
                log.write("  NOANSWER %s (asked %d)\n" % (n, asked[n]))
        here = [k for k in sorted(known) if count(k, ptext) > 0]
        done = 0
        for a, b, why in pairs(text, seg, here):
            fp = frozenset((a, b))
            if done >= PAIR_MAX or a not in known or b not in known or a == b or fp in never or fp in asked_pairs:
                continue
            asked_pairs.add(fp)
            done += 1
            calls["pair"] += 1
            log.write("PAIR %s | %s: %s\n" % (a, b, why))
            if guard(a, b, who(b)):
                merge(a, b, why)
            else:
                never.add(fp)
        log.flush()
        print("%s part %d/%d, %d people, %.0f min" % (time.strftime("%H:%M"), i + 1, len(parts),
                                                      len(known), (time.time() - t0) / 60), flush=True)

    if getattr(ai, "steps", None):
        log.write("WARNING %d saved answers left over\n" % len(ai.steps))
    cur = lambda n: cur(moved[n]) if n in moved else n
    log.write("MOVED %s\n" % sorted(moved.items()))
    log.write("CODERULE %s\n" % coderule)
    owners = collections.Counter(e for v in epithets.values() for e in v)
    for v in epithets.values():
        v -= {e for e in v if owners[e] > 1}
    log.write("EPITHETS %s\n" % sorted((k, sorted(v)) for k, v in epithets.items() if v))
    # code-side merge of leftovers, as in delta4
    allnames = {n: {bare(x) for x in names(n)} for n in known}
    common = common_words([b for v in allnames.values() for b in v])
    rename = {}
    sh = shared()
    for n in known:
        for s in allnames[n]:
            if " " in s or len(s) < 3 or s in common or s in sh:
                continue
            fits = [m for m in known if m != n and frozenset((m, n)) not in never
                    and m not in notpeople and n not in notpeople and not (titled(n) and titled(m))
                    and not (honor(n) and honor(n) != honor(m)) and any(
                b == s or (" " in b and same(s, b, common)) for b in allnames[m])]
            if len(fits) == 1 and len(fits[0]) > len(n):
                rename[n] = fits[0]
                break
    for a, b in list(rename.items()):
        while b in rename:
            b = rename[b]
        rename[a] = b
    log.write("CODE MERGE %s\n" % sorted(rename.items()))
    group = collections.defaultdict(set)
    for n in known:
        group[rename.get(n, n)] |= set(names(n))
    sq_seen = squash(seen)
    used = lambda x: mentions(x, sq_seen)
    shown = {}
    owners = collections.defaultdict(set)
    for t, al in group.items():
        for x in al:
            w = low(x).split()
            owners[w[-1] if w else ""].add(t)
    one = lambda x: len(x.split()) == 1
    ok = lambda x: proper(x) and low(x) not in SPECIES and not (one(x) and len(owners[low(x)]) > 1)

    def pick(al, t):
        return [x for x in al if ok(x) and not titled(x)] or [x for x in al if ok(x)] \
            or [x for x in al if proper(x) and not titled(x)] or [x for x in al if proper(x)] or [t]
    for t, al in group.items():
        cands = pick(al, t)
        best = max(cands, key=lambda x: (used(x), len(x.split()), x))
        # a given name grows into given + surname ("Percy" -> "Percy Jackson")
        longer = [x for x in cands if x != best and x.split()[0] == best.split()[0] and len(x.split()) > len(best.split())]
        if longer:
            best = max(longer, key=lambda x: (used(x), len(x.split()), x))
        shown[t] = best
    log.write("SHOWN %s\n" % sorted((t, b) for t, b in shown.items() if t != b))

    # 1: a row shows only names the book has used by then
    firsts = {}

    def first(x):
        if x not in firsts:
            q = squash(x)
            firsts[x] = next(((o, n) for o, seg in parts for n, t in seg
                              if q and re.search(r"\b%s\b" % re.escape(q), squash(t))), (10 ** 9, 0))
        return firsts[x]

    def show_at(t, w, at):
        al = {x for x in group[t] if first(x) <= at} | {w}
        cands = pick(al, w)
        best = max(cands, key=lambda x: (used(x), len(x.split()), x))
        longer = [x for x in cands if x != best and x.split()[0] == best.split()[0] and len(x.split()) > len(best.split())]
        return max(longer, key=lambda x: (used(x), len(x.split()), x)) if longer else best

    grp = {n: rename.get(n, n) for n in known}
    for n in known:
        rename[n] = shown[rename.get(n, n)]
    out_rows = []
    for o, pn, w, t in rows:
        # 2: a row written under a name that merged later belongs to the merged entity
        g = grp.get(cur(w), cur(w))
        s = show_at(g, w, (o, pn))
        final = shown.get(g, s)
        if s != final:
            log.write("ROWNAME %d:%d %s shown as %s (final name %s not used yet)\n" % (o, pn, w, s, final))
        out_rows.append((o, pn, s, t, final))

    table = collections.defaultdict(set)
    for n in known:
        t = rename.get(n, n)
        table[t] |= set(names(n))
    alias_out = {t: sorted(v - {t}) for t, v in sorted(table.items())}
    for k, v in epithets.items():
        t = rename.get(cur(k), cur(k))
        if t in alias_out:
            alias_out[t] = sorted(set(alias_out[t]) | v)
    alias_out["_not_people"] = sorted(notpeople)
    json.dump(alias_out, open(out + ".aliases.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False)

    done, last = set(), {}
    with open(out, "w", encoding="utf-8") as f:
        f.write(("delta7 live:" if live else "delta7: replayed;") +
                " repeatable, people named once, code-found nickname pairs\n\n")
        for o, pn, w, t, ent in out_rows:
            if ent in done:
                t = re.sub(r"\s+([.,;])", r"\1", NARR_I.sub("", t))
            done.add(ent)
            # 3: nothing new since this entity's last row
            if last.get(ent) == t:
                stats["repeat rows dropped"] += 1
                log.write("REPEAT %d:%d %s\n" % (o, pn, w))
                continue
            last[ent] = t
            f.write("%d:%d\t%s\theard\t1\t%s\n" % (o, pn, w, t.replace("\t", " ").replace("\n", " ")))
    print("calls:", dict(calls), "minutes: %.1f" % ((time.time() - t0) / 60))
    print("updates:", dict(stats))
    print("not people:", len(notpeople))
    print("never-merge pairs:", sorted(tuple(sorted(p)) for p in never))
    print("code merges:", sorted(rename.items()))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
