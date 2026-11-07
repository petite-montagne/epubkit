"""The scorecard: every check that used to take hours of reading rows."""
import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "cast_score", Path(__file__).resolve().parent.parent / "scripts" / "cast_score.py")
S = importlib.util.module_from_spec(spec)
spec.loader.exec_module(S)


def report(folder, name, rows):
    folder.mkdir(parents=True, exist_ok=True)
    lines = [name, "", "summary", ""] + ["%s\t%s\tmet\t1\t%s" % r for r in rows]
    (folder / (name + ".cast.txt")).write_text("\n".join(lines) + "\n", encoding="utf-8")


OLD = [("1:1", "Donut", "A cat owned by Beatrice."),
       ("1:2", "Princess Donut", "A cat who is a princess now."),
       ("1:3", "Shamus", "Created Ruckus."),
       ("1:4", "Bomo", "rock monster bodyguard for Carl."),
       ("1:5", "Zev", "A woman who runs the show. Zev is suspended. On a retreat now."),
       ("1:6", "Ikicha", "A crawler."),
       ("1:7", "Lucia Marr", "A girl with two big dogs."),
       ("1:8", "Lucia Mar", "A girl who fights with her dogs.")]
NEW = [("1:1", "Donut", "A cat owned by Beatrice."),
       ("1:3", "Shamus", "Someone who created Ruckus."),
       ("1:5", "Zev", "A woman who runs the show. On a retreat now."),
       ("1:7", "Lucia Marr", "A girl with two big dogs.")]


def test_each_check_finds_its_fault():
    f = S.faults(OLD)
    assert len(f["twice"]) == 2                      # Donut x2, Lucia x2
    assert any("Shamus" in e for e in f["fragment"])
    assert any("Bomo" in e for e in f["fragment"])
    assert any("Zev" in e for e in f["piled"])
    assert any("Ikicha" in e for e in f["empty"])
    assert not any(S.faults(NEW).values())
    assert not S.faults([("1:1", "Ghazi", "A wizard of glass."),
                         ("1:2", "Mrs. Ghazi", "An ooze who guards him.")])["twice"]


def test_comparing_runs_flags_a_change_that_made_things_worse(tmp_path, capsys):
    report(tmp_path / "old", "Book 01", OLD)
    report(tmp_path / "new", "Book 01", NEW)
    assert S.main([str(tmp_path / "old"), str(tmp_path / "new")]) == 0
    assert "better" in capsys.readouterr().out
    assert S.main([str(tmp_path / "new"), str(tmp_path / "old")]) == 1


def test_an_answer_key_adds_its_own_checks(tmp_path):
    report(tmp_path / "run", "Book 01", OLD + [("2:1", "Samantha", "A doll head.")])
    key = {"same": [["Donut", "Princess Donut"]], "must": {"1": ["Carl"]},
           "not_before": {"Samantha": 4}, "wrong": [{"name": "Zev", "text": "suspended"}]}
    _b, _p, k, _c = S.score(tmp_path / "run", key)
    assert [len(k[c]) for c in S.KEYED] == [1, 1, 1, 1]
    (tmp_path / "key.json").write_text(json.dumps(key))


CASE = {"book": 1, "name": "Mordecai", "also": ["Uncle Morty"],
        "says": ["cyclops|one-eyed"], "not": ["duende"], "stale": ["guild door"]}


def test_a_hard_case_is_judged_on_the_last_entry_the_book_gives():
    first = [("1:1", "Mordecai", "Guards the guild door.")]
    assert S.judge(first, CASE)[0] == "out-of-date"
    later = first + [("2:1", "Mordecai", "A one-eyed Hills Cyclops who trains them.")]
    assert S.judge(later, CASE)[0] == "pass"
    assert S.judge([("1:1", "Mordecai", "A duende the team fights.")], CASE)[0] == "wrong"
    assert S.judge([("1:1", "Mordecai", "A game guide who trains them.")], CASE)[0] == "thin"
    assert S.judge([("1:1", "Carl", "A crawler with no pants.")], CASE)[0] == "missing"
    mid = [("1:1", "Mordecai", "A duende the team fights.")] + later[1:]
    assert S.judge(mid, CASE)[0] == "wrong"
    split = later + [("2:2", "Uncle Morty", "A one-eyed Cyclops.")]
    assert S.judge(split, CASE)[0] == "twice"


def test_fewer_hard_cases_passing_is_worse(tmp_path, capsys):
    report(tmp_path / "old", "b1", [("1:1", "Mordecai", "A one-eyed Hills Cyclops guide.")])
    report(tmp_path / "new", "b1", [("1:1", "Mordecai", "A duende mob the team fights.")])
    key = tmp_path / "key.json"
    key.write_text(json.dumps({"cases": [CASE]}), encoding="utf-8")
    assert S.main([str(tmp_path / "old"), str(tmp_path / "new"), "--key", str(key)]) == 1
    out = capsys.readouterr().out
    assert "1→0 of 1 pass  WORSE" in out and "case wrong" in out


def test_a_one_word_key_name_finds_the_one_full_name_it_starts():
    case = {"book": 1, "name": "Imani", "says": ["healer"]}
    assert S.judge([("1:1", "Imani C.", "A healer with wings.")], case)[0] == "pass"
    two = [("1:1", "Imani C.", "A healer."), ("1:2", "Imani Rose", "A healer.")]
    assert S.judge(two, case)[0] == "missing"
