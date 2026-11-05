"""The who's who written chapter by chapter with quoted changes (cast_method = "xray").

The book and the model are both made up here: no real book text."""
from __future__ import annotations

import json
import logging
import sys

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


# ---- the DCC 1-5 test run (Nov 2026): what went wrong, and why it cannot again

class View:
    def __init__(self, people):
        self.people = people


BOOK2 = [
    (1, "front.xhtml", "Acknowledgments", [(0, "Thanks to Matt Dinniman and my Patreon backers.")]),
    (2, "c1.xhtml", "Chapter 1", [
        (0, "Mara Quill woke on the ferry. Tobin's old hat hung by the door."),
        (1, "Wren Ashby poured the tea. “Sit,” Wren said. I watched the gulls."),
        (2, "A Kobold ran past, then two more Kobolds, and the tree guy waved. Gwendolyn Duet waved from the dock."),
    ]),
    (3, "c2.xhtml", "Chapter 2", [
        (0, "Gwen shouted again. Sierra, a vampire, landed beside Mara Quill. Wren Ashby frowned."),
        (1, "Mara Quill sang like Taylor Swift. Gwen laughed."),
    ]),
]

ANSWERS2 = {
    "woke on the ferry": {"new": [
        new("I", "person", "The narrator.", "I watched the gulls"),
        new("Kobold", "monster", "A small monster running past.", "A Kobold ran past"),
        new("tree guy", "person", "A man in a tree.", "the tree guy waved"),
        new("Gwendolyn Duet", "person", "A sailor on the dock.", "Gwendolyn Duet waved"),
    ], "updates": []},
    "Gwen shouted again": {"new": [
        new("Sierra", "monster", "A vampire who lands beside Mara.", "Sierra, a vampire, landed",
            aliases=["Wren Ashby"]),
        dict(new("Taylor Swift", "person", "A singer.", "sang like Taylor Swift"), one="no"),
        new("Gwen", "person", "A loud sailor.", "Gwen shouted again"),
    ], "updates": []},
}


class Model2(Model):
    def __call__(self, prompt, system, usable):
        self.prompts.append(prompt)
        if prompt.startswith("Two entries"):
            return "SAME" if "Gwen" in prompt.split("\nB: ", 1)[1] else "DIFFERENT ENTITIES"
        text = prompt.split("NEW TEXT:", 1)[1]
        for marker, got in ANSWERS2.items():
            if marker in text:
                return json.dumps(got)
        return json.dumps({"new": [], "updates": []})


def run2(view=True):
    model = Model2()
    people = {"Mara Quill": ("A young sailor, Tobin's apprentice.", [], 1),
              "Wren Ashby": ("Mara's uncle, once known as the Grey Stranger. Now the harbour master.",
                             ["Grey Stranger"], 1)}
    rows, report, _s = X.build(Ctx(), BOOK2, model, hero="Mara Quill", first_person=True,
                               view=View(people) if view else None)
    return entries(rows), report, model


def test_people_from_the_earlier_books_start_from_who_they_were():
    rows, _r, _m = run2()
    wren = [(o, e) for o, e in rows if e.startswith("Wren Ashby")]
    # the whole line, what they became too
    assert wren[0] == (2, "Wren Ashby: Mara's uncle, once known as the Grey Stranger. "
                          "Now the harbour master.")


def test_the_earlier_books_are_only_named_where_this_book_names_them():
    rows, _r, model = run2()
    # Tobin's not in this book's list: the book only names his hat
    assert not any(e.startswith("Tobin") for _o, e in rows)
    # and the model is only shown the people a part names
    assert "Grey Stranger" not in model.prompts[0] or "Wren" in model.prompts[0]


def test_the_narrator_is_never_a_person_called_i():
    rows, _r, _m = run2()
    assert not any(e.startswith("I:") for _o, e in rows)


def test_kinds_descriptions_and_outside_people_are_not_listed():
    rows, _r, _m = run2()
    names = {e.split(":")[0] for _o, e in rows}
    assert not names & {"Kobold", "tree guy", "Taylor Swift"}


def test_a_model_alias_the_text_does_not_back_joins_no_one():
    rows, report, _m = run2()
    wren = [e for _o, e in rows if e.startswith("Wren Ashby")]
    assert all("vampire" not in e for e in wren)


def test_a_nickname_joins_the_full_name():
    rows, _r, _m = run2()
    names = [e.split(":")[0] for _o, e in rows]
    assert "Gwen" not in names and "Gwendolyn Duet" in names


def test_the_authors_pages_are_skipped():
    log = []
    kept = X.story_parts(BOOK2, log)
    assert [d[0] for d in kept] == [2, 3]
    assert "before the story" in log[0]


def test_name_forms():
    assert X.variant("Bea", "Miss Beatrice")
    assert X.variant("Gwen", "Gwendolyn Duet")
    assert X.variant("Tina", "Big Tina")
    assert X.variant("Bianca", "Bianca Del Ciao")
    assert not X.variant("Fire Brandy", "Tizquick")
    assert not X.variant("Miriam Dom", "Sierra")
    assert not X.variant("Draven Holt", "Corvin Holt")
    # one name spelt two ways
    assert X.variant("Lucia Marr", "Lucia Mar")
    assert X.variant("Vincente", "Vicente")
    assert not X.variant("Lena", "Lina")
    assert X.variant("Theobold", "Theobald")
    assert not X.variant("Marlon", "Marvin")
    assert not X.variant("Lucia Marr", "Lucio Mar")


def test_a_title_added_or_dropped_is_the_same_person():
    r = X._Run(Ctx(), DOCS, Model(), "", False)
    for k in ("Donut", "Henrik", "Draven Holt", "Mr. Kell"):
        r.known[k] = dict(aliases=[], type="person", first="Someone.", change="",
                          narrator=False)
    assert r.retitled("Donut", "Princess Donut")
    assert r.retitled("Henrik", "King Henrik")
    assert not r.retitled("Draven Holt", "Mr. Holt")
    assert not r.retitled("Mr. Kell", "Mrs. Kell")
    assert not r.retitled("Donut", "Mongo")
    r.known["Mexx-6000"] = dict(aliases=[], type="person", first="A robot.", change="",
                                narrator=False)
    r.known["Glass Wizard"] = dict(aliases=[], type="person", first="A wizard.", change="",
                                   narrator=False)
    assert r.retitled("Mexx-6000", "Mexx")
    r.known["Grimaldi"] = dict(aliases=[], type="person", first="A boss.", change="",
                               narrator=False)
    r.book += " The ringmaster bowed."
    assert r.retitled("Grimaldi", "Ringmaster Grimaldi")
    assert not r.retitled("Grimaldi", "Wizard Grimaldi")
    assert r.named_as("The Glass Wizard who sent a letter.", "Ghazi") == "Glass Wizard"
    assert r.named_as("A man who met the Glass Wizard.", "Ghazi") is None
    assert X.carry_split("rock monster bodyguard. Now a guard.")[0] == "Rock monster bodyguard."
    assert X.linked("Psamathe", "Samantha", "The goddess Psamathe, now called Samantha, smiled.")
    assert X.linked("Riddle", "Lord Voldemort", "Riddle said, “I am Lord Voldemort.”")
    assert not X.linked("Fire Brandy", "Tizquick", "Fire Brandy and Tizquick drove the train.")


def test_the_series_memory_keeps_everyone_the_xray_list_kept(tmp_path, monkeypatch):
    """Hekla is named once in book 1 and back in book 3: she must come back
    under the same name, not as "Hekla of Brynhild's Daughters"."""
    import types

    from epubkit import series_memory as S
    from epubkit.stages import recaps as R

    monkeypatch.setattr(R, "_story", lambda *a, **k: "")
    memory = S.Memory.open(tmp_path, "Test")
    rows = [(1, "c1", 0, "Carl", "met", 9, "The narrator."),
            (1, "c1", 5, "Hekla", "heard", 1, "A Valkyrie and leader of Brynhild's Daughters.")]
    for method, want in (("book", {"Carl"}), ("xray", {"Carl", "Hekla"})):
        memory.data["people"] = {}
        ctx = types.SimpleNamespace(
            config=types.SimpleNamespace(recaps=types.SimpleNamespace(cast_method=method)),
            path=tmp_path / "book1.epub", provider=None,
            report=lambda _t: None, note=lambda _t: None)
        R._remember_entries(ctx, memory, 1, "Carl", True, [], rows, {"leads": "them"})
        assert set(memory.data["people"]) == want


def test_what_carries_to_the_next_book_is_who_they_are_not_a_passing_state():
    # the level taken out of "Carl is now level three and..." left a broken
    # sentence that rode along in every later row of book 2
    assert X.carried("The narrator, a marine tech. Carl is now and has gained the skills "
                     "Foot Soldier and Smush.") == "The narrator, a marine tech."
    assert X.carried("A cat owned by Beatrice. Donut is now after participating in the "
                     "fight.") == "A cat owned by Beatrice."
    # what they became stays
    assert X.carried("A rat-like creature who guards the guild door. A Bugaboo creature "
                     "and guildmaster.") == ("A rat-like creature who guards the guild door. "
                                             "A Bugaboo creature and guildmaster.")
    assert X.carried("A goblin. He was drunk in the saferoom. Now Donut's manager.") == \
        "A goblin. Now Donut's manager."


def test_a_newer_change_replaces_what_a_carried_person_became():
    """Book 3 rows read "who + book 1's change + book 3's change": the carried
    change must be the one a newer change replaces, not part of who they are."""
    import types
    view = types.SimpleNamespace(people={
        "Zev": ("A woman who runs the show. Zev is suspended for cheating.", [], 2)})
    r = X._Run(Ctx(), DOCS, Model(), "", False, view)
    assert r.known["Zev"]["first"] == "A woman who runs the show."
    assert r.known["Zev"]["change"] == "Zev is suspended for cheating."
    assert r.who("Zev") == "A woman who runs the show. Zev is suspended for cheating."
    r.known["Zev"]["change"] = "On a retreat."
    assert r.who("Zev") == "A woman who runs the show. On a retreat."
    assert X.carry_split("A goblin. He was drunk in the saferoom.") == ("A goblin.", "")


def test_dropping_a_claim_never_leaves_a_fragment():
    """Book 4 had "Created Ruckus." and "Who held a Master's Degree..." once an
    unbacked death was cut from the head of the line."""
    r = X._Run(Ctx(), DOCS, Model(), "", False)
    text = "Shamus built the great bird Ruckus. Jennifer held a degree in library science."
    pt = X.squash(text)
    got = r.check_intro("Jennifer", [], "A librarian killed in the flood, who held a degree "
                        "in library science.", "Jennifer held a degree", pt, text)
    assert got == "A librarian, who held a degree in library science."
    got = r.check_intro("Shamus", [], "Killed long ago and created Ruckus.",
                        "Shamus built the great bird Ruckus", pt, text)
    assert got == "Someone who created Ruckus."
    got = r.check_intro("Crixus", [], "A sniper who killed a guard and the mad mage's goal.",
                        "Shamus built", pt, text)
    assert got == "A sniper who is the mad mage's goal."


def test_one_person_kept_twice_by_earlier_books_is_one_entry():
    """Book 5 listed "Drakea" and "Crawler Drakea" in the same spot: earlier
    books had kept both, and each became its own entry."""
    import types
    view = types.SimpleNamespace(people={
        "Drakea": ("A crawler who wrote in the cookbook.", [], 2),
        "Crawler Drakea": ("A crawler.", [], 1),
        "Finian": ("An elf king.", [], 1),
        "King Finian": ("The elf king.", [], 1),
        "Theobold": ("A gnome.", [], 1),
        "Theobald": ("A gnome.", [], 1)})
    r = X._Run(Ctx(), DOCS, Model(), "", False, view)
    assert {"Drakea", "Finian", "Theobold"} <= set(r.known)
    assert not {"Crawler Drakea", "King Finian", "Theobald"} & set(r.known)
    assert "Crawler Drakea" in r.known["Drakea"]["aliases"]
    assert r.retitled("Finian", "Sir Finian")


def test_two_entries_for_one_name_are_joined_at_the_end():
    r = X._Run(Ctx(), DOCS, Model(), "", False)
    for k in ("Crawler Drakea", "Drakea", "Draven Holt", "Corvin Holt"):
        r.known[k] = dict(aliases=[], type="person", first="Someone.", change="",
                          narrator=False)
    r.finish()
    assert ("Drakea" in r.known) != ("Crawler Drakea" in r.known)
    assert {"Draven Holt", "Corvin Holt"} <= set(r.known)
    assert not X.variant("Manasa", "Mana Genita")
    assert X.variant("Bea", "Miss Beatrice")


def test_a_job_word_is_not_a_given_name():
    r = X._Run(Ctx(), DOCS, Model(), "", False)
    r.book += " The ringmaster bowed."
    assert not r.family(["Ringmaster Grimaldi"], "", ["Papa Grimaldi"], "")
    assert r.family(["Draven Holt"], "", ["Corvin Holt"], "")


def test_the_names_list_joins_a_nickname_and_keeps_two_people_apart():
    from epubkit import series_memory as S
    names = S.Names([("Beatrice", ["Bea", "Miss Beatrice"], "person"),
                     ("Mr. Holt", [], "person"), ("Holt", [], "person")])
    r = X._Run(Ctx(), DOCS, Model(), "", False, None, names)
    for k in ("Bea", "Miss Beatrice", "Holt", "Mr. Holt"):
        r.known[k] = dict(aliases=[], type="person", first="Someone.", change="",
                          narrator=False)
    r.finish()
    assert ("Bea" in r.known) != ("Miss Beatrice" in r.known)
    assert r.listed(["Holt"], ["Mr. Holt"]) is False
    assert r.listed(["Bea"], ["Zed"]) is None


def test_the_self_check_mends_or_leaves_out_every_bad_line():
    C = X.C
    r = X._Run(Ctx(), DOCS, Model(), "", False)
    bog = C.Person("Bogdon Ro", {"Bogdon Ro"}, True)
    bog.rows = [(5, "", 90, "heard", "A legatus ranked ninth. Reanimated corpse head biting "
                 "Vrah's neck.")]
    lang = C.Person("Langley", {"Langley"}, True)
    lang.rows = [(5, "", 10, "heard", "A leader of a larger group."),
                 (5, "", 102, "heard", "A leader of a larger group. Reanimated corpse head "
                  "biting Vrah's neck.")]
    bomo = C.Person("Bomo", {"Bomo"}, True)
    bomo.rows = [(5, "", 1, "heard", "rock monster bodyguard. Hired by Clarabelle. Level up. "
                  "Now guards Carl.")]
    ika = C.Person("Ikicha", {"Ikicha"}, True)
    ika.rows = [(5, "", 3, "heard", "A crawler who writes notes in the cookbook."),
                (5, "", 4, "heard", "A crawler.")]
    r.self_check([bog, lang, bomo, ika])
    assert "Vrah" in bog.rows[0][4]
    assert all("Vrah" not in row[4] for row in lang.rows)
    assert bomo.rows[0][4] == "Rock monster bodyguard. Now guards Carl."
    assert [row[4] for row in ika.rows] == ["A crawler who writes notes in the cookbook."]


def test_twice_is_one_name_shown_twice_not_a_relative():
    from epubkit.stages.cast_xray import twice
    assert twice("Lucia Marr", "Lucia Mar") and twice("Princess Donut", "Donut")
    assert not twice("Mrs. Ghazi", "Ghazi") and not twice("Carl", "Donut")


def test_a_listed_person_or_the_lead_is_never_turned_into_not_a_person(monkeypatch):
    """DCC 4, run 10: "Carl" and "Crawler Carl" landed on the not-people list,
    which would have shut the main character out for the rest of the book."""
    answers = json.loads(json.dumps(ANSWERS2))
    answers["Gwen shouted again"]["new"] += [
        dict(new("Mara Quill", "group", "Sailors like her.", "landed beside Mara Quill"), one="no"),
        new("Wren Ashby", "place", "The harbour.", "Wren Ashby frowned"),
        dict(new("Captain Mara Quill", "title", "Her title.", "landed beside Mara Quill"), one="no"),
    ]
    monkeypatch.setattr(sys.modules[__name__], "ANSWERS2", answers)
    _rows, report, _m = run2()
    bad = [r for r in report if r.startswith("not people:")]
    assert not any("Mara Quill" in r or "Wren Ashby" in r for r in bad), bad   # titled too


def test_a_change_the_model_says_is_someone_else_s_is_turned_down():
    # a monster with the same name, or someone described just after Tobin speaks
    class Namesake(Model):
        def __call__(self, prompt, system, usable):
            if prompt.startswith("A character list has this entry"):
                self.prompts.append(prompt)
                return "DIFFERENT ENTITIES" if "Tobin Reed" in prompt else "SAME"
            return super().__call__(prompt, system, usable)
    model = Namesake()
    rows, report, _seen = X.build(Ctx(), DOCS, model, hero="Mara Quill")
    text = " ".join(e for _o, e in entries(rows))
    assert "Drowned" not in text
    assert "(1 as someone else's)" in report[0]
    asked = [p for p in model.prompts if p.startswith("A character list")]
    assert asked and "Tobin Reed drowned in the river" in asked[0]


def test_no_answer_on_whose_line_keeps_the_change():
    rows, report, model = run()
    assert any("Drowned" in e for _o, e in entries(rows))
    assert any(p.startswith("A character list") for p in model.prompts)


# ---- the event-first records (recaps.cast_events) --------------------------

def event(who, what, quote, happened="yes", lasting="yes", kind="change"):
    return {"who": who, "what": what, "kind": kind, "happened": happened, "lasting": lasting,
            "quote": quote}


EVENTS = {
    "Chapter 1": [],
    "Chapter 2": [
        event("Tobin Reed", "Tobin Reed drowned when the ferry struck the rocks.",
              "Tobin Reed drowned in the river"),
        # a moment, not a change
        event("Mara Quill", "Mara Quill is soaked on the ferry.", "Mara Quill and Tobin Reed took",
              lasting="no"),
        # only said
        event("Corvin Holt", "Corvin Holt becomes a merchant.", "Corvin Holt is Draven's father",
              happened="no"),
    ],
    "Chapter 3": [
        # the step says lasting; asked on its own, the model says it is for a while
        event("Mara Quill", "Mara Quill sets out on a voyage alone.", "Mara Quill sailed on alone"),
        # a namesake the model marks
        event("Tobin (the eel)", "Tobin the eel is eaten.", "Mara Quill sailed on alone"),
        # the quote names no one; the last person named before it is Mara, not Draven
        event("Draven Holt", "Draven Holt is revealed as her uncle.",
              "and I was your mother's brother"),
    ],
}


class Events(Model):
    def __init__(self, rewrite=None):
        super().__init__()
        self.rewrite = rewrite

    def __call__(self, prompt, system, usable):
        if prompt.startswith("A spoiler-free character list"):
            self.prompts.append(prompt)
            if self.rewrite is not None:
                return self.rewrite
            return "The old ferryman of the harbour town, who drowned when the ferry struck the rocks."
        if prompt.startswith("A character list has this entry"):
            self.prompts.append(prompt)
            return "SAME"
        if prompt.startswith("Part of a novel"):
            self.prompts.append(prompt)
            return "FOR A WHILE" if "voyage" in prompt else "LASTING"
        got = json.loads(super().__call__(prompt, system, usable))
        text = prompt.split("NEW TEXT:", 1)[1]
        for marker, chapter in (("harbour hall", "Chapter 1"), ("came in from the docks", "Chapter 2"),
                                ("sailed on alone", "Chapter 3")):
            if marker in text:
                return json.dumps({"new": got.get("new", []), "events": EVENTS[chapter]})
        return json.dumps({"new": [], "events": []})


def run_events(monkeypatch, model=None):
    monkeypatch.setenv("CAST_EVENTS", "1")
    model = model or Events()
    rows, report, _seen = X.build(Ctx(), DOCS, model, hero="Mara Quill")
    return rows, report, model


def test_events_are_asked_for_without_naming_anyone_to_check(monkeypatch):
    _rows, _report, model = run_events(monkeypatch)
    steps = [p for p in model.prompts if "NEW TEXT:" in p]
    assert steps and all('"events"' in p and "CHECK" not in p for p in steps)


def test_a_kept_event_rewrites_the_whole_entry(monkeypatch):
    rows, report, _m = run_events(monkeypatch)
    tobin = [(o, e) for o, e in entries(rows) if e.startswith("Tobin")]
    assert tobin[-1][0] == 2
    assert tobin[-1][1] == ("Tobin Reed: The old ferryman of the harbour town, who drowned "
                            "when the ferry struck the rocks.")
    assert "1 entries rewritten" in " ".join(report)


def test_moments_reports_namesakes_and_someone_elses_lines_are_left_out(monkeypatch):
    rows, report, _m = run_events(monkeypatch)
    text = " ".join(e for _o, e in entries(rows))
    for gone in ("soaked", "becomes a merchant", "eel", "her uncle", "voyage"):
        assert gone not in text
    assert "namesake 1" in " ".join(report) and "for a while 1" in " ".join(report)


def test_a_rewrite_that_brings_in_a_new_name_is_not_used(monkeypatch):
    model = Events(rewrite="The old ferryman, drowned beside Captain Varga.")
    rows, _report, _m = run_events(monkeypatch, model)
    tobin = [e for _o, e in entries(rows) if e.startswith("Tobin")][-1]
    assert "Varga" not in tobin and "drowned" in tobin
