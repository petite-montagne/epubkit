"""The who's who written chapter by chapter with quoted changes (cast_method = "xray").

The book and the model are both made up here: no real book text."""
from __future__ import annotations

import json
import logging

from epubkit.ai.providers import OllamaProvider, OpenAIProvider
from epubkit.stages import cast_xray as X


class Ctx:
    log = logging.getLogger("test")

    def report(self, _t):
        pass

    def note(self, _t):
        pass

    def tell(self, _t):
        pass


DOCS = [
    (1, "c1.xhtml", "Chapter 1", [
        (0, "Mara Quill walked into the harbour hall. Tobin Reed, the old ferryman, was mending a net."),
        (1, "“Sit down,” Tobin said. Mara Quill sat. Draven Holt watched them from the door."),
        (2, "A man in a grey cloak, the Grey Stranger, paid for a room and said nothing."),
    ]),
    (2, "c2.xhtml", "Chapter 2", [
        (0, "Mr. Holt came in from the docks. Corvin Holt is Draven's father, a merchant."),
        (1, "Mara Quill and Tobin Reed took the ferry out. Then the boat struck the rocks "
            "and Tobin Reed drowned in the river. Tobin was gone."),
    ]),
    (3, "c3.xhtml", "Chapter 3", [
        (0, "Mara Quill sailed on alone. Draven Holt laughed at her from the pier."),
        (1, "The Grey Stranger pulled back his hood. “I am Wren Ashby,” he said, "
            "“and I was your mother's brother.” Mara Quill stared at Wren Ashby."),
    ]),
]


def new(name, typ, who, evidence, aliases=()):
    return {"name": name, "type": typ, "aliases": list(aliases), "who": who, "evidence": evidence}


def change(name, now, event, quote, other=""):
    return {"name": name, "status": "CHANGED", "now": now, "event": event, "other": other,
            "quote": quote}


ANSWERS = {
    "Chapter 1": {"new": [
        new("Mara Quill", "person", "A young sailor in the harbour town.", "Mara Quill walked into"),
        new("Tobin Reed", "person", "The old ferryman who mends nets.", "Tobin Reed, the old ferryman"),
        new("Draven Holt", "person", "A young man who watches Mara.", "Draven Holt watched them"),
        new("Grey Stranger", "person", "A silent man in a grey cloak.", "the Grey Stranger, paid"),
        new("Harbour Hall", "place", "A hall.", "the harbour hall"),
    ], "updates": []},
    "Chapter 2": {"new": [
        # the model calls the father by the son's description: kept apart
        new("Mr. Holt", "person", "A young man who watches Mara.", "Mr. Holt came in"),
        new("Corvin Holt", "person", "Draven's father, a merchant.", "Corvin Holt is Draven's father"),
    ], "updates": [
        change("Tobin Reed", "Drowned when the ferry struck the rocks.", "died",
               "Tobin Reed drowned in the river"),
        # a made-up death: the quote is not in the text
        change("Mara Quill", "Died in the wreck.", "died", "Mara Quill drowned with him"),
    ]},
    "Chapter 3": {"new": [
        new("Wren Ashby", "person", "Mara's uncle, her mother's brother.", "I am Wren Ashby",
            aliases=["Grey Stranger"]),
    ], "updates": [
        # a big claim the quote does not make
        change("Draven Holt", "Killed by Mara.", "killed", "Draven Holt laughed at her",
               other="Mara Quill"),
        change("Grey Stranger", "Revealed as Wren Ashby, Mara's uncle.", "revealed",
               "I am Wren Ashby"),
    ]},
}


class Model:
    def __init__(self):
        self.prompts = []

    def __call__(self, prompt, system, usable):
        self.prompts.append(prompt)
        if prompt.startswith("Two entries"):
            a, b = prompt.split("\nB: ", 1)
            pair = {"Stranger" in a or "Wren" in a, "Stranger" in b or "Wren" in b}
            return "SAME" if pair == {True} else "DIFFERENT ENTITIES"
        text = prompt.split("NEW TEXT:", 1)[1]
        for marker, chapter in (("harbour hall", "Chapter 1"), ("came in from the docks", "Chapter 2"),
                                ("sailed on alone", "Chapter 3")):
            if marker in text:
                return json.dumps(ANSWERS[chapter])
        return json.dumps({"new": [], "updates": []})


def run():
    model = Model()
    rows, report, _seen = X.build(Ctx(), DOCS, model, hero="Mara Quill")
    return rows, report, model


def entries(rows):
    """[(chapter order, "name: entry")] in book order."""
    return [(r[0], "%s: %s" % (r[3], r[-1])) for r in rows]


def test_a_quoted_change_is_kept_and_filed_where_it_happens():
    rows, _r, _m = run()
    tobin = [(o, e) for o, e in entries(rows) if "Tobin" in e]
    assert tobin[0][0] == 1 and "ferryman" in tobin[0][1]
    assert any(o == 2 and "Drowned" in e for o, e in tobin)


def test_a_made_up_death_and_an_unbacked_big_claim_are_turned_down():
    rows, report, _m = run()
    text = " ".join(e for _o, e in entries(rows))
    assert "Died in the wreck" not in text
    assert "Killed by Mara" not in text
    assert "2 turned down" in report[0] and "2 changes kept" in report[0]


def test_places_are_not_people():
    rows, report, _m = run()
    assert not any("Harbour Hall" in e for _o, e in entries(rows))
    assert any("Harbour Hall" in line for line in report)


def test_a_father_never_takes_his_sons_entry():
    rows, _r, _m = run()
    draven = [e for _o, e in entries(rows) if e.startswith("Draven")]
    corvin = [e for _o, e in entries(rows) if e.startswith("Corvin")]
    assert draven and corvin
    assert all("father" not in e for e in draven)
    assert all("father" in e for e in corvin)
    # "Mr. Holt" given Draven's own line is not listed as someone new
    assert not any(e.startswith("Mr. Holt") for _o, e in entries(rows))


def test_a_reveal_is_not_shown_before_the_book_makes_it():
    rows, _r, _m = run()
    early = [e for o, e in entries(rows) if o == 1]
    late = [e for o, e in entries(rows) if o == 3]
    assert not any("Wren" in e for e in early)
    assert any("Grey Stranger" in e for e in early)
    assert any("Wren Ashby" in e for e in late)


def test_a_title_and_family_name_is_not_matched_by_the_surname():
    r = X._Run(Ctx(), DOCS, Model(), "", False)
    r.known["Draven Holt"] = dict(aliases=[], type="person", first="A young man.", change="",
                                  narrator=False)
    assert r.find("Mr. Holt") is None
    assert r.find("Draven") == "Draven Holt"
    assert X.same_family("Draven Holt", "Corvin Holt")
    assert not X.same_family("Draven Holt", "Draven")
    assert X.kin_of("Draven's father, a merchant.", ["Draven Holt", "Draven"])
    assert not X.kin_of("A merchant of the docks.", ["Draven Holt"])


def test_a_quote_may_differ_by_one_word():
    text = "We will take the ferry out at dawn, Tobin said."
    assert X.quote_ok("We will take the ferry out at dawn", text)
    assert X.quote_ok("You will take the ferry out at dawn", text)
    assert not X.quote_ok("You will take the boat out at dusk", text)
    assert not X.quote_ok("take a ferry", text)


def test_back_matter_and_a_sample_chapter_are_not_read():
    docs = [(i, "c%d.xhtml" % i, "Chapter %d" % i, [(0, "Mara Quill rowed.")]) for i in range(1, 7)]
    docs.append((7, "s.xhtml", "Chapter 1", [(0, "A sample of the next book.")]))
    log = []
    kept = X.story_parts(docs, log)
    assert [d[0] for d in kept] == [1, 2, 3, 4, 5, 6]
    assert log[0].startswith("cut order 7")
    docs[-1] = (7, "s.xhtml", "Chapter 1", [(0, "Mara Quill rowed again.")])
    log = []
    assert len(X.story_parts(docs, log)) == 6 and "chapter count restarts" in log[0]


def test_a_book_not_in_english_uses_the_book_method(monkeypatch):
    seen = {}
    monkeypatch.setattr(X.C, "build", lambda *a, **k: seen.setdefault("lang", k["lang"]) and ([], [], []))
    X.build(Ctx(), DOCS, Model(), lang="fr")
    assert seen["lang"] == "fr"


def test_a_run_is_repeatable():
    first, _r, _m = run()
    again, _r, _m = run()
    assert first == again


def test_a_seed_makes_a_local_server_repeatable(monkeypatch):
    seen = {}
    p = OpenAIProvider("qwen", "http://local:8081/v1", None, seed=7)
    monkeypatch.setattr(p, "_post", lambda u, pl, h: seen.update(pl) or
                        {"choices": [{"message": {"content": "k"}}]})
    p.complete("x")
    assert (seen["seed"], seen["top_k"], seen["cache_prompt"]) == (7, 1, False)

    seen.clear()
    p = OpenAIProvider("qwen", "http://local:8081/v1", None)
    monkeypatch.setattr(p, "_post", lambda u, pl, h: seen.update(pl) or
                        {"choices": [{"message": {"content": "k"}}]})
    p.complete("x")
    assert "seed" not in seen and "cache_prompt" not in seen

    seen.clear()
    p = OpenAIProvider("gpt", "https://api.openai.com", "sk", seed=7)
    monkeypatch.setattr(p, "_post", lambda u, pl, h: seen.update(pl) or
                        {"choices": [{"message": {"content": "k"}}]})
    p.complete("x")
    assert "seed" not in seen

    seen.clear()
    p = OllamaProvider("gemma2:9b", "http://localhost:11434", seed=7)
    monkeypatch.setattr(p, "_post", lambda u, pl, h: seen.update(pl) or {"response": "ok"})
    p.complete("x")
    assert seen["options"]["seed"] == 7 and seen["options"]["top_k"] == 1
