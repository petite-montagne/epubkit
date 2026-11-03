"""Build a series' names list from its fan wiki: who goes by which names.

    python -m epubkit.tools.wiki_names --series "Dungeon Crawler Carl"
    python -m epubkit.tools.wiki_names --series "Harry Potter" --wiki https://harrypotter.fandom.com

It writes "<series>.names.tsv" next to the series memory (series_memory.Names
reads it): one row per character page, with every name that points at that
page (the wiki's redirects, and the infobox's aliases, nicknames and titles).

Only names go in, never a description, so nothing the wiki says about anyone
can reach a book. The who's who uses the list to join two names of one
person ("Bea" / "Miss Beatrice") and to keep two people apart, and a row
whose first appearance is a later book is skipped (series_memory.Names), so a
name the reader hasn't met can't join anyone early.

An existing list is never overwritten without --force: a hand-made one may be
better than the wiki's.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from .. import series_memory

AGENT = "epubkit-wiki-names/1.0 (personal e-book library tool)"
CATEGORIES = ("Characters", "Crawlers", "NPCs", "People", "Individuals")
FIELDS = r"(?:aliases?|nicknames?|other ?names?|also ?known ?as|aka|titles?|full ?name|real ?name|names?)"
FIRST = r"(?:first ?appearance|first|debut|introduced)"


def candidates(series: str) -> list[str]:
    """Likely Fandom addresses for a series name."""
    s = re.sub(r"[^\w\s-]", "", series.lower()).strip()
    s = re.sub(r"^the\s+", "", s)
    words = s.split()
    out = []
    for w in ("-".join(words), "".join(words), words[0] if words else ""):
        if w and "https://%s.fandom.com" % w not in out:
            out.append("https://%s.fandom.com" % w)
    return out


class Wiki:
    def __init__(self, base: str, get=None, pause: float = 0.3):
        self.api = base.rstrip("/") + "/api.php"
        self.get = get or self._get
        self.pause = pause

    def _get(self, url: str) -> dict:
        req = urllib.request.Request(url, headers={"User-Agent": AGENT})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))

    def query(self, **params) -> list[dict]:
        """Every page of a query, following "continue"."""
        params = {"action": "query", "format": "json", "formatversion": "2", **params}
        out, cont = [], {}
        for _ in range(200):
            got = self.get(self.api + "?" + urllib.parse.urlencode({**params, **cont}))
            out.append(got.get("query") or {})
            cont = got.get("continue") or {}
            if not cont:
                break
            if self.pause:
                time.sleep(self.pause)
        return out

    def ok(self) -> bool:
        try:
            return bool(self.query(meta="siteinfo")[0].get("general"))
        except Exception:                                    # noqa: BLE001
            return False

    def characters(self) -> list[str]:
        titles, seen_cats = [], set()
        todo = [("Category:" + c, 0) for c in CATEGORIES]
        while todo:
            cat, depth = todo.pop(0)
            if cat in seen_cats:
                continue
            seen_cats.add(cat)
            for q in self.query(list="categorymembers", cmtitle=cat, cmlimit="500",
                                cmtype="page|subcat"):
                for m in q.get("categorymembers") or []:
                    if m.get("ns") == 14 and depth < 1:
                        todo.append((m["title"], depth + 1))
                    elif m.get("ns") == 0 and m["title"] not in titles:
                        titles.append(m["title"])
        return titles

    def names_of(self, titles: list[str]) -> dict[str, dict]:
        """{title: {"others": [...], "first": "..."}} from redirects and infoboxes."""
        out = {t: {"others": [], "first": ""} for t in titles}
        for i in range(0, len(titles), 50):
            batch = titles[i:i + 50]
            for q in self.query(titles="|".join(batch), prop="redirects|revisions",
                                rdlimit="max", rdnamespace="0", rvprop="content",
                                rvslots="main"):
                for p in q.get("pages") or []:
                    t = p.get("title")
                    if t not in out:
                        continue
                    for r in p.get("redirects") or []:
                        out[t]["others"].append(r["title"])
                    revs = p.get("revisions") or []
                    if revs:
                        text = ((revs[0].get("slots") or {}).get("main") or {}).get("content") \
                            or revs[0].get("content") or ""
                        names, first = infobox(text)
                        out[t]["others"] += names
                        out[t]["first"] = out[t]["first"] or first
        for t, v in out.items():
            seen, keep = {t.lower()}, []
            for n in v["others"]:
                if n.lower() not in seen and 1 < len(n) <= 60:
                    seen.add(n.lower())
                    keep.append(n)
            v["others"] = keep
        return out


def clean(value: str) -> list[str]:
    """Names from one infobox value: links unwrapped, notes and refs dropped."""
    v = re.sub(r"<ref[^>]*?/>|<ref.*?</ref>", "", value, flags=re.S)
    v = re.sub(r"\{\{[^{}]*\}\}", "", v)
    v = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", v)
    v = re.sub(r"'''?|<[^>]+>", lambda m: "\n" if m.group(0).startswith("<br") else "", v)
    v = re.sub(r"\([^)]*\)", "", v)
    out = []
    for n in re.split(r"[\n,;•*]|<br\s*/?>| / ", v):
        n = n.strip(" \"'“”‘’.:")
        if n and len(n.split()) <= 6 and not re.search(r"https?:|=", n):
            out.append(n)
    return out


def infobox(text: str) -> tuple[list[str], str]:
    names, first = [], ""
    for m in re.finditer(r"^\s*\|\s*(%s)\s*=\s*(.*)$" % FIELDS, text, re.I | re.M):
        names += clean(m.group(2))
    m = re.search(r"^\s*\|\s*%s\s*=\s*(.*)$" % FIRST, text, re.I | re.M)
    if m:
        got = clean(m.group(1))
        first = got[0] if got else ""
    return names, first


def book_number(first: str, titles: dict[str, str]) -> str:
    """The book a first appearance names, by number or by title."""
    if not first:
        return ""
    m = re.search(r"\b(?:book|volume|vol\.?)\s*(\d+)\b", first, re.I)
    if m:
        return m.group(1)
    f = re.sub(r"\W+", " ", first.lower()).strip()
    for k, t in titles.items():
        tt = re.sub(r"\W+", " ", (t or "").lower()).strip()
        if tt and (tt in f or f in tt):
            return str(k)
    return ""


def rows(wiki: Wiki, titles: dict[str, str]) -> list[str]:
    chars = wiki.characters()
    found = wiki.names_of(chars)
    out = ["# names list from %s, %s" % (wiki.api, time.strftime("%Y-%m-%d")),
           "# name<TAB>other names<TAB>kind<TAB>first book"]
    for t in sorted(found):
        v = found[t]
        out.append("\t".join((t, "; ".join(v["others"]), "person",
                              book_number(v["first"], titles))))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--series", required=True)
    ap.add_argument("--wiki", help="the wiki's address, if not <series>.fandom.com")
    ap.add_argument("--series-dir")
    ap.add_argument("--force", action="store_true", help="replace an existing list")
    a = ap.parse_args(argv)
    folder = Path(a.series_dir).expanduser() if a.series_dir else series_memory.default_dir()
    path = folder / (series_memory.slug(a.series) + ".names.tsv")
    if path.exists() and not a.force:
        print("%s already exists; --force replaces it" % path)
        return 1
    wiki = None
    for base in ([a.wiki] if a.wiki else candidates(a.series)):
        w = Wiki(base)
        if w.ok():
            wiki = w
            break
    if wiki is None:
        print("no wiki found for %s; give one with --wiki" % a.series)
        return 2
    memory = series_memory.Memory.open(folder, a.series)
    titles = {k: (v or {}).get("title", "") for k, v in memory.data.get("books", {}).items()}
    lines = rows(wiki, titles)
    folder.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("%d characters from %s -> %s" % (len(lines) - 2, wiki.api, path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
