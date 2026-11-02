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
    _b, _p, k = S.score(tmp_path / "run", key)
    assert [len(k[c]) for c in S.KEYED] == [1, 1, 1, 1]
    (tmp_path / "key.json").write_text(json.dumps(key))
