"""Tests für llm.prepare_images und die Bildaufbereitung.

sips, pdftoppm und qlmanage (macOS bzw. poppler) werden hier durch einen Fake ersetzt. Geprüft
wird die Logik drumherum (welches Werkzeug, welche Argumente, wann verkleinert wird), nicht die
Werkzeuge selbst. Ein Test mit dem echten sips gehört auf einen macOS-Runner und fehlt bewusst.
"""
import subprocess

import pytest

import llm


class FakeTools:
    """Ersetzt subprocess.run in llm.py für sips / pdftoppm / qlmanage."""

    def __init__(self, sizes=None, pdf_pages=3, ql_creates_png=True):
        self.calls = []
        self.sizes = sizes or {}          # Dateiname -> (breite, höhe) für `sips -g`
        self.pdf_pages = pdf_pages
        self.ql_creates_png = ql_creates_png

    def __call__(self, cmd, **kwargs):
        self.calls.append(cmd)
        tool = cmd[0]
        stdout = ""
        if tool == "sips" and cmd[1] == "-g":
            w, h = self.sizes.get(cmd[-1].rsplit("/", 1)[-1], (800, 600))
            stdout = f"{cmd[-1]}\n  pixelWidth: {w}\n  pixelHeight: {h}\n"
        elif tool == "sips" and cmd[1:3] == ["-s", "format"]:
            open(cmd[cmd.index("--out") + 1], "wb").write(b"JPEG")
        elif tool == "pdftoppm":
            prefix = cmd[-1]
            last = int(cmd[cmd.index("-l") + 1])
            width = len(str(self.pdf_pages))  # wie pdftoppm: mit Nullen aufgefüllt
            for i in range(1, min(last, self.pdf_pages) + 1):
                open(f"{prefix}-{i:0{width}d}.png", "wb").write(b"PNG")
        elif tool == "qlmanage":
            if self.ql_creates_png:
                out_dir = cmd[cmd.index("-o") + 1]
                open(f"{out_dir}/{cmd[-1].rsplit('/', 1)[-1]}.png", "wb").write(b"PNG")
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")

    def named(self, tool):
        return [c for c in self.calls if c[0] == tool]


@pytest.fixture
def tools(monkeypatch):
    fake = FakeTools()
    monkeypatch.setattr(llm.subprocess, "run", fake)
    return fake


@pytest.fixture
def work(tmp_path):
    d = tmp_path / "work"
    d.mkdir()
    return d


def make(tmp_path, name):
    f = tmp_path / name
    f.write_bytes(b"DATA")
    return f


def resizes(tools):
    return [c for c in tools.named("sips") if "-Z" in c]


# ---------------------------------------------------------------- Fotos

@pytest.mark.parametrize("name", ["foto.jpg", "foto.JPEG", "scan.png", "bild.webp"])
def test_direkt_unterstuetzte_bilder_werden_kopiert(tools, work, tmp_path, name):
    pages = llm.prepare_images(make(tmp_path, name), 2000, 5, work)
    ext = "." + name.rsplit(".", 1)[1].lower()
    assert pages == [work / f"bild{ext}"]
    assert pages[0].read_bytes() == b"DATA"
    assert not any(c[1:3] == ["-s", "format"] for c in tools.named("sips"))  # keine Umwandlung


@pytest.mark.parametrize("name", ["foto.HEIC", "foto.heif", "scan.tif", "scan.tiff", "a.gif", "b.bmp"])
def test_andere_bildformate_werden_mit_sips_zu_jpeg(tools, work, tmp_path, name):
    original = make(tmp_path, name)
    pages = llm.prepare_images(original, 2000, 5, work)
    assert pages == [work / "bild.jpg"]
    convert = [c for c in tools.named("sips") if c[1:3] == ["-s", "format"]][0]
    assert convert == ["sips", "-s", "format", "jpeg", str(original), "--out", str(work / "bild.jpg")]


def test_unbekanntes_format_ist_fehler(tools, work, tmp_path):
    with pytest.raises(RuntimeError, match="nicht in ein Bild umwandeln"):
        llm.prepare_images(make(tmp_path, "daten.csv"), 2000, 5, work)


# ---------------------------------------------------------------- Verkleinern

def test_grosses_bild_wird_verkleinert(monkeypatch, work, tmp_path):
    tools = FakeTools(sizes={"bild.jpg": (4000, 3000)})
    monkeypatch.setattr(llm.subprocess, "run", tools)
    (page,) = llm.prepare_images(make(tmp_path, "foto.jpg"), 2000, 5, work)
    assert resizes(tools) == [["sips", "-Z", "2000", str(page)]]


def test_hochformat_nutzt_die_laengere_kante(monkeypatch, work, tmp_path):
    tools = FakeTools(sizes={"bild.jpg": (1000, 3000)})
    monkeypatch.setattr(llm.subprocess, "run", tools)
    llm.prepare_images(make(tmp_path, "foto.jpg"), 2000, 5, work)
    assert len(resizes(tools)) == 1


def test_kleines_bild_wird_nicht_vergroessert(tools, work, tmp_path):
    llm.prepare_images(make(tmp_path, "foto.jpg"), 2000, 5, work)  # Fake meldet 800x600
    assert resizes(tools) == []


def test_bild_genau_an_der_grenze_bleibt_unveraendert(monkeypatch, work, tmp_path):
    tools = FakeTools(sizes={"bild.jpg": (2000, 1500)})
    monkeypatch.setattr(llm.subprocess, "run", tools)
    llm.prepare_images(make(tmp_path, "foto.jpg"), 2000, 5, work)
    assert resizes(tools) == []


# ---------------------------------------------------------------- PDF

def test_pdf_mit_pdftoppm(monkeypatch, work, tmp_path):
    tools = FakeTools(pdf_pages=10)
    monkeypatch.setattr(llm.subprocess, "run", tools)
    monkeypatch.setattr(llm.shutil, "which", lambda name: "/usr/bin/pdftoppm" if name == "pdftoppm" else None)
    original = make(tmp_path, "scan.pdf")
    pages = llm.prepare_images(original, 2000, 3, work)
    (call,) = tools.named("pdftoppm")
    assert call == ["pdftoppm", "-png", "-r", "150", "-f", "1", "-l", "3", str(original), str(work / "seite")]
    assert [p.name for p in pages] == ["seite-01.png", "seite-02.png", "seite-03.png"]  # nur max_pages Seiten
    assert tools.named("qlmanage") == []


def test_pdf_seiten_bleiben_in_leserichtung(monkeypatch, work, tmp_path):
    """Mehr als 9 Seiten: die Sortierung nach Dateiname darf Seite 10 nicht vor Seite 2 stellen."""
    monkeypatch.setattr(llm.subprocess, "run", FakeTools(pdf_pages=12))
    monkeypatch.setattr(llm.shutil, "which", lambda name: "/x/pdftoppm")
    pages = llm.prepare_images(make(tmp_path, "scan.pdf"), 2000, 12, work)
    assert [p.name for p in pages] == [f"seite-{i:02d}.png" for i in range(1, 13)]


def test_pdf_ohne_pdftoppm_nutzt_quick_look_fuer_seite_1(monkeypatch, tools, work, tmp_path, capsys):
    monkeypatch.setattr(llm.shutil, "which", lambda name: None)
    original = make(tmp_path, "scan.pdf")
    pages = llm.prepare_images(original, 1500, 5, work)
    (call,) = tools.named("qlmanage")
    assert call == ["qlmanage", "-t", "-s", "1500", "-o", str(work), str(original)]
    assert len(pages) == 1
    assert "pdftoppm fehlt" in capsys.readouterr().out


def test_pdf_quick_look_ohne_ergebnis_ist_fehler(monkeypatch, work, tmp_path):
    monkeypatch.setattr(llm.subprocess, "run", FakeTools(ql_creates_png=False))
    monkeypatch.setattr(llm.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError, match="PDF konnte nicht"):
        llm.prepare_images(make(tmp_path, "scan.pdf"), 2000, 5, work)
