"""Tests für die Metriken und den Ablauf von evaluate.py (ohne LM Studio)."""
import csv
import random
import sys

import pytest

import evaluate
import llm
from conftest import GOLDEN, reference_dirs


def naive_levenshtein(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


# ---------------------------------------------------------------- levenshtein

@pytest.mark.parametrize("a, b, expected", [
    ("kitten", "sitting", 3),
    ("", "", 0),
    ("", "abc", 3),
    ("abc", "", 3),
    ("abc", "abc", 0),
    ("abc", "abd", 1),
    ("abc", "xabc", 1),
    ("abcx", "abc", 1),
    ("flaw", "lawn", 2),
])
def test_levenshtein_bekannte_werte(a, b, expected):
    assert evaluate.levenshtein(a, b) == expected
    assert evaluate.levenshtein(b, a) == expected


def test_levenshtein_auf_wortlisten():
    assert evaluate.levenshtein("a b c".split(), "a x c".split()) == 1
    assert evaluate.levenshtein([], ["a"]) == 1


def test_levenshtein_entspricht_naiver_implementierung():
    rnd = random.Random(1234)
    for _ in range(300):
        a = "".join(rnd.choice("abc") for _ in range(rnd.randint(0, 12)))
        b = "".join(rnd.choice("abc") for _ in range(rnd.randint(0, 12)))
        assert evaluate.levenshtein(a, b) == naive_levenshtein(a, b), (a, b)


# ---------------------------------------------------------------- normalize / score

def test_normalize():
    assert evaluate.normalize("  a \n\t b  ") == "a b"


def test_score_identisch():
    assert evaluate.score("abc def", ["p"], "abc def", ["p"]) == {
        "zeichen": 1.0, "woerter": 1.0, "struktur": 1.0}


def test_score_zeichen_und_woerter_unterscheiden_sich():
    s = evaluate.score("hallo welt", None, "hallo welx", None)
    assert s["zeichen"] == pytest.approx(0.9)
    assert s["woerter"] == pytest.approx(0.5)
    assert s["struktur"] is None


def test_score_struktur_nur_wenn_beide_vorhanden():
    assert evaluate.score("a", ["p"], "a", None)["struktur"] is None
    assert evaluate.score("a", None, "a", ["p"])["struktur"] is None
    assert evaluate.score("a", ["p", "table"], "a", ["p"])["struktur"] == pytest.approx(2 / 3)


def test_score_wird_nicht_negativ():
    assert evaluate.score("a", None, "völlig anderer langer text", None)["zeichen"] == 0.0


def test_score_leere_referenz():
    assert evaluate.score("", [], "", [])["zeichen"] == 1.0
    assert evaluate.score("", [], "x", [])["zeichen"] == 0.0


def test_score_leere_antwort_ist_null():
    s = evaluate.score("hallo welt", None, "", None)
    assert s["zeichen"] == 0.0 and s["woerter"] == 0.0


# ---------------------------------------------------------------- read_candidate

def test_read_candidate_html(tmp_path):
    f = tmp_path / "x.html"
    f.write_text("<h1>Titel</h1><p>a<br/>b</p><table><tr><td>1</td><td>2</td></tr></table>", encoding="utf-8")
    text, struct = evaluate.read_candidate(f)
    assert text == "Titel a b 1 2"  # Zellen mit Leerzeichen, alles in einer Zeile
    assert struct == ["h1", "p", "table", "tr", "td", "td"]


def test_read_candidate_txt_hat_keine_struktur(tmp_path):
    f = tmp_path / "t.txt"
    f.write_text("  eins\n\n zwei  ", encoding="utf-8")
    assert evaluate.read_candidate(f) == ("eins zwei", None)


# ---------------------------------------------------------------- Anzeige

def test_fmt():
    assert evaluate.fmt(None) == "–"
    assert evaluate.fmt(1.0).strip() == "100.0 %"
    assert evaluate.fmt(0.9876).strip() == "98.8 %"


def test_print_table(capsys):
    evaluate.print_table([
        {"dokument": "210", "modell": "tesseract (paperless)", "zeichen": 0.35, "woerter": 0.08, "struktur": None},
        {"dokument": "210", "modell": "chandra", "zeichen": 1.0, "woerter": 0.99, "struktur": 1.0},
    ])
    out = capsys.readouterr().out
    assert "Zeichen" in out and "Wörter" in out and "Struktur" in out
    assert "tesseract (paperless)" in out and "chandra" in out
    assert "35.0 %" in out


# ---------------------------------------------------------------- Dateisystem-Ablauf

@pytest.fixture
def projekt(tmp_path, monkeypatch):
    """Temporäres Projekt mit einer Referenz '7_test'."""
    ref_dir, bench_dir = tmp_path / "referenz", tmp_path / "benchmark"
    ref = ref_dir / "7_test"
    ref.mkdir(parents=True)
    (ref / "ground_truth.html").write_text("<p>Hallo Welt</p>", encoding="utf-8")
    monkeypatch.setattr(evaluate, "REF_DIR", ref_dir)
    monkeypatch.setattr(evaluate, "BENCH_DIR", bench_dir)
    monkeypatch.setattr(llm, "PROJECT_DIR", tmp_path)
    return ref, bench_dir / "7_test"


def test_find_original_nimmt_unterstuetzte_datei(tmp_path):
    (tmp_path / "original.txt").write_text("x")
    assert evaluate.find_original(tmp_path) is None
    (tmp_path / "original.JPG").write_bytes(b"x")
    assert evaluate.find_original(tmp_path).name == "original.JPG"


def test_evaluate_ref_ohne_kandidaten(projekt):
    ref, _ = projekt
    assert evaluate.evaluate_ref(ref) == []


def test_evaluate_ref_tesseract_und_modelle(projekt):
    ref, bench = projekt
    (ref / "tesseract.txt").write_text("Hallo Wxlt", encoding="utf-8")
    bench.mkdir(parents=True)
    (bench / "modell-a.html").write_text("<p>Hallo Welt</p>", encoding="utf-8")
    (bench / "modell-b.html").write_text("<p>Hallo</p>", encoding="utf-8")
    rows = evaluate.evaluate_ref(ref)
    assert [r["modell"] for r in rows] == ["tesseract (paperless)", "modell-a", "modell-b"]
    assert all(r["dokument"] == "7" for r in rows)
    assert rows[1]["zeichen"] == 1.0 and rows[1]["struktur"] == 1.0
    assert rows[0]["struktur"] is None
    assert rows[2]["zeichen"] < 1.0


def test_write_csv(projekt, capsys):
    rows = [{"dokument": "7", "modell": "m", "zeichen": 0.98765, "woerter": 1.0, "struktur": None}]
    evaluate.write_csv(rows)
    target = evaluate.BENCH_DIR / "bewertung.csv"
    with target.open(encoding="utf-8") as f:
        read = list(csv.DictReader(f))
    assert read == [{"dokument": "7", "modell": "m", "zeichen": "0.9877", "woerter": "1.0000", "struktur": ""}]
    assert "bewertung.csv" in capsys.readouterr().out


def test_main_score_only(projekt, monkeypatch, capsys):
    ref, bench = projekt
    bench.mkdir(parents=True)
    (bench / "m.html").write_text("<p>Hallo Welt</p>", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["evaluate.py", "--score-only"])
    evaluate.main()
    out = capsys.readouterr().out
    assert "1 Referenz(en): 7" in out
    assert (evaluate.BENCH_DIR / "bewertung.csv").exists()


def test_main_filtert_nach_ids(projekt, monkeypatch, capsys):
    ref, bench = projekt
    other = evaluate.REF_DIR / "8_andere"
    other.mkdir()
    (other / "ground_truth.html").write_text("<p>x</p>", encoding="utf-8")
    bench.mkdir(parents=True)
    (bench / "m.html").write_text("<p>Hallo Welt</p>", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["evaluate.py", "--score-only", "7"])
    evaluate.main()
    assert "1 Referenz(en): 7" in capsys.readouterr().out


def test_main_ohne_referenzen_bricht_ab(projekt, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["evaluate.py", "--score-only", "999"])
    with pytest.raises(SystemExit) as exc:
        evaluate.main()
    assert exc.value.code == 1
    assert "Keine Referenzen" in capsys.readouterr().err


def test_main_ohne_ergebnisse_bricht_ab(projekt, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["evaluate.py", "--score-only"])
    with pytest.raises(SystemExit):
        evaluate.main()
    assert "Keine Ergebnisse" in capsys.readouterr().err


def test_main_ohne_modell_bricht_ab(projekt, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["evaluate.py"])
    with pytest.raises(SystemExit):
        evaluate.main()
    assert "Kein Modell" in capsys.readouterr().err


# ---------------------------------------------------------------- Golden-Tests mit referenz/

REFS = reference_dirs()


def test_referenzen_vorhanden():
    assert len(REFS) >= 4


@pytest.mark.parametrize("ref", REFS, ids=lambda p: p.name.split("_", 1)[0])
def test_ground_truth_gegen_sich_selbst_ist_100_prozent(ref):
    text, struct = evaluate.read_candidate(ref / "ground_truth.html")
    assert text
    assert evaluate.score(text, struct, text, struct) == {"zeichen": 1.0, "woerter": 1.0, "struktur": 1.0}


@pytest.mark.parametrize("ref", REFS, ids=lambda p: p.name.split("_", 1)[0])
def test_tesseract_basislinie_ist_deutlich_schlechter(ref):
    """Zweck des Projekts: Tesseract liegt bei 30–76 % (Zeichen), das LLM darüber."""
    tess = ref / evaluate.TESSERACT
    if not tess.exists():
        pytest.skip("keine tesseract.txt")
    ref_text, ref_struct = evaluate.read_candidate(ref / "ground_truth.html")
    hyp_text, hyp_struct = evaluate.read_candidate(tess)
    s = evaluate.score(ref_text, ref_struct, hyp_text, hyp_struct)
    assert s["zeichen"] < 0.85
    assert s["woerter"] < 0.6


@pytest.mark.parametrize("ref", REFS, ids=lambda p: p.name.split("_", 1)[0])
def test_gezielte_fehler_senken_die_metriken_plausibel(ref):
    """Zehn Prozent der Zeichen beschädigen -> Zeichenwert ca. 90 %, Wortwert deutlich niedriger."""
    text, _ = evaluate.read_candidate(ref / "ground_truth.html")
    chars = list(text)
    for i in range(0, len(chars), 10):
        chars[i] = "§" if chars[i] != "§" else "#"
    s = evaluate.score(text, None, "".join(chars), None)
    assert 0.85 <= s["zeichen"] <= 0.95
    assert s["woerter"] < s["zeichen"]


@pytest.mark.parametrize("ref", REFS, ids=lambda p: p.name.split("_", 1)[0])
def test_html_to_text_snapshot(ref):
    """Festgehaltener Paperless-Text je Referenz. Neu erzeugen: UPDATE_GOLDEN=1 pytest."""
    import os
    doc_id = ref.name.split("_", 1)[0]
    actual = llm.html_to_text((ref / "ground_truth.html").read_text(encoding="utf-8")) + "\n"
    golden = GOLDEN / f"{doc_id}.txt"
    if os.environ.get("UPDATE_GOLDEN"):
        golden.write_text(actual, encoding="utf-8")
    if not golden.exists():
        pytest.skip(f"{golden.name} fehlt (lokale, nicht eingecheckte Referenz) – mit UPDATE_GOLDEN=1 erzeugen")
    assert actual == golden.read_text(encoding="utf-8")


@pytest.mark.parametrize("ref", REFS, ids=lambda p: p.name.split("_", 1)[0])
def test_html_to_text_invarianten_auf_echten_dokumenten(ref):
    text = llm.html_to_text((ref / "ground_truth.html").read_text(encoding="utf-8"))
    lines = text.split("\n")
    assert all(line == line.strip() and line for line in lines)  # keine Leerzeilen, kein Randleerraum
    assert "<" not in text and "data-label" not in text
