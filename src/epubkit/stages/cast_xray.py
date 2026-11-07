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
import itertools
import json
import os
import re

from . import cast as C

PASSAGE = 16000
DESC = 90
FIRST_WORDS, CHANGE_WORDS, CARRY_WORDS = 24, 16, 40
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
                  r"afterword|author.?s note|a note from the author|special thanks|thank you|"
                  r"patreon|backers|"
                  r"discussion (questions|guide)|(an )?excerpt|preview|sneak peek|read on\b|"
                  r"coming soon|a sample|bonus (chapter|content)|titles available|keep reading|"
                  r"turn the page|don.t miss)", re.I)

#: the author's own pages before the story starts
FRONT = re.compile(r"^\W*(acknowledg|dedicat|foreword|preface|introduction|author.?s note|"
                   r"a note from|note to (the )?reader|copyright|contents|table of contents|"
                   r"title page|also by|praise for|special thanks|thank you|patreon|backers|"
                   r"epigraph|maps?\b)", re.I)
PRONOUNS = {"i", "me", "my", "we", "us", "you", "he", "him", "she", "her", "they", "them", "it",
            "narrator", "the narrator"}

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
{{"new": [{{"name": "...", "type": "...", "one": "yes or no", "aliases": ["..."], "who": "...", "evidence": "..."}}],
  "updates": [{{"name": "...", "status": "SAME or CHANGED", "now": "...", "event": "...", "other": "...", "quote": "..."}}]}}

Rules for "new":
- Every named individual in the NEW TEXT who is not in KNOWN PEOPLE{and_unlisted}.
- "type": one of person, creature, animal, ai, god, monster, company, place, item, group, kind, title, reference.
- "one": "yes" only for one particular individual in this story. "no" for a kind of creature, species, race, job or monster type, a group or crowd, a real person or character from outside this story who is only mentioned in a comparison or joke, and the book's author or people the author thanks.
- "name": the fullest name the text gives, never a pronoun or "the narrator" (use the narrator's name). "aliases": other names the text uses for the same individual. Never pronouns. A shared surname is not an alias.
- "who": ONE sentence (under 25 words) on who they are: their lasting role and relation to the main characters, from this text only. Not their mood or what they are doing right now.
- "evidence": a short exact quote (under 20 words) from the NEW TEXT that names them.
Rules for "updates" (one per CHECK name, no others):
- "status": CHANGED only if their role, allegiance, form, rank, relationship or status changes for good in this text; otherwise SAME and leave the other fields empty.
- "now": ONE sentence (under 16 words): who they are now, after the change.
- "event": a few words for the change itself. "other": the other individual involved, or "".
- "quote": a short exact quote (under 25 words) from the NEW TEXT that shows the change and names them.
- If the text shows a person going by a new name, mark them CHANGED and give the new name in "now"."""

# The event-first step (recaps.cast_events): the model says what lasting
# things happened in the part, then to whom, instead of being asked about
# each listed name in turn ("did Mordecai change?" invites a yes).
STEP_EVENTS = STEP.split("Return JSON only")[0] + """Return JSON only, in this shape:
{{"new": [{{"name": "...", "type": "...", "one": "yes or no", "aliases": ["..."], "who": "...", "evidence": "..."}}],
  "events": [{{"what": "...", "who": "...", "kind": "...", "also": "...", "happened": "yes or no", "lasting": "yes, no or unsure", "quote": "..."}}]}}

""" + STEP.split("Return JSON only")[1].split("\n\n", 1)[1].split("Rules for \"updates\"")[0] + \
    """Rules for "events":
- First read the NEW TEXT for things that change someone for good: they die or come back, are born, join or leave a group or side, get or lose a job, rank or title, take a new name, form, body or species, are permanently marked, injured or cursed, or begin or end a lasting bond (marry, break up, become enemies or allies). Then say whom each one happened to.
- Not events: a fight, a trip, a plan, a mood, a conversation, being knocked out, asleep, frozen, held for a while, summoned or sent away, a level, skill, spell or item.
- "what": ONE sentence (under 16 words) on the change, naming the person.
- A game or system line that gives someone a new kind, form or class ("Name. Kind. Level 50.") is an event. So is a reveal of who someone really is or how they are related.
- "who": the one individual it happens to, by the name the text uses. If it is someone who only shares a name with a listed person (a monster or enemy also called that), give the name and add their kind, like "Rook (the troll)".
- "also": when the same event changes a second individual for good (the one killed by "who", the one "who" marries, the one who gets "who"'s mark), their name; else "". Who did it is not "also" unless they change too.
- "kind": a few words for the kind of change.
- "happened": "yes" only if the text shows it happening; "no" if it is only said, planned, feared, imagined, remembered from long before, or a rumour.
- "lasting": "yes" only if it will still be true after this scene; "unsure" if the text does not show that.
- "quote": a short exact quote (under 25 words) from the NEW TEXT that shows the change and names the person.
- If nothing lasting happens, "events" is []."""

LASTING = """Part of a novel:
<<<
{context}
>>>

A character list is about to say this about {name}: {what}

Is that a lasting change to who {name} is, or only something that happens to them for a while?
LASTING: they die or come back; lose a body part, wing or eye, or take a new body, form, kind or class; take a new name, title, role, job, rank, faith or side; are marked, cursed or bound; begin or end a bond with someone (marry, break up, become enemies); or a reveal of who they really are or how they are related. These stay true unless the passage shows them undone.
FOR A WHILE: a task or quest, a trip, being called away, a fight, a mood, an illness or injury they get over, using or getting an item, one moment in one scene.
The first line of your answer must be exactly LASTING or exactly FOR A WHILE. If you cannot tell, answer FOR A WHILE."""

PASSING_EVENT = re.compile(r"\b(level|levels|leveled|stats?|points|leaderboard|"
                           r"equips?|equipped|looted|armor)\b", re.I)

REWRITE = """A spoiler-free character list has this entry:
{entry}

What has happened to {name} since, in the order the book tells it:
{fact}

Write the new entry for {name}: at most two sentences, under 40 words, without their name or any heading at the start. First who they are now (their lasting role, kind and relation to the main characters), then the latest change. Keep every title, role, kind and relationship unless a later change ends it; leave out anything a later change replaces and anything that only describes one moment or place. Use only what is written above, and no other names. Return only the new entry."""

HEADER = re.compile(r"^[^.:]{0,80}?\(also [^)]*\)\s*:\s*")


GUARD = """Two entries from a character list:

A: {a}
B: {b}

Are A and B the same individual? A parent and child, brothers and sisters, a husband and wife or any two relatives who share a family name are DIFFERENT. If they are different people, the first line of your answer must be exactly DIFFERENT ENTITIES. If they are the same person, the first line must be exactly SAME."""


WHOSE = """A character list has this entry:
{entry}

A new line is proposed for {name}: {now}

The part of the book it comes from:
<<<
{context}
>>>

Is the new line about {name} from the entry? In stories people can take a new body, form, species, job or name; that alone never makes them someone else. It is about someone else only if the passage shows another individual: a different person or creature present in this part of the book, or a different one that happens to have the same name (for example a monster, mob or enemy the characters note is only named like {name}). If it is about someone else, the first line of your answer must be exactly DIFFERENT ENTITIES. If it is about {name}, or you cannot tell, the first line must be exactly SAME."""


GUARD_LISTED = """

The series' character list gives both names to one person. Answer SAME unless the entries show they are two different people."""


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


def words_cut(s: str, words: int) -> str:
    """The whole line up to a word budget: what an earlier book said about
    someone is often two sentences (who they are, then what they became),
    and the second is the one that matters (Mordecai was "a rat-like
    creature who guards the Tutorial Guild door" in book 5 when only the
    first was kept)."""
    w = s.split()
    return " ".join(w[:words]).rstrip(",;:") + ("…" if len(w) > words else "")


#: a state, not who someone is: levels, skills and stats change every
#: chapter, and being drunk or asleep is over by the next book
PASSING = re.compile(r"\b(level|levels|leveled|skills?|spells?|stats?|charisma|constitution|"
                     r"strength|intelligence|dexterity|points|leaderboard|ranked|rank|"
                     r"unconscious|passed out|drunk|asleep|injured|wounded|currently|"
                     r"right now|tattoo|armor|wears|wearing|equipped|received|looted)\b", re.I)
#: what is left of a sentence once its level was taken out ("Carl is now
#: and has gained", "Donut is now after the fight")
BROKEN = re.compile(r"\b(?:is|was|are|were) now (?:and|after|with|but|from|by)\b|"
                    r"\b(?:is|was) now[,.]?$", re.I)


def carried(desc: str) -> str:
    """What the last book's line says that is still true: who they are
    (its first sentence) and the last thing they became, never a passing
    state or a sentence broken by the level being taken out of it."""
    return words_cut(" ".join(x for x in carry_split(desc) if x), CARRY_WORDS)


def carry_split(desc: str) -> tuple:
    """carried() as (who they are, what they became), so that a newer change
    in this book replaces what they became instead of piling on top."""
    parts = [x.strip() for x in re.split(r"(?<=[.!?])\s+(?=[A-Z])", desc.strip()) if x.strip()]
    if not parts:
        return "", ""
    later = [x for x in parts[1:] if not PASSING.search(x) and not BROKEN.search(x)]
    parts = [x[:1].upper() + x[1:] for x in parts]       # "rock monster..." once a level went
    first = words_cut(parts[0], CARRY_WORDS)
    room = CARRY_WORDS - len(first.split())
    change = words_cut(later[-1], room) if later and room >= 4 else ""
    return first, change


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


def variant(a: str, b: str) -> bool:
    """Two forms of one name, by their words alone: titles and ranks aside,
    one's words are among the other's ("Katia" / "Katia Grim", "Big Tina" /
    "Tina"), or a one-word name begins the other's first word or the other
    way round ("Bea" / "Miss Beatrice", "Gwen" / "Gwendolyn Duet", "Sledge" /
    "Sledgie")."""
    wa, wb = bare(a).split(), bare(b).split()
    if not wa or not wb:
        return False
    if wa == wb:
        return True
    s, lg = (wa, wb) if len(wa) <= len(wb) else (wb, wa)
    if len(s) < len(lg) and set(s) <= set(lg) and len("".join(s)) >= 2 \
            and not all(w in STOPW for w in s):
        return True
    # a nickname is the start of the longer name, never longer than it
    # ("Manasa" is not "Mana Genita")
    if len(s) == 1 and len(s[0]) >= 3 and len(s[0]) < len(lg[0]) and lg[0].startswith(s[0]):
        return True
    return misspelt(wa, wb)


def one_letter(a: str, b: str) -> bool:
    """b is a with one letter added or left out, not a plural "s"; or, in a
    long name (7+ letters), one letter changed ("Theobold" / "Theobald")."""
    if len(a) == len(b) >= 7:
        return sum(x != y for x, y in zip(a, b, strict=True)) == 1
    if len(a) > len(b):
        a, b = b, a
    if len(b) != len(a) + 1 or b == a + "s":
        return False
    return any(b[:i] + b[i + 1:] == a for i in range(len(b)))


def misspelt(wa: list, wb: list) -> bool:
    """One name spelt two ways: same words but one, and that one differs by a
    single added or dropped letter ("Lucia Marr" / "Lucia Mar", "Vincente" /
    "Vicente"). A lone name needs 5+ letters so short names stay apart."""
    if len(wa) != len(wb):
        return False
    diff = [(x, y) for x, y in zip(wa, wb, strict=True) if x != y]
    if len(diff) != 1:
        return False
    x, y = diff[0]
    return min(len(x), len(y)) >= (5 if len(wa) == 1 else 3) and one_letter(x, y)


LINK = r"(?:(?:also|now|later|then|usually|often|sometimes|simply) )?(?:called|known as|named|nicknamed|aka|or|alias|whose (?:real |true )?name (?:is|was))"



def twice(a: str, b: str) -> bool:
    """Two shown names that are one name: the same bare name, or spelt one
    letter apart. Mr./Mrs. with a family name is someone else (Mrs. Ghazi /
    Ghazi). The report's "shown twice" and the scorecard both use this."""
    if any(honor(n) and surname_only(n) for n in (a, b)):
        return False
    return bare(a) == bare(b) or misspelt(bare(a).split(), bare(b).split())

def linked(a: str, b: str, text: str) -> bool:
    """The text itself says a and b are one: "X, also known as Y", "X (Y)",
    "Y's real name was X", "I am X" said where Y speaks."""
    t = squash(text)
    x, y = squash(a), squash(b)
    if not x or not y:
        return False
    ex, ey = re.escape(x), re.escape(y)
    for p, q in ((ex, ey), (ey, ex)):
        if re.search(r"\b%s\b %s (?:the )?%s\b" % (p, LINK, q), t) or \
                re.search(r"\b%s\s*\(\s*%s\s*\)" % (p, q), text.lower()) or \
                re.search(r"\b%s s (?:real|true) name (?:is|was) %s\b" % (p, q), t):
            return True
    for sent in re.split(r"(?<=[.!?])\s+", text):
        st = squash(sent)
        if re.search(r"\b(?:i am|i m|my name is|call me) %s\b" % ey, st) and \
                re.search(r"\b%s\b" % ex, st):
            return True
        if re.search(r"\b(?:i am|i m|my name is|call me) %s\b" % ex, st) and \
                re.search(r"\b%s\b" % ey, st):
            return True
    return False


def parse(text: str) -> dict:
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        got = json.loads(m.group(0)) if m else {}
        if isinstance(got, dict):
            return got
    except ValueError:
        pass
    # an answer cut short: keep every complete entry
    second = "events" if '"events"' in (text or "") else "updates"
    got, cut = {"new": [], second: []}, (text or "").find('"%s"' % second)
    for o in re.finditer(r"\{[^{}]*\}", text or ""):
        try:
            got[second if 0 <= cut < o.start() else "new"].append(json.loads(o.group(0)))
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
    """The book's own documents: the author's pages before the story are
    skipped (dedication, preface, thanks), and it stops at back matter, a
    sample or the next book's chapter 1 in the second half."""
    first = next((i for i, (_o, _p, label, ps) in enumerate(docs[:max(3, len(docs) // 3)])
                  if chapter_no(label or "", " ".join(t for _n, t in ps[:2])[:200]) is not None),
                 None)
    lead = 0
    for i, (o, _p, label, ps) in enumerate(docs[:first if first is not None
                                                 else max(1, len(docs) // 4)]):
        head = " ".join(t for _n, t in ps[:2])[:200]
        if FRONT.match(label or "") or FRONT.match(head) or \
                (first is not None and sum(len(t) for _n, t in ps) < 1500):
            log.append("skip order %d %r: before the story" % (o, label or head[:40]))
            lead = i + 1
        else:
            break
    docs = docs[lead:]
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
    events = bool(getattr(getattr(getattr(ctx, "config", None), "recaps", None), "cast_events", False)
                  or os.environ.get("CAST_EVENTS"))
    ledger = bool(getattr(getattr(getattr(ctx, "config", None), "recaps", None), "cast_ledger", False)
                  or os.environ.get("CAST_LEDGER"))
    run = _Ledger if ledger else _Records if events else _Run
    return run(ctx, docs, ask, hero, first_person, view, names_list).go()


class _Run:
    def __init__(self, ctx, docs, ask, hero, first_person, view=None, names_list=None):
        self.ctx, self.ask = ctx, ask
        # the series' names list (tools/wiki_names.py): only which names are
        # one person and which are not, never what anyone is like
        self.names_list = names_list if names_list else None
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
        self.book = book_text
        self.book_sq = squash(book_text)
        # a one-word "name" the book also writes in lower case is a common
        # noun (a species, a job): "changeling", "grull"
        self.lower_words = collections.Counter(
            re.findall(r"(?<![\w’'.!?:\"“] )\b([a-z][a-z'’\-]{2,})\b", book_text))
        self.cap_words = collections.Counter(re.findall(r"\b([A-Z][a-z'’\-]{2,})\b", book_text))
        self.parts = [(o, seg) for o, _p, _l, ps in self.docs for seg in _segments(ps, PASSAGE)]
        # the earlier books: everyone the reader already knows starts from
        # who they were when the last book ended, not from a vague first
        # mention in this one
        self.carried: set = set()
        self.shown: set = set()
        for name, (desc, aliases, _n) in (getattr(view, "people", None) or {}).items():
            name = norm(name)
            if not desc or not proper(name) or low(name) in PRONOUNS or name in self.known:
                continue
            # two earlier books may have kept one person under two forms of a
            # name ("Drakea" / "Crawler Drakea"): one entry, not two rows
            twin = next((k for k in self.carried if self.retitled(k, name)), None)
            if twin:
                self.known[twin]["aliases"] = sorted(
                    set(self.known[twin]["aliases"]) | {name} |
                    {norm(a) for a in aliases if proper(norm(a))} - {twin})
                self.log.append("from the books before: %s is %s" % (name, twin))
                continue
            self.known[name] = dict(
                aliases=[norm(a) for a in aliases if proper(norm(a)) and norm(a) != name],
                type="person", first=carry_split(desc)[0], change=carry_split(desc)[1],
                narrator=False)
            self.carried.add(name)
        if self.carried:
            self.log.append("%d people from the books before" % len(self.carried))

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
        if len(fits) == 1:
            return fits[0]
        if fits:
            return None
        # a nickname: "Bea" for Miss Beatrice, "Gwen" for Gwendolyn Duet
        fits = [k for k in self.known
                if any(variant(name, x) for x in self.names(k))
                and not any(same_family(name, x) for x in self.names(k))]
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
        """Code's own answer for relatives: never the same person. Two names
        that share a family name are relatives only when both start with a
        given name: "Ringmaster Grimaldi" / "Papa Grimaldi" start with words
        the book also writes in lower case, so they go to the guard."""
        def given(n):
            w = plain(n).split()
            return bool(w) and not re.search(r"\b%s\b" % re.escape(w[0]), self.book)
        return any(same_family(x, y) and given(x) and given(y)
                   for x in a_names for y in b_names) or \
            kin_of(a_desc, b_names) or kin_of(b_desc, a_names)

    def listed(self, a_names, b_names):
        """What the names list says: True one person, False two, None silent."""
        if not self.names_list:
            return None
        oa = {self.names_list.of(x) for x in a_names} - {""}
        ob = {self.names_list.of(x) for x in b_names} - {""}
        if not oa or not ob:
            return None
        return bool(oa & ob)

    def retitled(self, k, name):
        """The same name with a title only one side carries ("Princess Donut" /
        "Donut", "King Henrik" / "Henrik", "Mexx-6000" / "Mexx"): one person,
        no need to ask. Two
        different titles, or Mr./Mrs. with a family name alone ("Mr. Holt"),
        still go to the guard."""
        def family_only(n):
            # "Mr. Holt" is a family name; "Sir Ferdinand" is not
            return honor(n) not in ("", "sir", "dame") and surname_only(n)
        b = bare(norm(name))
        if not b or family_only(norm(name)):
            return False
        def num(n):
            return re.sub(r"\s+\d+$", "", n)
        for x in self.names(k):
            bx = bare(x)
            # a model number only one side carries: "Mexx-6000" / "Mexx"
            if (bx != b and num(bx) != b and num(b) != bx) or family_only(x):
                continue
            if honor(name) and honor(x) and honor(name) != honor(x):
                continue
            if not titled(name) or not titled(x) or plain(name) == plain(x):
                return True
        # one name spelt two ways ("Theobold" / "Theobald")
        if any(misspelt(b.split(), bare(x).split()) for x in self.names(k)):
            return True
        # a job the book also writes in lower case, used as a title:
        # "Ringmaster Grimaldi" / "Grimaldi" ("the ringmaster said")
        p = plain(norm(name)).split()
        for x in self.names(k):
            q = plain(x).split()
            s, lg = (p, q) if len(p) < len(q) else (q, p)
            if s and len(lg) == len(s) + 1 and lg[1:] == s and len(lg[0]) >= 4 \
                    and lg[0] not in STOPW and re.search(r"(?<![.!?\"“]\s)\b%s\b"
                                                         % re.escape(lg[0]), self.book):
                return True
        return False

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
            hint = GUARD_LISTED if self.listed(self.names(a), [b_name]) else ""
            r = self.ask(GUARD.format(a=self.entry(a), b=b_name + ": " + b_who) + hint, SYSTEM,
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

    def named_as(self, desc, name):
        """Someone known the description opens by naming: Glass Wizard given
        "Ghazi, the author of the letter", Ghazi given "The Glass Wizard who
        sent a letter". Only a candidate: the guard still decides."""
        for k in self.known:
            for x in self.names(k):
                if plain(x) == plain(name) or len(x) < 4 or low(x) in PRONOUNS:
                    continue
                if re.match(r"(?:the\s+)?%s(?:,|\s+(?:who|is|was)\b)" % re.escape(x), desc, re.I):
                    return k
        return None

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
        """A word for a kind, not someone's name: written in lower case too
        ("changeling"), or written as one of many - "a Kobold", "two more
        Kobolds" - at least twice."""
        w = low(name).split()
        # a word the book mostly capitalises is a name, even if it is also
        # written in lower case now and then ("Elle", and "elle" in French)
        if low(name) in GENERIC or (len(w) == 1 and len(name.split()) == 1
                                    and self.lower_words[w[0]] >= max(
                                        1, self.cap_words[w[0][:1].upper() + w[0][1:]])):
            return True
        if len(name.split()) > 2:
            return False
        n = re.escape(name)
        one = len(re.findall(r"\b(?:[Aa]n?|[Aa]nother|[Ee]very|[Ee]ach)\s+%s\b" % n, self.book))
        many = len(re.findall(r"\b%s(?:e?s)\b" % n, self.book))
        return one >= 1 and one + many >= 2

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

    def is_known(self, n) -> bool:
        """Listed already, or the book's main character."""
        if not n:
            return False
        # with or without a title: "Crawler Carl" is the lead "Carl"
        forms = {plain(n), plain(bare(n))}
        names = {plain(self.lead or ""), plain(bare(self.lead or ""))} - {""}
        for k in self.known:
            names |= {plain(x) for x in self.names(k)} | {plain(bare(x)) for x in self.names(k)}
        return bool(forms & names)

    def add(self, p, order, seg, text, ptext):
        if not isinstance(p, dict):
            return
        name, desc = norm(p.get("name")), str(p.get("who") or "").strip()
        ev, typ = str(p.get("evidence") or "").strip(), str(p.get("type") or "").strip().lower()
        aliases = [norm(a) for a in p.get("aliases") or [] if norm(a) and norm(a) != name]
        if not name or not desc or name in self.notpeople:
            return
        if name in NOT_NAMES or low(name) in PRONOUNS or not proper(name):
            self.log.append("drop %s: not a name" % name)
            return
        if str(p.get("one", "yes")).strip().lower() in ("no", "false", "n"):
            # someone already listed stays a person: one passage's "the Carls
            # of the world" must not shut Carl out for the rest of the book
            if self.is_known(name) or any(self.is_known(a) for a in aliases):
                self.log.append("kept %s: said not one individual, but already listed" % name)
                return
            for n in [name] + aliases:
                self.notpeople[n] = "not one individual"
            self.log.append("not one individual %s (%s)" % (name, typ or "?"))
            return
        # an alias the model gives is kept only when it is a form of the
        # name or the text itself ties the two together
        kept = [a for a in aliases if proper(a) and low(a) not in PRONOUNS
                and (variant(name, a) or linked(name, a, text))]
        if len(kept) < len(aliases):
            self.log.append("aliases not backed by the text for %s: %s"
                            % (name, [a for a in aliases if a not in kept]))
        aliases = kept
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
        known_name = any(plain(name) in {plain(x) for x in self.names(k)} for k in self.known)
        if not known_name and self.common_noun(name):
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
                if self.is_known(n):
                    continue
                self.notpeople[n] = typ
            self.log.append("not a person %s (%s)" % (name, typ))
            return
        para = next((n for n, t in seg if in_text(name, squash(t))), seg[0][0])
        hit = self.find(name) or next((self.find(a) for a in aliases if self.find(a)), None) \
            or self.aka(ev, name) or self.named_as(desc, name)
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
        if hit and self.listed(self.names(hit), [name, *aliases]) is False:
            self.log.append("names list: %s and %s are two people" % (hit, name))
            self.never.add(frozenset((hit, name)))
            hit = None
        if hit and self.listed(self.names(hit), [name, *aliases]) and \
                any(variant(x, name) or linked(x, name, text) for x in self.names(hit)):
            main_name = self._grow(hit, name, aliases)
            self.log.append("joined %s + %s -> %s (names list)" % (hit, name, main_name))
            return
        if hit and self.retitled(hit, name):
            main_name = self._grow(hit, name, aliases)
            self.log.append("joined %s + %s -> %s (same name, title added or dropped)"
                            % (hit, name, main_name))
            return
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
                if idx == 0:
                    # the head says who they are: keep what comes before the
                    # claim ("A librarian killed in the flood" -> "A
                    # librarian"), so the rest is not left without a subject
                    # ("Who held a Master's Degree...", "Created Ruckus.")
                    say = "|".join(CLAIMS[b][0] for b in bad)
                    m = re.search(r"\b(?:%s)\b" % say, cl, re.I)
                    head = cl[:m.start()] if m else ""
                    head = re.sub(r"\s+(?:who|which|that|was|is|were|are|and|by|"
                                  r"recently|later|now)?\s*$", "", head, flags=re.I).strip(" ,;")
                    if len(head.split()) < 2 or not re.search(r"[A-Za-z]{3}", head):
                        head = "Someone"
                    out.append(("", head))
                    if idx + 1 < len(pieces) and pieces[idx + 1][0].strip() in ("and", "but"):
                        pieces[idx + 1] = (" who ", pieces[idx + 1][1])
                # "goose who killed X and attacks" -> "goose who attacks"
                elif sep.strip() in ("who", "which", "that") and idx + 1 < len(pieces) \
                        and pieces[idx + 1][0].strip() in ("and", "but"):
                    nxt = pieces[idx + 1][1]
                    # "who killed a guard and the mad mage's goal" -> "who is
                    # the mad mage's goal"
                    if re.match(r"(?:the|a|an|his|her|their|its|[A-Z]\w*'s)\b", nxt):
                        nxt = "is " + nxt
                    pieces[idx + 1] = (sep, nxt)
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

    def nearest(self, before, after=""):
        """The listed person named closest to a quote that sits between
        before and after, or None."""
        best, gap = None, 10 ** 9
        for e in self.known:
            for f in self.forms(e):
                pat = r"\b%s\b" % re.escape(f)
                for m in re.finditer(pat, before):
                    if len(before) - m.end() < gap:
                        best, gap = e, len(before) - m.end()
                m = re.search(pat, after)
                if m and m.start() < gap:
                    best, gap = e, m.start()
        return best

    def verify(self, k, u, text, ptext, seg, subject=False):
        """Empty when the change is backed by its quote, else why not. With
        subject, a quote that does not name them must follow a stretch
        where they are the last person named (not just named somewhere in
        the 300 characters before, which lets Katia take a line about
        whoever is named after her)."""
        q = str(u.get("quote") or "").strip()
        sq = squash(q)
        if not sq:
            return "no quote"
        if sq not in ptext and not quote_ok(q, text):
            return "quote not in text"
        # the narrator is "I" in the story, and "you" in game messages and
        # what others say to them ("You have been granted...")
        mine = self.forms(k) + sorted(self.epithets[k]) + \
            ((["i", "me", "my"] + (["you", "your"] if subject else []))
             if self.known[k]["narrator"] else [])

        def hit(fs, s):
            return any(re.search(r"\b%s\b" % re.escape(f), s) for f in fs)
        at = ptext.find(sq[:40])
        before = ptext[max(0, at - 300):at] if at >= 0 else ""
        said = FIRSTP.search(sq) and any(
            sq[:40] in squash(t) and hit(self.forms(k) + sorted(self.epithets[k]), squash(t))
            for _n, t in seg)
        if subject and not (hit(mine, sq) or said):
            # a title, kind or pronoun ("the deckmaster", "she"): the
            # person it stands for is the one named closest to the quote,
            # before it or just after ("A deity has fallen." then
            # "Crawler Paz Lo has slain the goddess, Ysalte.")
            if any(hit(self.forms(e), sq) for e in self.known if e != k):
                return "the quote names someone else"
            end = at + len(sq) if at >= 0 else 0
            after = ptext[end:end + 400] if at >= 0 else ""
            last = self.nearest(before, after)
            if last is None:
                return "quote does not name them"
            if last != k:
                return "the person named closest to the quote is %s" % last
        elif not (hit(mine, sq) or hit(self.forms(k) + sorted(self.epithets[k]), before) or said):
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

    def whose(self, k, now, u, text):
        """The model's look at a change the code let through: is the new line
        really this person's? A name near a quote is not enough (Mordecai
        speaks just before a Hills Cyclops is described), and a monster can
        share a name with a listed person (a duende mob called Mordecai).
        Only a clear DIFFERENT turns it down; no answer keeps it."""
        q = str(u.get("quote") or "").strip()
        at = text.find(q[:40]) if q else -1
        if at < 0:
            at = text.lower().find(q[:40].lower()) if q else -1
        # the lines after the quote too: "same name as Mordecai!" comes after the mob's tag
        context = text[max(0, at - 700):at + len(q) + 700] if at >= 0 else q
        self.calls["whose"] += 1
        try:
            r = self.ask(WHOSE.format(entry=self.entry(k), name=k, now=now,
                                      context=context.strip()), SYSTEM, _usable_guard).strip()
        except Exception:                                    # noqa: BLE001
            r = ""
        self.log.append("whose %s | %s -> %s" % (k, now, r.splitlines()[0] if r else "no answer"))
        if r.upper().startswith("DIFFERENT"):
            self.stats["someone else's"] += 1
            return "about someone else (model)"
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
        # the people this part names, and everyone it asks about
        listed = sorted(k for k in self.known
                        if counts[k] > 0 or k in check or self.known[k]["narrator"])
        manifest = "\n".join("- " + self.entry(n)[:DESC + len(n)]
                             for n in listed) or "(none yet)"
        # someone from the earlier books gets their row where this book
        # first names them
        for k in listed:
            if k in self.carried and k not in self.shown and counts[k] > 0:
                f = self.forms(k)
                pat = re.compile(r"\b(?:%s)\b" % "|".join(map(re.escape, f))) if f else None
                para = next((n for n, t in seg if pat and pat.search(squash(t))), seg[0][0])
                self.rows.append((order, para, k, self.who(k)))
                self.shown.add(k)
        ctext = ("\nCHECK (say for each whether they CHANGED or stayed the SAME in this text):\n"
                 + "\n".join("- " + k for k in check) + "\n") if check else "\nCHECK: (none)\n"
        utext = ("\nUNLISTED names in this part: " + "; ".join(n + hint for n, hint in unl) +
                 " -- for each, is it a person, and if so who, with a quote? Put each in \"new\" "
                 "with its real type (a name that is not a person gets its own type: place, "
                 "item, group, title...).\n") if unl else ""
        self.calls["step"] += 1
        try:
            rtext = self.ask_step(self.step_prompt(manifest, text, ctext, utext, unl))
        except Exception as exc:                             # noqa: BLE001
            self.log.append("part %d: no answer (%s)" % (i + 1, exc))
            return
        got = parse(rtext)
        for p in got.get("new") or []:
            self.add(p, order, seg, text, ptext)
        self.take(got, order, seg, text, ptext)
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

    def ask_step(self, prompt):
        return self.ask(prompt, SYSTEM, _usable_step)

    def step_prompt(self, manifest, text, ctext, utext, unl):
        return STEP.format(known=manifest, text=text, check=ctext, unlisted=utext,
                           and_unlisted=", including each UNLISTED name" if unl else "")

    def take(self, got, order, seg, text, ptext):
        """Keep each CHANGED update that passes the checks."""
        given: dict = {}                    # change text -> who it went to, this part
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
            # one event copied onto a second person ("Reanimated corpse head
            # biting Vrah's neck" for Bogdon Ro, then for Langley too)
            same_now = squash(str(u.get("now") or ""))
            if not why and len(same_now.split()) >= 6 and given.get(same_now, k) != k:
                why = "same change as %s's" % given[same_now]
            if not why and same_now:
                given[same_now] = k
            now = str(u.get("now") or "").strip()
            if not now:
                why = why or "no 'now'"
            if not why:
                why = self.whose(k, now, u, text)
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

    def self_check(self, shown_people):
        """The last look at every line before it is written, with no model
        and no answer key: what used to take a person hours of reading rows.
        A line is mended when it can be (a capital to start, at most two
        sentences, no gap where a level was) and left out when it can't (it
        says nothing, or it is word for word someone else's line)."""
        fixed = collections.Counter()
        owner: dict = {}
        # in reading order, so a line belongs to whoever had it first
        events = sorted(((r[0], r[2], n, i) for n, p in enumerate(shown_people)
                         for i, r in enumerate(p.rows)), key=lambda e: (e[0], e[1], e[2], e[3]))
        kept = collections.defaultdict(list)
        for _o, _pn, n, i in events:
            p = shown_people[n]
            o, path, pn, status, text = p.rows[i]
            t = text.strip()
            parts = [x for x in re.split(r"(?<=[.!?])\s+(?=[A-Z])", t) if x]
            parts = [x for x in parts if not BROKEN.search(x)] or parts[:1]
            if len(parts) > 2:
                parts = [parts[0], parts[-1]]
                fixed["cut to two sentences"] += 1
            last = parts[-1] if len(parts) > 1 else ""
            if last and owner.get(squash(last), p) is not p and len(squash(last).split()) >= 6:
                # someone else's change tacked on: keep who this one is
                parts = parts[:-1]
                fixed["left out: someone else's change"] += 1
            t = " ".join(parts)
            if re.match(r"(?:who|which|that|whose)\b", t, re.I):
                t = "Someone " + t[0].lower() + t[1:]
                fixed["given a subject"] += 1
            if t[:1].islower():
                t = t[:1].upper() + t[1:]
                fixed["capital added"] += 1
            if len(t) > 220:
                t = words_cut(t, 36)
                fixed["shortened"] += 1
            sq = squash(t)
            if owner.get(sq, p) is not p and len(sq.split()) >= 6:
                fixed["left out: someone else's line"] += 1
                continue
            if re.fullmatch(r"(?:An?|The) [\w'-]+(?: [\w'-]+)?\.?", t) and len(p.rows) > 1:
                fixed["left out: says nothing"] += 1
                continue
            owner.setdefault(sq, p)
            for x in parts[1:]:
                owner.setdefault(squash(x), p)
            kept[n].append((o, path, pn, status, t))
        for n, p in enumerate(shown_people):
            p.rows[:] = kept.get(n) or p.rows[:1]
        if fixed:
            self.log.append("self-check: " + ", ".join(
                "%s %d" % kv for kv in sorted(fixed.items())))

    def finish(self):
        # one person still held as two entries, by whatever path each came in
        # (a carried "Crawler Drakea" and a new "Drakea"): the same name with
        # a title added or dropped, or spelt one letter apart, is one person
        changed = True
        while changed:
            changed = False
            for a, b in itertools.combinations(sorted(self.known), 2):
                if frozenset((a, b)) in self.never or \
                        self.family(self.names(a), self.who(a), self.names(b), self.who(b)):
                    continue
                said = self.listed(self.names(a), self.names(b))
                if said is False:
                    continue
                if any(self.retitled(a, x) for x in self.names(b)) or (said and any(
                        variant(x, y) for x in self.names(a) for y in self.names(b))):
                    keep = self._join(a, b)
                    self.log.append("joined at the end (same name): %s + %s -> %s" % (a, b, keep))
                    changed = True
                    break
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
        # a fuller form of the same name ("Bianca" -> "Bianca Del Ciao") is
        # no reveal: the person keeps the name the reader met them by
        # Each pair that are forms of one name merge, even when the person
        # also has a name that is not ("Drakea" / "Crawler Drakea" stayed
        # two rows at one spot because a third, revealed name was there too)
        for g, ps in list(by_group.items()):
            if len(ps) < 2:
                continue
            ps.sort(key=lambda q: min((r[0], r[2]) for r in q.rows))
            kept: list = []
            for q in ps:
                into = next((k for k in kept if variant(k.name, q.name)), None)
                if into is None:
                    kept.append(q)
                    continue
                into.rows.extend(q.rows)
                into.rows.sort(key=lambda r: (r[0], r[2]))
                into.forms = sorted(set(into.forms) | set(q.forms), key=len, reverse=True)
                people = {k: v for k, v in people.items() if v is not q}
            by_group[g] = kept
        for ps in by_group.values():
            if len(ps) > 1:
                for p in ps:
                    others = {q.name for q in ps if q is not p}
                    p.forms = sorted({f for f in p.forms if f not in others} | {p.name},
                                     key=len, reverse=True)
        shown_people = list(people.values())
        self.self_check(shown_people)
        # what the scorecard calls "twice": say where each one came from
        for a, b in itertools.combinations(shown_people, 2):
            if twice(a.name, b.name):
                ga = next((g for (g, _s), v in people.items() if v is a), "?")
                gb = next((g for (g, _s), v in people.items() if v is b), "?")
                self.log.append("shown twice: %s [entry %s: %s] | %s [entry %s: %s]%s"
                                % (a.name, ga, ", ".join(sorted(group.get(ga, ()))),
                                   b.name, gb, ", ".join(sorted(group.get(gb, ()))),
                                   " (carried)" if ga in self.carried or gb in self.carried
                                   else ""))
        for p in shown_people:
            p.mentions = C._mentions(self.docs, p.forms)
            p.spoke = C._first_spoken(self.docs, p.forms)
        # a name the book never prints is not someone the reader meets
        gone = [p.name for p in shown_people if not p.mentions and p.name != self.lead]
        if gone:
            self.log.append("never named in the text, left out: %s" % ", ".join(sorted(gone)))
        shown_people = [p for p in shown_people if p.mentions or p.name == self.lead]
        rows = C._rows(shown_people, self.lead)
        report = ["%d people written; %d questions (%d parts, %d same-person checks); "
                  "%d changes kept, %d turned down (%d as someone else's); %d first descriptions changed"
                  % (len(shown_people), sum(self.calls.values()), self.calls["step"],
                     self.calls["guard"], self.stats["changes kept"],
                     self.stats["changes turned down"], self.stats["someone else's"],
                     self.stats["first descriptions changed"])]
        ev = {k: v for k, v in self.stats.items() if k.startswith("events:")}
        if self.calls["guide"] or self.calls["decide"]:
            report.append("ledger: %d guide, %d events, %d looked again, %d decide calls"
                          % (self.calls["guide"], self.calls["events"], self.calls["cover"],
                             self.calls["decide"]))
        if self.calls["rewrite"] or ev:
            report.append("events: %d entries rewritten of %d tries; %s" % (
                self.stats["entries rewritten"], self.calls["rewrite"],
                ", ".join("%s %d" % (k[8:], v) for k, v in sorted(ev.items())) or "none left out"))
        if self.notpeople:
            report.append("not people: " + ", ".join(sorted(self.notpeople)[:60]))
        if os.environ.get("CAST_HISTORY"):
            report.extend(self.log)
        return rows, report, C.seen_rows(shown_people, self.lead)


class _Records(_Run):
    """The who's who as one record per person (recaps.cast_events): each
    part is read for lasting events first and only then for whom they
    happened to; an event is kept only when the text shows it happening,
    it lasts, and its quote is about that person; and each kept event
    rewrites the whole entry, so the first sentence never goes stale
    ("guards the Tutorial Guild door" six books on)."""

    def step_prompt(self, manifest, text, ctext, utext, unl):
        return STEP_EVENTS.format(known=manifest, text=text, check="\n", unlisted=utext,
                                  and_unlisted=", including each UNLISTED name" if unl else "")

    def take(self, got, order, seg, text, ptext):
        given: dict = {}
        evs = [e for e in got.get("events") or [] if isinstance(e, dict)]

        def at(e):
            q = squash(str(e.get("quote") or ""))[:40]
            i = ptext.find(q) if q else -1
            return i if i >= 0 else len(ptext)
        # in the order the text tells them, so a person's last entry in a
        # part is their latest one (Imani's skulls came after her squad died)
        # an event that changes two people goes to each ("Paz Lo slays
        # Ysalte" is news for Ysalte too)
        both = []
        for e in sorted(evs, key=at):
            both.append(e)
            also = str(e.get("also") or "").strip()
            if also and squash(also) not in ("none", "n a", "nobody", "no one", "") and \
                    squash(also) != squash(str(e.get("who") or "")):
                both.append(dict(e, who=also, also="", _also=True))
        for e in both:
            who = str(e.get("who") or "").strip()
            what = str(e.get("what") or "").strip()
            if "(" in who:
                # someone who only shares a listed name (a monster called Mordecai)
                self.stats["events: namesake"] += 1
                self.log.append("event left out, a namesake: %s | %s" % (who, what))
                continue
            k = self.owner(who)
            if k is False:
                # "Alpha Carl" (a card) is not Carl: a name with a word none
                # of the person's names has is someone else
                self.stats["events: namesake"] += 1
                self.log.append("event left out, another name: %s | %s" % (who, what))
                continue
            if not k:
                self.stats["events: nobody listed"] += 1
                continue
            happened = low(str(e.get("happened") or ""))
            lasting = low(str(e.get("lasting") or ""))
            why = ""
            if not happened.startswith("yes"):
                why = "not shown happening"
            elif not lasting.startswith("yes"):
                why = "not lasting (%s)" % (lasting or "no answer")
            elif not what:
                why = "no 'what'"
            elif PASSING_EVENT.search(what) and not BIG.search(what):
                why = "a passing thing"
            u = {"quote": e.get("quote"), "now": what, "event": e.get("kind") or "", "other": ""}
            if not why:
                why = self.verify(k, u, text, ptext, seg, subject=True)
            sq_what = squash(what)
            if not why and not e.get("_also") and len(sq_what.split()) >= 6 \
                    and given.get(sq_what, k) != k:
                why = "same change as %s's" % given[sq_what]
            if not why:
                given[sq_what] = k
            if why:
                self.stats["changes turned down"] += 1
                self.log.append("event turned down for %s: %s | %s | %s"
                                % (k, why, what, e.get("quote")))
                continue
            sq = squash(str(e.get("quote")))
            para = next((n for n, t in seg if sq[:40] in squash(t)), seg[0][0])
            self.keep(k, what, u, order, para, text)

    def keep(self, k, what, u, order, para, text):
        """A change that passed the code's checks: the model's two looks,
        then the entry is rewritten at once."""
        why = self.whose(k, what, u, text) or self.lasting(k, what, u, text)
        if why:
            self.stats["changes turned down"] += 1
            self.log.append("event turned down for %s: %s | %s | %s"
                            % (k, why, what, u.get("quote")))
            return
        self.stats["changes kept"] += 1
        self.known[k].setdefault("facts", []).append((order, para, what))
        self.rewrite(k, what)
        self.rows.append((order, para, k, self.who(k)))

    def owner(self, who):
        """The listed person an event's name is, None when no one, False
        when the name belongs to someone or something else: a name on the
        not-people list, or one with a word that none of the found
        person's names has ("Alpha Carl" for Carl)."""
        n = norm(who)
        if any(plain(n) == plain(x) for x in self.notpeople):
            return False
        k = self.find(n)
        if not k:
            return None
        if plain(n) in {plain(x) for x in self.names(k)}:
            return k
        words = set().union(*({w for w in low(x).split()} for x in self.names(k)))
        extra = [w for w in low(n).split() if w not in words and w not in STOPW
                 and w not in GENERIC and not re.match(RANKS, w + " ")]
        return False if extra else k

    def lasting(self, k, what, u, text):
        """One plain question about one event, apart from the long step
        answer (where "lasting: yes" let through Zev being called away and
        a quest Katia took): a doubt leaves it out."""
        q = str(u.get("quote") or "").strip()
        i = text.find(q[:40]) if q else -1
        if i < 0:
            i = text.lower().find(q[:40].lower()) if q else -1
        context = text[max(0, i - 700):i + len(q) + 700] if i >= 0 else q
        self.calls["lasting"] += 1
        try:
            r = self.ask(LASTING.format(context=context.strip(), name=k, what=what), SYSTEM,
                         lambda t: (t or "").strip().upper().startswith(("LASTING", "FOR A WHILE")))
        except Exception:                                    # noqa: BLE001
            r = ""
        first = r.strip().splitlines()[0] if r and r.strip() else "no answer"
        self.log.append("lasting %s | %s -> %s" % (k, what, first))
        if not first.upper().startswith("LASTING"):
            self.stats["events: for a while"] += 1
            return "for a while (model)"
        return ""

    def rewrite(self, k, what):
        """The whole entry again from the old one and the new fact. Kept only
        when it names no one the two do not; else the old way (first
        sentence + latest change)."""
        # always from who they were before this book's changes plus every
        # change since, never from the last rewrite: a chain of rewrites
        # gains and loses facts at each step
        rec = self.known[k]
        rec.setdefault("base", HEADER.sub("", self.who(k)))
        facts = rec.setdefault("since", [])
        facts.append(what)
        before = rec["base"]
        fact = "\n".join("- " + f for f in facts[-6:])
        self.calls["rewrite"] += 1
        try:
            r = self.ask(REWRITE.format(entry=before, fact=fact, name=k), SYSTEM,
                         lambda t: bool((t or "").strip()))
        except Exception:                                    # noqa: BLE001
            r = ""
        r = re.sub(r"^\W*(?:new entry|entry)\s*:\s*", "", (r or "").strip(), flags=re.I)
        r = HEADER.sub("", r)
        r = re.sub(r"^%s\s*:\s*" % re.escape(k), "", r).strip().strip('"').strip()
        src = squash(before + " " + fact + " " + " ".join(self.names(k)))
        odd = [w for w in re.findall(r"(?<![.!?]\s)(?<!^)\b([A-Z][a-z'’\-]{2,})", r)
               if squash(w) not in src and w not in NOT_NAMES]
        if not r or odd or len(r) > 320:
            self.log.append("rewrite not used for %s (%s): %s" % (k, "names " + ", ".join(odd)
                            if odd else "empty or long", r[:120]))
            self.known[k]["change"] = sentence(what, CHANGE_WORDS)
            return
        self.stats["entries rewritten"] += 1
        self.log.append("rewrite %s | %s -> %s" % (k, what, r))
        self.known[k]["first"], self.known[k]["change"] = r, ""


# ----------------------------------------------------------- the ledger
#
# recaps.cast_ledger: the same records, asked for in small steps the PC's
# model can do one at a time, and decided once the whole book is read.
#   1. a reading guide: how this book is told, from its opening;
#   2. per part, one question for the names and one for the lasting events,
#      each with worked examples (made up, not from any real book);
#   3. code checks every event's quote and whose name it is, and logs it;
#   4. anyone the book keeps naming who has no logged event is looked at
#      again (code makes sure nobody stays at their first sighting);
#   5. at the end, each person's whole log goes to the model at once:
#      KEEP or DROP each change, seeing what came after it; then the kept
#      ones are written in book order, each entry from earlier facts only.

STEP_NAMES = STEP.split("Return JSON only")[0] + """Return JSON only, in this shape (the quote that names them first):
{{"new": [{{"evidence": "...", "name": "...", "type": "...", "one": "yes or no", "aliases": ["..."], "who": "..."}}]}}

""" + STEP.split("Return JSON only")[1].split("\n\n", 1)[1].split("Rules for \"updates\"")[0].rstrip()

GUIDE = """The opening of a novel:
<<<
{text}
>>>

Answer about how this book is told, from the text above only. Return JSON only, in this shape:
{{"narrator": "...", "first_person": "yes or no", "system_messages": "yes or no", "you_in_messages": "...", "changes_form": "yes or no", "shared_names": "yes or no"}}
- "narrator": the name of the person telling the story, or "" if it is told from outside.
- "first_person": "yes" if the narrator says "I".
- "system_messages": "yes" if the story shows game or system notices, screens or messages.
- "you_in_messages": the name of the person those messages call "you", or "".
- "changes_form": "yes" if people in this world can take a new body, form, species or class.
- "shared_names": "yes" if monsters, cards, items, ranks or titles here carry a person's name."""

EXAMPLES = """EXAMPLE 1
TEXT: Notice: Crawler Vex has been granted the class Ember Monk. A goblin chieftain, also called Vex, laughed at him before Bruno crushed it. Vex was knocked flat but stood up a minute later.
ANSWER: {"events": [{"quote": "Crawler Vex has been granted the class Ember Monk", "who": "Vex", "also": "", "what": "Vex takes the class Ember Monk.", "happened": "yes"},
 {"quote": "A goblin chieftain, also called Vex", "who": "Vex (the goblin chieftain)", "also": "", "what": "A goblin chieftain who shares Vex's name is killed by Bruno.", "happened": "yes"}]}
(Being knocked flat is a moment, not an event. The goblin only shares a name, so its kind goes in brackets.)

EXAMPLE 2
TEXT: Everyone in the village said the miller had poisoned his wife. Inspector Dray proved it was the miller's brother, Aldo, and arrested him that night. The headmistress named Hollis captain of the Ravens.
ANSWER: {"events": [{"quote": "proved it was the miller's brother, Aldo, and arrested him", "who": "Aldo", "also": "", "what": "Aldo is shown to be the poisoner and is arrested.", "happened": "yes"},
 {"quote": "named Hollis captain of the Ravens", "who": "Hollis", "also": "", "what": "Hollis becomes captain of the Ravens.", "happened": "yes"}]}
(What the village said about the miller is a rumour, not an event.)

EXAMPLE 3
TEXT: The old queen fell beneath the knight's blade. Sir Tamsin had slain Queen Orla, and the crown passed to her daughter, Brin. Brin swore she would one day take back the eastern hills.
ANSWER: {"events": [{"quote": "Sir Tamsin had slain Queen Orla", "who": "Sir Tamsin", "also": "Queen Orla", "what": "Sir Tamsin kills Queen Orla.", "happened": "yes"},
 {"quote": "the crown passed to her daughter, Brin", "who": "Brin", "also": "", "what": "Brin becomes queen after her mother's death.", "happened": "yes"}]}
(Queen Orla is changed too, so she is "also". Brin's oath is a plan, not an event.)"""

EVENTS = """{about}NEW TEXT:
<<<
{text}
>>>

What happens in the NEW TEXT that changes someone for good? They die or come back, are born, join or leave a group or side, get or lose a job, rank, title or class, take a new name, body, form or species, lose a body part, are marked or cursed for good, begin or end a lasting bond (marry, break up, become enemies), or are shown to be someone else or someone's relative.{only}
Not events: a fight, a trip, a plan, an oath, a mood, a talk, being knocked out, asleep, frozen or held for a while, being sent away or called away, a level, skill, spell or item, a rumour.
- "who": the one individual it happens to, by the name the text uses. Someone who only shares a person's name gets their kind in brackets: "Vex (the goblin chieftain)".
- "also": a second individual the same event changes for good, else "".
- "what": ONE sentence (under 16 words) naming the person.
- "happened": "yes" only if the text shows it happening, not only says it might, will, or was rumoured to.
- "quote": a short exact quote (under 25 words) from the NEW TEXT that shows it.
If nothing lasting happens, answer {{"events": []}}.

{examples}

First find the exact words that show each change, then say whom it happened to.
Return JSON only, in this shape:
{{"events": [{{"quote": "...", "who": "...", "also": "...", "what": "...", "happened": "yes or no"}}]}}"""

DECIDE = """{about}A spoiler-free character list has this entry for {name} from before these pages:
{entry}

Possible changes for {name}, in the order the book tells them, each with its passage:
{items}

For each one, answer KEEP if the passage shows it happening to {name} and it lasts: their life or death, body or form, name, title, role, job, rank, class, side or faith, a bond begun or ended, or a reveal of who they are. It counts even when someone else does it to {name} (kills, transforms, marks, curses, hires or marries them).
Answer DROP only if it is about another individual (even one with the same name), or only a moment, a plan, a rumour, an item, or something that wears off, or a later item plainly undoes it.
For each number, first give a short reason (under 20 words) from the passage, then the answer.
Return JSON only, one entry per number, like {{"1": {{"why": "...", "answer": "KEEP"}}, "2": {{"why": "...", "answer": "DROP"}}}}."""

COVER_MIN, COVER_MAX, DECIDE_BATCH = 12, 80, 8

# The answer shapes, sent to servers that can hold the model to them
# (llama.cpp turns a schema into a grammar): always well-formed JSON, yes/no
# and KEEP/DROP as fixed choices, and the fields in the order the model
# should think in - the quote before the claim, the reason before the
# verdict. Strings are bounded so an answer cannot run on.


def _str(n):
    return {"type": "string", "maxLength": n}


YESNO = {"type": "string", "enum": ["yes", "no"]}
GUIDE_SCHEMA = {"type": "object", "properties": {
    "narrator": _str(60), "first_person": YESNO, "system_messages": YESNO,
    "you_in_messages": _str(60), "changes_form": YESNO, "shared_names": YESNO},
    "required": ["narrator", "first_person", "system_messages", "you_in_messages",
                 "changes_form", "shared_names"]}
NAMES_SCHEMA = {"type": "object", "properties": {"new": {
    "type": "array", "maxItems": 25, "items": {"type": "object", "properties": {
        "evidence": _str(140), "name": _str(60),
        "type": {"type": "string", "enum": ["person", "creature", "animal", "ai", "god",
                                            "monster", "company", "place", "item", "group",
                                            "kind", "title", "reference"]},
        "one": YESNO, "aliases": {"type": "array", "maxItems": 6, "items": _str(60)},
        "who": _str(160)},
        "required": ["evidence", "name", "type", "one", "aliases", "who"]}}},
    "required": ["new"]}
EVENTS_SCHEMA = {"type": "object", "properties": {"events": {
    "type": "array", "maxItems": 12, "items": {"type": "object", "properties": {
        "quote": _str(160), "who": _str(80), "also": _str(80), "what": _str(160),
        "happened": YESNO},
        "required": ["quote", "who", "also", "what", "happened"]}}},
    "required": ["events"]}


def decide_schema(n):
    one = {"type": "object", "properties": {
        "why": _str(140), "answer": {"type": "string", "enum": ["KEEP", "DROP"]}},
        "required": ["why", "answer"]}
    return {"type": "object", "properties": {str(i + 1): one for i in range(n)},
            "required": [str(i + 1) for i in range(n)]}


def _usable_events(t: str) -> bool:
    return bool(re.search(r"\{.*\}", t or "", re.S))


class _Ledger(_Records):
    """recaps.cast_ledger: see the notes above EXAMPLES."""

    def ask_json(self, prompt, usable, schema):
        """Ask with the answer's shape when the model call takes one."""
        try:
            return self.ask(prompt, SYSTEM, usable, schema=schema)
        except TypeError:
            return self.ask(prompt, SYSTEM, usable)

    def go(self):
        ctx = self.ctx
        self.about = self.reading_guide()
        self.log.append("main character: %s" % (", ".join(sorted(self.hero)) or "none found"))
        self.cands = collections.defaultdict(list)
        total = len(self.parts)
        for i, (order, seg) in enumerate(self.parts):
            ctx.report("who's who: part %d/%d" % (i + 1, total))
            self.part_no = i
            self.one_part(i, order, seg)
        ctx.report("who's who: looking again at people with no changes")
        self.cover()
        ctx.report("who's who: deciding each person's changes")
        self.decide()
        return self.finish()

    # -- 1. how this book is told ------------------------------------------

    def reading_guide(self):
        opening = ""
        for _o, seg in self.parts:
            opening += "\n".join(t for _n, t in seg) + "\n"
            if len(opening) >= PASSAGE:
                break
        self.calls["guide"] += 1
        try:
            got = parse(self.ask_json(GUIDE.format(text=opening[:PASSAGE + 4000]), _usable_step,
                                      GUIDE_SCHEMA))
        except Exception:                                    # noqa: BLE001
            got = {}

        def yes(k):
            return low(str(got.get(k) or "")).startswith("yes")
        narr = norm(str(got.get("narrator") or "").strip())
        you = norm(str(got.get("you_in_messages") or "").strip())
        # the guide only adds a narrator when the book's own count found none
        if narr and proper(narr) and not self.hero and yes("first_person"):
            self.hero = {narr: NARRATOR}
            self.lead = narr
        lines = []
        lead = self.lead or narr
        if yes("first_person") and lead:
            lines.append("It is told in the first person by %s: \"I\" is %s." % (lead, lead))
        if yes("system_messages"):
            lines.append("It shows game or system messages%s." % (
                "; when they say \"you\" they mean %s" % (you or lead) if (you or lead) else ""))
        if yes("changes_form"):
            lines.append("People can take a new body, form, species or class; that does not "
                         "make them someone else.")
        if yes("shared_names"):
            lines.append("Monsters, cards, items, ranks or titles can carry a person's name; "
                         "those are not that person.")
        self.log.append("reading guide: %s" % (" ".join(lines) or "nothing to note"))
        return ("ABOUT THIS BOOK: " + " ".join(lines) + "\n\n") if lines else ""

    # -- 2. names, then events -------------------------------------------

    def ask_step(self, prompt):
        return self.ask_json(prompt, _usable_step, NAMES_SCHEMA)

    def step_prompt(self, manifest, text, ctext, utext, unl):
        return self.about + STEP_NAMES.format(
            known=manifest, text=text, check="\n", unlisted=utext,
            and_unlisted=", including each UNLISTED name" if unl else "")

    def events_for(self, text, only=""):
        self.calls["events"] += 1
        try:
            got = parse(self.ask_json(EVENTS.format(about=self.about, text=text, examples=EXAMPLES,
                                                    only=only), _usable_events, EVENTS_SCHEMA))
        except Exception:                                    # noqa: BLE001
            return []
        # whether it lasts is decided at the end of the book, not here
        return [dict(e, lasting="yes") for e in got.get("events") or [] if isinstance(e, dict)]

    def take(self, got, order, seg, text, ptext):
        super().take({"events": self.events_for(text)}, order, seg, text, ptext)

    # -- 3. log, do not decide yet -----------------------------------------

    def keep(self, k, what, u, order, para, text):
        q = str(u.get("quote") or "").strip()
        i = text.find(q[:40]) if q else -1
        if i < 0:
            i = text.lower().find(q[:40].lower()) if q else -1
        context = text[max(0, i - 600):i + len(q) + 400] if i >= 0 else q
        if any(c["what"] == what and c["order"] == order for c in self.cands[k]):
            return
        self.cands[k].append(dict(order=order, para=para, what=what, quote=q,
                                  context=re.sub(r"\s+", " ", context).strip()))
        self.stats["events: logged"] += 1
        self.log.append("logged %s | %s | %s" % (k, what, q))

    # -- 4. nobody stays at their first sighting ------------------------------

    def cover(self):
        squashed = [squash("\n".join(t for _n, t in seg)) for _o, seg in self.parts]
        named = {k: [self.count(k, p) for p in squashed] for k in self.known}
        todo = sorted((k for k, n in named.items() if sum(n) >= COVER_MIN and not self.cands[k]),
                      key=lambda k: -sum(named[k]))[:COVER_MAX]
        for k in todo:
            # the part that names them most, the later one on a tie: where a
            # change is likeliest to show
            i = max(range(len(self.parts)), key=lambda j: (named[k][j], j))
            order, seg = self.parts[i]
            text = "\n".join(t for _n, t in seg)
            self.calls["cover"] += 1
            self.stats["events: looked at again"] += 1
            evs = [e for e in self.events_for(
                text, only="\nLook only for lasting changes to %s." % k)
                if self.owner(str(e.get("who") or "")) == k
                or self.owner(str(e.get("also") or "")) == k]
            self.log.append("looked again at %s in part %d: %d events" % (k, i + 1, len(evs)))
            if evs:
                _Records.take(self, {"events": evs}, order, seg, text, squashed[i])

    # -- 5. decide with the whole log, then write in book order ---------------

    def decide(self):
        for k in sorted(self.cands):
            cs = sorted(self.cands[k], key=lambda c: (c["order"], c["para"]))
            if not cs:
                continue
            verdict = {}
            for start in range(0, len(cs), DECIDE_BATCH):
                batch = cs[start:start + DECIDE_BATCH]
                items = "\n".join('%d. %s\n   Passage: "%s"' % (n + 1, c["what"], c["context"])
                                  for n, c in enumerate(batch))
                self.calls["decide"] += 1
                try:
                    got = parse(self.ask_json(DECIDE.format(about=self.about, name=k,
                                                            entry=HEADER.sub("", self.who(k)),
                                                            items=items),
                                              _usable_events, decide_schema(len(batch))))
                except Exception:                            # noqa: BLE001
                    got = {}
                for n, c in enumerate(batch):
                    a = got.get(str(n + 1)) or ""
                    if isinstance(a, dict):
                        self.log.append("decide why %s | %s" % (k, a.get("why", "")))
                        a = a.get("answer") or ""
                    a = str(a).strip().upper()
                    verdict[id(c)] = a.startswith("KEEP")
                    self.log.append("decide %s | %s -> %s" % (k, c["what"], a or "no answer"))
            for c in cs:
                if not verdict.get(id(c)):
                    self.stats["changes turned down"] += 1
                    continue
                self.stats["changes kept"] += 1
                self.known[k].setdefault("facts", []).append((c["order"], c["para"], c["what"]))
                self.rewrite(k, c["what"])
                self.rows.append((c["order"], c["para"], k, self.who(k)))
