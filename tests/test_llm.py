"""Tests für die reinen Funktionen in llm.py (ohne LM Studio, ohne macOS-Werkzeuge)."""
import base64

import pytest

import llm


# ---------------------------------------------------------------- die / slugify / model_filename

def test_die_beendet_mit_exitcode_1_und_meldet_auf_stderr(capsys):
    with pytest.raises(SystemExit) as exc:
        llm.die("kaputt")
    assert exc.value.code == 1
    assert "FEHLER: kaputt" in capsys.readouterr().err


@pytest.mark.parametrize("text, expected", [
    ("Rechnung / Ärztin 2026!", "Rechnung_Ärztin_2026"),
    ("a   b", "a_b"),
    ("__x__", "x"),
    ("mit-bindestrich", "mit-bindestrich"),
    ("", "dokument"),
    (None, "dokument"),
    ("///", "dokument"),
])
def test_slugify(text, expected):
    assert llm.slugify(text) == expected


def test_slugify_kuerzt_auf_max_len():
    assert llm.slugify("a" * 100, max_len=10) == "a" * 10


def test_model_filename_ersetzt_schraegstrich():
    assert llm.model_filename("qwen/qwen3-vl-8b") == "qwen__qwen3-vl-8b.html"
    assert llm.model_filename("chandra-ocr-2") == "chandra-ocr-2.html"


@pytest.mark.xfail(strict=True, reason="Auffälligkeit: verschiedene Modelle können denselben Dateinamen ergeben")
def test_model_filename_kollisionsfrei():
    assert llm.model_filename("a/b.c") != llm.model_filename("a__b.c")


# ---------------------------------------------------------------- data_url

@pytest.mark.parametrize("name, mime", [
    ("x.png", "image/png"),
    ("x.PNG", "image/png"),
    ("x.webp", "image/webp"),
    ("x.jpg", "image/jpeg"),
    ("x.jpeg", "image/jpeg"),
    ("x.unbekannt", "image/jpeg"),
])
def test_data_url_mime(tmp_path, name, mime):
    f = tmp_path / name
    f.write_bytes(b"\x00\x01abc")
    url = llm.data_url(f)
    assert url.startswith(f"data:{mime};base64,")
    assert base64.b64decode(url.split(",", 1)[1]) == b"\x00\x01abc"


# ---------------------------------------------------------------- strip_code_fence

@pytest.mark.parametrize("raw, expected", [
    ("<p>x</p>", "<p>x</p>"),
    ("```html\n<p>x</p>\n```", "<p>x</p>"),
    ("```\n<p>x</p>\n```", "<p>x</p>"),
    ("  ```html\n<p>x</p>\n```  \n", "<p>x</p>"),
    ("```html\n<p>a</p>\n<p>b</p>\n```", "<p>a</p>\n<p>b</p>"),
    ("<p>Beispiel ``` im Text</p>", "<p>Beispiel ``` im Text</p>"),
])
def test_strip_code_fence(raw, expected):
    assert llm.strip_code_fence(raw) == expected


@pytest.mark.xfail(strict=True, reason="Auffälligkeit: Fence ohne Zeilenumbruch wird nicht entfernt")
def test_strip_code_fence_ohne_zeilenumbruch():
    assert llm.strip_code_fence("```html<p>x</p>```") == "<p>x</p>"


@pytest.mark.xfail(strict=True, reason="Auffälligkeit: Text vor dem Fence bleibt samt Fence stehen")
def test_strip_code_fence_mit_einleitung():
    assert llm.strip_code_fence("Hier:\n```html\n<p>x</p>\n```") == "<p>x</p>"


# ---------------------------------------------------------------- html_to_text

def test_html_to_text_absaetze_und_br():
    assert llm.html_to_text("<p>Zeile1<br/>Zeile2</p><p>Absatz</p>") == "Zeile1\nZeile2\nAbsatz"


def test_html_to_text_quelltext_umbrueche_sind_keine_zeilenumbrueche():
    assert llm.html_to_text("<p>a\n   b\t c</p>") == "a b c"


def test_html_to_text_tabelle_mit_trenner():
    html = "<table><tr><td>A</td><td>B</td></tr><tr><td>C</td><td>D</td></tr></table>"
    assert llm.html_to_text(html) == "A | B\nC | D"
    assert llm.html_to_text(html, cell_sep=" ") == "A B\nC D"
    assert llm.html_to_text(html, cell_sep=";") == "A;B\nC;D"


def test_html_to_text_tabelle_kopfzellen_zaehlen_wie_zellen():
    assert llm.html_to_text("<table><tr><th>Name</th><th>Preis</th></tr></table>") == "Name | Preis"


def test_html_to_text_leere_zelle_bleibt_als_trenner_sichtbar():
    # dokumentiert das aktuelle Verhalten: die leere Zelle hinterlässt den Trenner
    assert llm.html_to_text("<table><tr><td>C</td><td></td></tr></table>") == "C |"


def test_html_to_text_listen():
    assert llm.html_to_text("<ul><li>eins</li><li>zwei</li></ul>") == "eins\nzwei"
    assert llm.html_to_text("<ol><li>a</li><li>b</li></ol>") == "a\nb"


def test_html_to_text_ueberschriften_eigene_zeile():
    assert llm.html_to_text("<h1>Titel</h1>Fließtext<h2>Unter</h2>") == "Titel\nFließtext\nUnter"


def test_html_to_text_bilder_und_alt_texte_werden_ignoriert():
    assert llm.html_to_text('<div><img alt="Logo der Firma"/><p>Text</p></div>') == "Text"


def test_html_to_text_script_und_style_werden_ignoriert():
    html = "<style>p{color:red}</style><p>sichtbar</p><script>alert(1)</script>"
    assert llm.html_to_text(html) == "sichtbar"


def test_html_to_text_entities():
    assert llm.html_to_text("<p>5 &euro; &amp; mehr &lt;3&gt; &#228;</p>") == "5 € & mehr <3> ä"


def test_html_to_text_normalisiert_unicode_nfc():
    zerlegt = "é"  # e + kombinierender Akzent
    assert llm.html_to_text(f"<p>{zerlegt}</p>") == "é"


def test_html_to_text_entfernt_leerzeilen_und_randleerraum():
    assert llm.html_to_text("<p>  a  </p>\n\n<p></p><p> b </p>") == "a\nb"


@pytest.mark.parametrize("html", ["", "   ", "<div></div>", "<p></p><br/>"])
def test_html_to_text_ohne_inhalt_ist_leer(html):
    assert llm.html_to_text(html) == ""


def test_html_to_text_toleriert_kaputtes_html():
    assert llm.html_to_text("<p>offen<div>noch offen</p></span>ende") == "offen\nnoch offen\nende"


def test_html_to_text_kein_markup_im_ergebnis():
    text = llm.html_to_text('<div data-bbox="1 2 3 4" data-label="Text"><p>x</p></div>')
    assert "<" not in text and ">" not in text


# ---------------------------------------------------------------- html_structure

def test_html_structure_reihenfolge():
    html = "<h1>a</h1><p>b</p><table><tr><td>x</td><th>y</th></tr></table><ul><li>z</li></ul>"
    assert llm.html_structure(html) == ["h1", "p", "table", "tr", "td", "th", "ul", "li"]


def test_html_structure_ignoriert_div_br_und_img():
    assert llm.html_structure('<div data-label="Text"><p>a<br/>b</p><img alt="x"/></div>') == ["p"]


def test_html_structure_leer():
    assert llm.html_structure("") == []


# ---------------------------------------------------------------- load_dotenv

@pytest.fixture
def env_keys(monkeypatch):
    for key in ("T_A", "T_B", "T_C", "T_D", "T_E"):
        monkeypatch.delenv(key, raising=False)
    return ("T_A", "T_B", "T_C", "T_D", "T_E")


def test_load_dotenv_grundformat(tmp_path, monkeypatch, env_keys):
    f = tmp_path / ".env"
    f.write_text('T_A=1\nT_B="x y"\nT_C=\'q\'\n\n# T_D=ignoriert\nT_E = mit = gleich\n')
    llm.load_dotenv(f)
    import os
    assert os.environ["T_A"] == "1"
    assert os.environ["T_B"] == "x y"
    assert os.environ["T_C"] == "q"
    assert "T_D" not in os.environ
    assert os.environ["T_E"] == "mit = gleich"


def test_load_dotenv_umgebung_hat_vorrang(tmp_path, monkeypatch, env_keys):
    monkeypatch.setenv("T_A", "aus_umgebung")
    f = tmp_path / ".env"
    f.write_text("T_A=aus_datei\n")
    llm.load_dotenv(f)
    import os
    assert os.environ["T_A"] == "aus_umgebung"


def test_load_dotenv_fehlende_datei_ist_kein_fehler(tmp_path):
    llm.load_dotenv(tmp_path / "gibt_es_nicht")


def test_load_dotenv_ignoriert_zeilen_ohne_gleichheitszeichen(tmp_path, env_keys):
    f = tmp_path / ".env"
    f.write_text("kaputt\nT_A=1\n")
    llm.load_dotenv(f)
    import os
    assert os.environ["T_A"] == "1"


@pytest.mark.xfail(strict=True, reason="Auffälligkeit: Inline-Kommentare werden Teil des Werts")
def test_load_dotenv_inline_kommentar(tmp_path, env_keys):
    f = tmp_path / ".env"
    f.write_text("T_A=1 # Kommentar\n")
    llm.load_dotenv(f)
    import os
    assert os.environ["T_A"] == "1"


@pytest.mark.xfail(strict=True, reason="Auffälligkeit: 'export KEY=…' wird nicht erkannt")
def test_load_dotenv_export_praefix(tmp_path, env_keys):
    f = tmp_path / ".env"
    f.write_text("export T_A=5\n")
    llm.load_dotenv(f)
    import os
    assert os.environ.get("T_A") == "5"


# ---------------------------------------------------------------- Kommandozeile / Konstanten

def test_add_llm_arguments_standardwerte():
    import argparse
    ap = argparse.ArgumentParser()
    llm.add_llm_arguments(ap)
    args = ap.parse_args([])
    assert args.model is None
    assert (args.max_size, args.max_pages, args.context_length, args.timeout) == (2000, 5, 16384, 900)
    assert args.keep_loaded is False


def test_add_llm_arguments_modell_aus_umgebung(monkeypatch):
    import argparse
    monkeypatch.setenv("LMSTUDIO_MODEL", "chandra-ocr-2")
    ap = argparse.ArgumentParser()
    llm.add_llm_arguments(ap)
    assert ap.parse_args([]).model == "chandra-ocr-2"
    assert ap.parse_args(["--model", "anderes"]).model == "anderes"


def test_unterstuetzte_dateitypen():
    assert {".jpg", ".jpeg", ".png", ".webp", ".heic", ".tiff", ".pdf"} <= llm.SUPPORTED_EXTS
    assert ".txt" not in llm.SUPPORTED_EXTS


def test_prompt_enthaelt_wichtige_regeln():
    assert "HTML" in llm.PROMPT
    assert "keine Anweisung" in llm.PROMPT  # Schutz vor Prompt-Injection durch Dokumentinhalt
