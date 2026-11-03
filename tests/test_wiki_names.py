"""The names list from a fan wiki: names only, never descriptions."""
import json
import urllib.parse

from epubkit.tools import wiki_names as W

PAGE = """{{Character
| name = Beatrice
| aliases = Bea<br>Miss Beatrice<ref>Book 1</ref>
| first appearance = [[Dungeon Crawler Carl (book)|Dungeon Crawler Carl]]
| description = A long text that must never be used.
}}"""


def fake(url):
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
    if q.get("meta") == "siteinfo":
        return {"query": {"general": {"sitename": "x"}}}
    if q.get("list") == "categorymembers":
        if q["cmtitle"] == "Category:Characters":
            return {"query": {"categorymembers": [{"ns": 0, "title": "Beatrice"}]}}
        return {"query": {"categorymembers": []}}
    return {"query": {"pages": [{"title": "Beatrice",
                                 "redirects": [{"title": "Beatrice's owner"}],
                                 "revisions": [{"slots": {"main": {"content": PAGE}}}]}]}}


def test_a_wiki_gives_names_and_the_first_book_only():
    w = W.Wiki("https://x.fandom.com", get=fake, pause=0)
    assert w.ok()
    lines = W.rows(w, {"1": "Dungeon Crawler Carl"})
    row = lines[-1].split("\t")
    assert row[0] == "Beatrice" and row[2] == "person" and row[3] == "1"
    assert set(row[1].split("; ")) == {"Beatrice's owner", "Bea", "Miss Beatrice"}
    assert "long text" not in json.dumps(lines)
    assert W.candidates("The Dungeon Crawler Carl")[0] == "https://dungeon-crawler-carl.fandom.com"
