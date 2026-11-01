#!/usr/bin/env python3
"""Deterministic scorer for epubkit cast reports (*.cast.txt) against a book's answer key.

usage: score.py REPORT KEY [--rules dcc5|hp1] [--book EPUB] [-v]

Per answer-key person the FINAL row (latest order:para across every row name that
matches the person) is graded:
  missing  no row
  wrong    final text matches a WRONG pattern for that person
  thin     main/supporting person whose final text has none of their NEED words,
           or any person whose final text, minus sentences with a VAGUE stock phrase,
           is under 6 words (unless it hits a NEED word)
  right    otherwise
Also counted: junk rows (names not in the key that are on the JUNK list), unkeyed real
people (EXTRA list), unclassified names (neither; extend the lists), duplicate people
(one key person written under more than one row name), spoilers (a row stating a FACT
before the chapter it happens in) and early rows (a row placed before the key's
"chapter first named"). Spoiler/early checks need positions in the key (DCC5 only).
Everything is sorted; same inputs always give the same output.
"""
import argparse, csv, re, sys
from pathlib import Path

ROW = re.compile(r"^(\d+):(\d+)\t([^\t]+)\t(\w+)\t(\d+)\t(.*)")
TITLES = r"^(mr|mrs|ms|miss|madam|madame|professor|prof|sir|uncle|aunt|lord|the|dr|god|goddess|hunter|crawler)\s+"
VAGUE = [r"not otherwise described", r"calls (him|her|them) by name", r"greets (him|her|them) by name"]
MIN_WORDS = 6

RULES = {
    "dcc5": dict(
        need={
            "Carl": "crawler|narrator|coast guard", "Donut": r"\bcat\b",
            "Katia": "shapeshift|meld|change shape|guild", "Mordecai": "guide|manager",
            "Signet": "naiad|summoner|tattoo", "Chris": "lava|rock|igneous",
            "Mongo": "allosaurus|dinosaur|pet", "Orren": "liaison|valtay|gondii",
            "Quasar": "lawyer|advocate", "Bomo": "cretin|rock monster|mercenar|guard",
            "Sledge": "cretin|rock|mercenar|bodyguard", "Vrah": "mantis",
            "Miriam": "shepherd|vampire", "Prepotente": "goat|caprid",
            "Zev": r"kua-tin|\bPR\b|handler|liaison|admin", "Odette": "host|show",
            "Lucia": "lajabless|inquisitor|#2|mayor",
            "Dmitri": "nodling|ogre|two-headed|visionary|maxim",
            "Maxim": "nodling|ogre|twin|dmitri", "Elle": "ice|tundra|blizzard|elderly",
            "Imani": "guild|healer|buff|safehome", "Eva": r"nagini|snake|player killer|\bPK\b",
            "Kiwi": "raptor|mongo|bear|tina", "Big Tina": "allosaurus|dinosaur|boss",
            "Samantha": "head|doll|psamathe|deity|goddess", "Beatrice": r"\bex\b|ex-|girlfriend|owner",
            "Areson": "ogre", "Clint": "were|recon",
            "Imogen": "high elf|queen|signet|half-sister|elf", "Circe": "mantis|hive|vrah|queen",
            "Bautista": "tiger|swashbuckler|lead|team|crew|katia",
            "Louis": "exterminat|twister|juice box|driver", "Firas": "hammersmith|britney",
            "Britney": "ukrain|barbarian|firas|guitar", "Florin": "crocodil|shotgun",
            "Edict": "mantis", "Cici": "rottweiler|dog", "Gustavo": "rottweiler|dog|lucia",
            "Ferdinand": "cat|familiar|imogen", "Diwata": "god|deity|squirrel",
            "D'Nadia": "saccathian|sponsor|empress|prism",
            "Bianca": "goat|familiar|hellspawn|mount", "Li Na": "changbi|smoke|li jun|katia|eva",
        },
        wrong={
            "Mordecai": r"two-headed|\bAI\b", "Katia": r"rejoin|\bhuman\b", "Florin": r"\bhuman\b",
            "Li Na": "sister of zhang", "Diwata": "actually circe took|under the control of",
            "Circe": "mother of donut", "Bautista": "brother of grace", "Sledge": r"\bdied\b|\bdead\b",
        },
        # the person's own death; "saved Carl from death" must not count
        facts=[("Miriam", r"\b(dies|died|dying|is dead|now dead|was killed|is killed)\b", 47),
               ("Clint", r"\b(dies|died|dying|is dead|now dead|was killed|is killed)\b", 26)],
        # order -> chapter, from recaps._documents labels (checked against the r15 book)
        chapters=[(10, 24, 1), (27, 40, 16), (43, 68, 30), (71, 78, 56), (80, 91, 64), (92, 92, 76)],
        aliases={},
        junk="""daughter|borant|meadow lark|murderer|sepsis whore|sultan|valtay corporation|rottweiler|ursine|dreadnought|
            npcs|snitch|majesty|only true blood|queen of all that is|queen of all that will|skull empire|
            predator|shepherd|popov|judge|rambo|jaxbrin|vol|plenty|don""",
        extra="susan|yolanda martinez|apollon|lika|brandon an|jaygee",
    ),
    "hp1": dict(
        need={
            "Harry": "wizard|survived|scar|seeker|gryffindor|orphan", "Ron": "weasley|friend",
            "Hermione": "muggle|book|friend|witch", "Dumbledore": "headmaster",
            "Hagrid": "keeper|keys|grounds", "Snape": "potions",
            "Quirrell": "teacher|defen[cs]e|stammer|turban",
            "Voldemort": "dark wizard|bad wizard|killed|parents",
            "Draco": "slytherin|rival|pale|crabbe|goyle",
            "Neville": "gryffindor|forgetful|clumsy|toad|trevor",
            "McGonagall": r"transfiguration|gryffindor|professor|\bcat\b|tabby",
            "Vernon": "uncle|grunnings|drills", "Petunia": "aunt|lily|sister",
            "Dudley": "cousin|son", "Fred": "twin|prank|beater", "George": "twin|prank|beater",
            "Percy": "prefect", "Molly": "mother|mum|platform|jumper",
            "Wood": "captain|keeper|quidditch", "Filch": "caretaker", "Firenze": "centaur",
            "Flamel": "alchem|stone", "Lily": "mother|killed", "James": "father|killed",
            "Fluffy": "three-headed|dog", "Norbert": "dragon",
        },
        wrong={"Molly": "staying with her family"},
        facts=[], chapters=[(6, 22, 1)],
        aliases={"mrs dursley": "Petunia", "ronald weasley": "Ron"},
        junk="don|potions|vol|house|smeltings|apothecary",
        extra="""susan|madam malkin|malkin|morgana|binns|fang|fat lady|adrian pucey|pucey|
            madam pince|pince|perenelle""",
    ),
    "hp2": dict(
        need={
            "Harry": "wizard|scar|seeker|gryffindor|parsel|survived", "Ron": "weasley|friend",
            "Hermione": "muggle|book|friend|witch|clever|gryffindor", "Dumbledore": "headmaster",
            "Hagrid": "keeper|keys|grounds|gamekeeper|expelled|azkaban",
            "Lockhart": r"defen[cs]e|teacher|author|book|celebrit|famous|fraud|memory",
            "Tom Riddle": "diary|memory|heir|student|voldemort|prefect",
            "Ginny": "weasley|sister|youngest|daughter|diary|chamber",
            "Voldemort": "dark wizard|dark lord|killed|parents|riddle",
            "Dobby": r"\belf\b|malfoy|warn", "Lucius": "father|malfoy|governor|draco|ministry",
            "Draco": "slytherin|rival|seeker|crabbe|goyle", "Snape": "potions",
            "McGonagall": r"transfiguration|gryffindor|deputy|professor",
            "Myrtle": "ghost|bathroom|toilet|girls", "basilisk": "snake|serpent|monster|chamber",
            "Aragog": "spider|acromantula", "Fawkes": "phoenix",
            "Molly": "mother|mum|howler", "Arthur": "father|ministry|muggle|car",
            "Fred": "twin|brother|beater|prank", "George": "twin|brother|beater|prank",
            "Percy": "prefect|brother", "Vernon": "uncle|drills|grunnings|mason",
            "Petunia": "aunt", "Dudley": "cousin|son", "Colin": "first-year|first year|camera|photo|petrif|fan",
            "Justin": "hufflepuff|petrif|muggle", "Nick": "ghost|deathday|headless",
            "Filch": "caretaker|squib",
        },
        wrong={},
        facts=[("Tom Riddle", r"voldemort|you-know-who|dark lord|he-who-must|heir of slytherin|slytherin's heir", 17),
               ("Voldemort", r"riddle|diary|heir of slytherin|slytherin's heir", 17),
               ("Ginny", r"open(ed|s|ing)? the chamber|possess|controll|bewitch|riddle's diary|the diary|wr(ote|ites|iting) (in|to)", 17),
               ("Ginny", r"taken into|carried (off|into)|in the chamber|taken by", 16),
               ("basilisk", r".", 16),
               ("Lockhart", r"fraud|fake|stole|took credit|memory charm|lost (his )?memory|obliviat|liar", 16),
               ("Myrtle", r"basilisk|killed by|\beyes\b|chamber", 16),
               ("Hagrid", r"innocent|framed|cleared|wrongly", 17),
               ("Dobby", r"\bfree\b|freed|\bsock", 18),
               ("Lucius", r"diary|planted|slipped|removed|sacked|dismissed", 18),
               ("Harry", r"parsel", 11),
               ("Percy", r"penelope|girlfriend", 18)],
        # order -> chapter, from recaps._documents labels; order 31 is the HP 3 sample chapter
        chapters=[(6, 23, 1)],
        aliases={"mrs dursley": "Petunia", "ronald weasley": "Ron", "ronald": "Ron",
                 "he who must not be named": "Lord Voldemort", "m riddle": "Tom Riddle"},
        junk="don|potions|vol|house|apothecary|ministry of magic|muggle|squib|heir of slytherin|heir",
        extra="angelina|angelina johnson|bloody baron|fat friar|madam pince|pince|katie bell|alicia spinnet|lavender brown|parvati patil|grey lady",
    ),
}


DEATH = r"\b(dies|died|dying|is dead|now dead|was killed|is killed)\b"
RULES["pj6"] = dict(
    need={
        "Percy": r"poseidon|demigod|narrator|son of|letter|recommend|college|universit",
        "Annabeth": r"athena|girlfriend|daughter", "Grover": r"satyr|friend|goat",
        "Ganymede": r"cup|chalice", "Iris": r"rainbow|messag|goddess|cupbearer",
        "Hebe": r"youth|goddess|cupbearer|jeebies", "Geras": r"chalice|cup|gary|old age",
        "Zeus": r"king|god|sky|brunch", "Poseidon": r"father|dad|sea|god",
        "Paul": r"stepdad|stepfather|step-father", "Sally": r"mom|mother",
        "Blanche": r"iris|photo|camp|daughter|colou?r", "Elisson": r"river",
        "Athena": r"mother|mom|goddess|wisdom", "Rhea": r"titan|mother|grand|queen",
        "Lucius": r"lion", "Juniper": r"girlfriend|dryad|grover", "Eudora": r"counsel",
        "Li'l Killer": r"chick|chicken|bird|bit", "Naomi": r"kitchen|palace|maron|pastr",
        "Chiron": r"camp|director|teacher|centaur",
    },
    wrong={"Geras": r"hebe stole|iris stole", "Iris": r"\bstole\b", "Hebe": r"\bstole\b"},
    facts=[("Geras", r"geras|old age|\bgod\b|goddess", 25),
           # the challenge (ch 25) is not the outcome; Percy wins by hugging him in ch 27
           ("Geras", r"\b(beat|beats|beaten|defeat\w*|won|wins|hug\w*)\b", 27)],
    chapters=[(5, 39, 1)],
    aliases={"old age": "Geras", "mr d": "Dionysus"},
    junk="mercedes|new rome|new rome university|camp half-blood|olympus|hebe jeebies|fiji|csi|big three",
    extra="dionysus|artemis|hades|hephaestus|demeter|apollo|maron|tyson|frank|hazel|jason|piper|nico|will|rachel|thalia",
)
RULES["dcc4"] = dict(
    need={
        "Carl": r"crawler|narrator|human|bomb|party", "Donut": r"\bcat\b",
        "Katia": r"shapeshift|scout|crawler|party|guild", "Mordecai": r"guide|potion|manager",
        "Mongo": r"dinosaur|pet|allosaurus|donut", "Gwen": r"crawler|team|lead|scout",
        "Elle": r"ice|elderly|older|imani|crawler", "Imani": r"crawler|lead|elle|heal|group",
        "Louis": r"exterminat|crawler|firas|juice box", "Firas": r"hammersmith|crawler|louis",
        "Chris": r"crawler|throne|meadow lark|imani", "Henrik": r"npc|local|gnome|wynne|god|spell",
        "Wynne": r"gnome|mechanic|kane|prison|healer", "Loita": r"handler|\bpr\b|kua-tin|zev|liaison",
        "Zev": r"handler|\bpr\b|kua-tin|liaison", "Psamathe": r"deity|goddess|god|banish|nothing|doll|yarilo",
        "Quetzalcoatlus": r"wife|undead|flesh|temple|god", "Emberus": r"\bgod\b|fire",
        "Orthrus": r"dog|hound|nothing|emberus", "Ghazi": r"mage|sand|elemental|gate",
        "Vadim": r"crawler|surgeon|water", "Britney": r"crawler|vadim|water",
        "Tran": r"crawler|metal|gwen|valve", "Maggie": r"crawler|potion",
    },
    wrong={"Psamathe": r"\byarilo is\b"},
    facts=[("Psamathe", r"samantha|join|companion|party|donut", 34),
           ("Maggie", DEATH, 34),
           ("Henrik", DEATH, 26),  # ch26 first says he is dead; the ch11 body was Svern
           ("Orthrus", r"emberus|let out|released|nothing", 28)],
    chapters=[(10, 18, 1), (20, 26, 10), (28, 33, 17), (35, 47, 23)],
    aliases={"princess donut": "Donut", "commandant kane": "Commandant Kane"},
    junk="""borant|valtay|bactrian|bactrians|dromedarian|dromedarians|syndicate|skull empire|feral gods|
        desperado club|hump town|larracos|anser|necropolis|npc|npcs|crawlers|wasteland|nothing|ai|veriluxx|
        hunting grounds|club vanquisher|meadow lark|mad dune|grull|chariot|gate|quest|achievement""",
    extra="hellik|taranis|yarilo|magnificent troy|troy|signet|clint|dmitri|maxim|kiwi",
)


def light(s):
    s = s.lower().replace("’", "'").replace(".", "").strip()
    return re.sub(r"\s+", " ", s)


def strip_titles(s):
    while True:
        t = re.sub(TITLES, "", s)
        if t == s:
            return s
        s = t


def substance(text):
    """The text minus any sentence carrying a VAGUE stock phrase."""
    sents = re.split(r"(?<=[.!?])\s+", text)
    return " ".join(x for x in sents if not any(re.search(v, x, re.I) for v in VAGUE))


def words(s):
    return set(re.findall(r"[a-z0-9'-]+", s))


def load_key(path):
    people = []
    for r in csv.DictReader(open(path, encoding="utf-8"), delimiter="\t"):
        forms = [r["name"]] + [x.strip() for x in (r.get("other names") or "").split(";") if x.strip()]
        first = (r.get("chapter first named") or "").strip()
        people.append(dict(name=r["name"], forms=forms, tier=r["importance"].strip().lower(),
                           first=int(first) if first.isdigit() else None))
    return people


def load_report(path):
    rows, renamed = {}, {}
    for line in open(path, encoding="utf-8"):
        line = line.rstrip("\n")
        m = ROW.match(line)
        if m:
            rows.setdefault(m.group(3), []).append((int(m.group(1)), int(m.group(2)), m.group(6)))
        elif line.startswith("someone else's name:"):
            for a, b in re.findall(r"([^,(]+?)\s*\(([^)]+)\)", line.split(":", 1)[1]):
                renamed[a.strip()] = b.strip()
    return rows, renamed


TITLE_WORDS = {"princess", "prince", "queen", "king", "lady", "lord", "captain", "general", "sir", "miss", "mr",
               "mrs", "ms", "god", "goddess", "the", "commandant", "admiral", "duke", "duchess", "emperor", "empress"}


class Matcher:
    def __init__(self, people, aliases):
        self.people = people
        self.exact, self.stripped, self.tokens = {}, {}, {}
        for i, p in enumerate(people):
            for f in p["forms"]:
                self.exact.setdefault(light(f), i)
                self.stripped.setdefault(strip_titles(light(f)), i)
                for t in words(strip_titles(light(f))):
                    self.tokens.setdefault(t, set()).add(i)
        self.aliases = {light(a): b for a, b in aliases.items()}

    def __call__(self, name):
        # crawler-style " 2" suffix on a reused name is the same person
        n = re.sub(r"\s+\d+$", "", light(name))
        if n in self.exact:
            return self.exact[n]
        s = strip_titles(n)
        if s in self.stripped:
            return self.stripped[s]
        if n in self.aliases or s in self.aliases:
            return self(self.aliases.get(n) or self.aliases[s])
        ws = words(s)
        if len(ws) == 1:
            hit = self.tokens.get(next(iter(ws)), set())
            # a title on its own ("Princess", "God") names nobody in particular
            if len(hit) == 1 and next(iter(ws)) not in TITLE_WORDS:
                return next(iter(hit))
        # "Commissar Leon", "Lady Psamathe": try again without the leading word
        rest = s.split(None, 1)
        # but never down to a bare surname: "Peter Weasley" is not Mrs. Weasley
        if len(rest) == 2:
            r = light(rest[1])
            if r in self.exact or len(words(r)) > 1:
                return self(rest[1])
            hit = self.tokens.get(r, set())
            if len(hit) == 1 and r not in TITLE_WORDS:
                return next(iter(hit))
        return None


def listset(s):
    return {x.strip() for x in s.split("|") if x.strip()}


def chapter_of(order, spans):
    for lo, hi, ch in spans:
        if lo <= order <= hi:
            return ch + order - lo
    return None


def score(report, key, rules):
    R = RULES[rules]
    people = load_key(key)
    match = Matcher(people, R["aliases"])
    rows, renamed = load_report(report)

    def resolve(rule_name):
        i = match(rule_name)
        if i is None:
            sys.exit(f"rule name {rule_name!r} not in the key")
        return i
    need = {resolve(k): re.compile(v, re.I) for k, v in R["need"].items()}
    wrong = {resolve(k): re.compile(v, re.I) for k, v in R["wrong"].items()}
    facts = [(resolve(k), re.compile(v, re.I), ch) for k, v, ch in R["facts"]]
    junk, extra = listset(R["junk"]), listset(R["extra"])
    has_pos = any(p["first"] for p in people)

    names_of, junk_rows, extra_rows, unclassified = {}, [], [], []
    for n in sorted(rows):
        i = match(renamed.get(n, n))
        if i is not None:
            names_of.setdefault(i, []).append(n)
            continue
        s = strip_titles(light(n))
        (junk_rows if light(n) in junk or s in junk else
         extra_rows if light(n) in extra or s in extra else unclassified).append(n)

    out = []
    for i, p in enumerate(people):
        ns = names_of.get(i, [])
        allrows = sorted((o, para, t, n) for n in ns for o, para, t in rows[n])
        spoil, early = [], []
        if allrows:
            o, para, text, n = allrows[-1]
            if i in wrong and wrong[i].search(text):
                v = "wrong"
            elif p["tier"] != "minor" and i in need and not need[i].search(text):
                v = "thin"
            elif len(substance(text).split()) < MIN_WORDS and not (i in need and need[i].search(text)):
                v = "thin"
            else:
                v = "right"
            for o2, para2, t2, n2 in allrows:
                ch = chapter_of(o2, R["chapters"])
                if ch is None:
                    continue
                for fi, rx, fch in facts:
                    # the row's own name is not a fact about them (Old Age, Mad Dune Mage)
                    body = re.sub(r"(?i)\b(%s)\b" % "|".join(map(re.escape, n2.split())), " ", t2)
                    if fi == i and ch < fch and rx.search(body):
                        spoil.append(f"{o2}:{para2} ch{ch} {n2}")
                # early only if the row uses the name the key says arrives later;
                # an alias the book uses first (Miss Beatrice, Mad Dune Mage) is not early
                if has_pos and p["first"] and ch < p["first"] and re.search(
                        r"(?i)\b%s\b" % re.escape(p["name"].split()[0]), n2 + " " + t2):
                    early.append(f"{o2}:{para2} ch{ch}<{p['first']} {n2}")
        else:
            v, text, n = "missing", "", ""
        out.append(dict(name=p["name"], tier=p["tier"], verdict=v, names=ns, text=text,
                        spoil=spoil, early=early))
    return out, junk_rows, extra_rows, unclassified, has_pos


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("report")
    ap.add_argument("key")
    ap.add_argument("--rules", choices=sorted(RULES))
    ap.add_argument("-v", action="store_true", help="per-person lines")
    a = ap.parse_args()
    rules = a.rules or ("hp1" if "Harry Potter" in Path(a.report).name else "dcc5")
    out, junk, extra, unclassified, has_pos = score(a.report, a.key, rules)
    tiers = ["main", "supporting", "minor"]
    verdicts = ["right", "thin", "wrong", "missing"]
    print(f"report: {a.report}\nrules: {rules}")
    print("tier        " + " ".join(f"{v:>7}" for v in verdicts) + "   total")
    for t in tiers + ["all"]:
        sel = [x for x in out if t == "all" or x["tier"] == t]
        print(f"{t:<11} " + " ".join(f"{sum(x['verdict'] == v for x in sel):>7}" for v in verdicts)
              + f"   {len(sel):>5}")
    dups = [x for x in out if len(x["names"]) > 1]
    print(f"duplicates: {len(dups)}" + "".join(f"\n  {x['name']}: {', '.join(x['names'])}" for x in dups))
    print(f"junk rows: {len(junk)}  [{', '.join(junk)}]")
    print(f"unkeyed real people: {len(extra)}  [{', '.join(extra)}]")
    print(f"unclassified names: {len(unclassified)}  [{', '.join(unclassified)}]")
    if has_pos or RULES[rules]["facts"]:
        sp = [s for x in out for s in x["spoil"]]
        print(f"spoilers: {len(sp)}" + "".join(f"\n  {s}" for s in sp))
    if has_pos:
        ea = [s for x in out for s in x["early"]]
        print(f"early rows (before key's first chapter): {len(ea)}" + "".join(f"\n  {s}" for s in ea))
    elif not RULES[rules]["facts"]:
        print("spoilers: n/a (key has no positions)")
    if a.v:
        for x in out:
            print(f"{x['verdict']:<8} {x['tier']:<10} {x['name']} <- {', '.join(x['names']) or '-'}: {x['text']}")


if __name__ == "__main__":
    main()
