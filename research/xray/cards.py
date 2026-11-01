"""Step 1: quote cards (no model). Adds a card for each named person the voted
list has no entry for, built from the sentence of their first mention.

usage: python3 -I cards.py BOOK BASE.cast.txt OUT.cast.txt > cards.log   (BOOK: dcc5 | hp1)
"""
import collections, csv, difflib, glob, os, re, sys

H = os.path.expanduser("~")
sys.path.insert(0, H + "/cast-pilot/xray/epubkit/src")
from epubkit.stages.recaps import _documents  # noqa: E402

CP = H + "/cast-pilot/"
BOOKS = {
    "dcc5": dict(book=CP + "books-dcc5-r17/*.epub", wiki=CP + "series-dcc5-r17/*.names.tsv",
                 ent=CP + "booknlp/out/dcc5/dcc5.entities", runs="Dungeon*.cast.txt"),
    "hp1": dict(book=CP + "books-hp1-r17/*.epub", wiki=CP + "series-hp1-r17/*.names.tsv",
                ent=CP + "booknlp/out/hp1/hp1.entities", runs="Harry*.cast.txt"),
}
PERSONISH = {"person", "NPC", "crawler", "god", "deity", "monster", "boss", "character"}
TITLES = r"^(mr|mrs|ms|miss|madam|madame|professor|prof|sir|uncle|aunt|lord|the|dr|god|goddess|hunter|crawler)\s+"
MAX_WORDS = 30
PARTICLES = {"de", "da", "di", "du", "van", "von", "der", "den", "la", "le", "of", "the", "al", "bin", "ibn", "y"}


def low(s):
    s = s.lower().replace("’", "'").replace(".", "")
    s = re.sub(r"[_\-·]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    while True:
        t = re.sub(TITLES, "", s)
        if t == s:
            return s
        s = t


# --- koassistant-style duplicate rules (xray_dedup.lua findDuplicates) ---
def common_words(names):
    """A word that is a whole name or part of 3+ different names is a title or
    family name, not an identity."""
    c = collections.Counter(w for n in set(names) for w in set(n.split()))
    return {w for w, k in c.items() if k >= 3}


def same(a, b, common):
    """a, b already low(). Exact, or one's words are the start or end of the
    other's (3+ letters, never equal word counts), ignoring common words."""
    if a == b:
        return True
    wa, wb = a.split(), b.split()
    if len(wa) == len(wb):
        return False
    s, l = (wa, wb) if len(wa) < len(wb) else (wb, wa)
    if len(" ".join(s)) < 3 or (len(s) == 1 and s[0] in common):
        return False
    return l[:len(s)] == s or l[-len(s):] == s


def main(which, base, out):
    B = BOOKS[which]
    BOOK, WIKI, ENT = glob.glob(B["book"])[0], glob.glob(B["wiki"])[0], B["ent"]
    lines = open(base, encoding="utf-8").read().splitlines()
    rows = [l for l in lines if re.match(r"^\d+:\d+\t", l)]
    have = sorted({low(l.split("\t")[1]) for l in rows})

    per, shown = collections.Counter(), collections.defaultdict(collections.Counter)
    ids, pron = collections.defaultdict(set), set()
    for e in csv.DictReader(open(ENT, encoding="utf-8"), delimiter="\t", quoting=csv.QUOTE_NONE):
        if e["prop"] == "PROP" and e["cat"] == "PER":
            per[low(e["text"])] += 1
            shown[low(e["text"])][e["text"]] += 1
            ids[low(e["text"])].add(e["COREF"])
        elif e["prop"] == "PRON" and e["cat"] == "PER":
            pron.add(e["COREF"])
    # BookNLP's own notion of a character: someone it hears speak or refers back to with a pronoun
    speaks = {q["char_id"] for q in csv.DictReader(open(ENT[:-len("entities")] + "quotes", encoding="utf-8"),
                                                   delimiter="\t", quoting=csv.QUOTE_NONE)}
    wiki = {}
    for l in open(WIKI, encoding="utf-8"):
        f = l.rstrip("\n").split("\t")
        if l.startswith("#") or len(f) < 3 or f[2] not in PERSONISH:
            continue
        for n in [f[0]] + [x.strip() for x in f[1].split(";") if x.strip()]:
            wiki.setdefault(low(n), f[0])

    # names the runs found but wrote nothing about
    found = collections.Counter()
    for p in glob.glob(CP + "r1[3-7]-reports/" + B["runs"]) + \
            glob.glob(CP + "dense14b/g1[57]-reports/" + B["runs"]):
        for l in open(p, encoding="utf-8"):
            if l.startswith("nothing said about:"):
                for n in l.split(":", 1)[1].split(","):
                    if n.strip():
                        found[n.strip()] += 1

    docs = _documents(BOOK, 2000)
    paras = [(o, n, t) for o, _p, _lab, ps in docs for n, t in ps]
    full = "\n".join(t for _o, _n, t in paras)

    # candidate display forms -> source
    cands = {}
    for n in found:
        cands.setdefault(n, "runs")
    for n, k in per.items():
        if k >= 2:
            # display it as the book most often writes it, capitalised if it ever is
            forms = [f for f, _ in shown[n].most_common() if f[:1].isupper()] or [shown[n].most_common(1)[0][0]]
            cands.setdefault(forms[0], "booknlp")
    for n, canon in wiki.items():
        cands.setdefault(canon, "wiki")

    # like koassistant, common words come from the carried list only
    common = common_words(have)
    have_canon = {wiki[h] for h in have if h in wiki}
    log, cards, seen = collections.Counter(), [], []
    for disp in sorted(cands, key=lambda s: (-len(s), s)):
        src = cands[disp]
        n = low(disp)
        if len(n) < 3:
            log["too short"] += 1
            continue
        if any(same(n, h, common) for h in have) or wiki.get(n) in have_canon:
            log["already has an entry"] += 1
            continue
        # WordDumb-style near match (Theobald/Theobold) and plurals (Popovs)
        if any(difflib.SequenceMatcher(None, n, h).ratio() >= 0.857 or n.rstrip("s") == h for h in have + seen):
            log["near match / plural of an entry"] += 1
            continue
        # a name is a proper noun: capitalised, its words never written in
        # lower case in the book, and not only ever at the start of a sentence
        if not disp[:1].isupper():
            log["not capitalised"] += 1
            continue
        if any(w[:1].islower() and w not in PARTICLES for w in disp.split()):
            log["lower-case word inside the name"] += 1
            continue
        if " " not in disp and re.search(r"(?<![\w’'])" + re.escape(disp.lower()) + r"(?![\w])", full):
            log["also a common word"] += 1
            continue
        if any(same(n, s, common) for s in seen):
            log["same as another card"] += 1
            continue
        # veto: keep only names BookNLP tags as a person 2+ times or the wiki lists as a person
        if per[n] < 2 and n not in wiki:
            log["veto (not a BookNLP/wiki person)"] += 1
            continue
        # the display form as it is written in the book
        rx = re.compile(r"(?<![\w’'])" + re.escape(disp.replace("'", "’")).replace("’", "['’]") + r"(?![\w])")
        hits = rx.findall(full)
        if len(hits) < 2:
            if disp[0].islower():
                rx = re.compile(r"(?<![\w’'])" + re.escape(disp.title()) + r"(?![\w])")
                hits = rx.findall(full)
            if len(hits) < 2:
                log["under 2 mentions in the book"] += 1
                continue
        if " " not in disp and not [x for x in rx.finditer(full)
                                     if not re.search(r"(^|[.!?…—–\"“”‘]\s*|\n)$", full[max(0, x.start() - 3):x.start()])]:
            log["only at the start of a sentence"] += 1
            continue
        # BookNLP-only names: most of the book's mentions must be tagged as a person
        if src == "booknlp" and n not in wiki and per[n] < 0.5 * len(hits):
            log["BookNLP tags under half its mentions as a person"] += 1
            continue
        if src == "booknlp" and n not in wiki and not ids[n] & (pron | speaks):
            log["BookNLP never hears them speak or uses a pronoun"] += 1
            continue
        if disp.isupper() or re.match(r"(A|An|The) ", disp):
            log["starts with a/an"] += 1
            continue
        for o, pn, t in paras:
            m = rx.search(t)
            if m:
                break
        sents = re.split(r"(?<=[.!?…])[\"”’]?\s+", t)
        pos, s = 0, t
        for x in sents:
            i = t.find(x, pos)
            if i <= m.start() < i + len(x) + 1:
                s = x
                break
            pos = i + len(x)
        w = s.split()
        if len(w) > MAX_WORDS:
            # keep a window of words around the name
            k = len(s[:s.find(m.group(0))].split()) if m.group(0) in s else 0
            lo = max(0, min(k - 12, len(w) - MAX_WORDS))
            s = ("… " if lo else "") + " ".join(w[lo:lo + MAX_WORDS]) + (" …" if lo + MAX_WORDS < len(w) else "")
        if m.group(0) not in s:
            log["name not in the quote"] += 1
            continue
        seen.append(n)
        log["card (" + src + ")"] += 1
        print("CARD\t%s\t%s\tbooknlp=%d\twiki=%s\tbook=%d" % (disp, src, per[n], n in wiki, len(hits)))
        cards.append((o, pn, m.group(0), len(hits), 'First mention: "%s"' % s.strip()))

    with open(out, "w", encoding="utf-8") as f:
        f.write("quote cards on top of %s\n\n" % os.path.basename(base))
        for l in rows:
            f.write(l + "\n")
        for o, pn, who, k, text in sorted(cards):
            f.write("%d:%d\t%s\theard\t%d\t%s\n" % (o, pn, who, k, text))
    for k, v in sorted(log.items()):
        print("%-40s %d" % (k, v))
    print("cards:", len(cards))


if __name__ == "__main__":
    main(*sys.argv[1:4])
