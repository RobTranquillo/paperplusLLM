"""Tests für die Klasse Paperless, store_document und pending_ids gegen den Fake-Server."""
import socket

import pytest

import paperplus
from fake_paperless import TOKEN


@pytest.fixture
def pl(paperless):
    return paperplus.Paperless(paperless.url, TOKEN)


# ---------------------------------------------------------------- request

def test_request_setzt_auth_und_accept_header(paperless, pl):
    pl.request("/api/tags/")
    assert paperless.last_headers["Authorization"] == f"Token {TOKEN}"
    assert paperless.last_headers["Accept"] == "application/json"


def test_request_patch_sendet_json(paperless, pl):
    paperless.add_document(1)
    pl.update(1, {"content": "neu"})
    method, path, _, body = paperless.requests[-1]
    assert (method, path, body) == ("PATCH", "/api/documents/1/", {"content": "neu"})
    assert paperless.last_headers["Content-Type"] == "application/json"
    assert paperless.docs[1]["content"] == "neu"


def test_url_mit_schraegstrich_am_ende(paperless):
    client = paperplus.Paperless(paperless.url + "/", TOKEN)
    assert client.url == paperless.url
    assert client.tag_id("x") is None


# ---------------------------------------------------------------- check_connection

def test_check_connection_ok(pl, capsys):
    pl.check_connection()
    assert "Paperless erreichbar" in capsys.readouterr().out


@pytest.mark.parametrize("status", [401, 403])
def test_check_connection_token_ungueltig(paperless, pl, status, capsys):
    paperless.force_status = status
    with pytest.raises(SystemExit) as exc:
        pl.check_connection()
    assert exc.value.code == 1
    assert f"HTTP {status}" in capsys.readouterr().err


def test_check_connection_falsches_token(paperless, capsys):
    client = paperplus.Paperless(paperless.url, "falsch")
    with pytest.raises(SystemExit):
        client.check_connection()
    assert "Token ungültig" in capsys.readouterr().err


def test_check_connection_serverfehler(paperless, pl, capsys):
    paperless.force_status = 500
    with pytest.raises(SystemExit) as exc:
        pl.check_connection()
    assert exc.value.code == 1
    assert "HTTP 500" in capsys.readouterr().err


@pytest.fixture
def offline_url():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    return f"http://127.0.0.1:{port}"  # Port ist jetzt frei -> Verbindung wird abgelehnt


def test_check_connection_offline_ist_fehler(offline_url, capsys):
    with pytest.raises(SystemExit) as exc:
        paperplus.Paperless(offline_url, TOKEN).check_connection()
    assert exc.value.code == 1
    assert "nicht erreichbar" in capsys.readouterr().err


def test_check_connection_offline_still_beenden_im_zeitplan(offline_url, capsys):
    with pytest.raises(SystemExit) as exc:
        paperplus.Paperless(offline_url, TOKEN).check_connection(quiet_if_offline=True)
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert "nichts zu tun" in captured.out and captured.err == ""


# ---------------------------------------------------------------- list_all

def test_list_all_folgt_den_seiten(paperless, pl):
    paperless.max_page_size = 2
    for i in range(1, 6):
        paperless.add_document(i)
    result = pl.list_all("/api/documents/?page_size=100&fields=id")
    assert [d["id"] for d in result] == [5, 4, 3, 2, 1]
    assert len(paperless.calls("GET", "/api/documents/")) == 3  # 2+2+1


def test_list_all_leer(pl):
    assert pl.list_all("/api/documents/?page_size=100") == []


# ---------------------------------------------------------------- tag_id

def test_tag_id_findet_vorhandenen_tag_ohne_gross_kleinschreibung(paperless, pl):
    tag = paperless.add_tag("LLM-Angereichert")
    assert pl.tag_id("llm-angereichert") == tag


def test_tag_id_fehlender_tag_ohne_create(paperless, pl):
    assert pl.tag_id("gibt-es-nicht") is None
    assert paperless.calls("POST") == []


def test_tag_id_legt_tag_an_ohne_automatische_vergabe(paperless, pl, capsys):
    new_id = pl.tag_id("neu", create=True)
    (call,) = paperless.calls("POST", "/api/tags")
    assert call[3] == {"name": "neu", "matching_algorithm": 0}  # 0 = "Keine"
    assert paperless.tags[-1]["id"] == new_id
    assert "angelegt" in capsys.readouterr().out


def test_tag_id_create_legt_vorhandenen_tag_nicht_doppelt_an(paperless, pl):
    existing = paperless.add_tag("vorhanden")
    assert pl.tag_id("vorhanden", create=True) == existing
    assert paperless.calls("POST") == []


def test_tag_id_maskiert_sonderzeichen_in_der_url(paperless, pl):
    paperless.add_tag("a&b c")
    assert pl.tag_id("a&b c") is not None


# ---------------------------------------------------------------- document / download

def test_document_und_download(paperless, pl):
    paperless.add_document(7, original=b"\xff\xd8JPEG", archive=b"%PDF")
    assert pl.document(7)["id"] == 7
    assert pl.download(7, original=True) == b"\xff\xd8JPEG"
    assert pl.download(7, original=False) == b"%PDF"
    assert paperless.calls("GET", "/api/documents/7/download")[0][2] == {"original": "true"}
    assert paperless.calls("GET", "/api/documents/7/download")[1][2] == {}


def test_unbekanntes_dokument_ist_http_fehler(pl):
    import urllib.error
    with pytest.raises(urllib.error.HTTPError) as exc:
        pl.document(999)
    assert exc.value.code == 404


# ---------------------------------------------------------------- store_document

def test_store_document_foto(paperless, pl, tmp_path, capsys):
    paperless.add_document(12, title="Rechnung / März", file_name="IMG_1.JPG", original=b"BILD")
    folder, original, doc = paperplus.store_document(pl, 12, tmp_path)
    assert folder == tmp_path / "12_Rechnung_März"
    assert original == folder / "original.jpg"
    assert original.read_bytes() == b"BILD"
    assert doc["id"] == 12
    assert "#12" in capsys.readouterr().out


def test_store_document_laedt_vorhandene_datei_nicht_erneut(paperless, pl, tmp_path):
    paperless.add_document(12, original=b"BILD")
    paperplus.store_document(pl, 12, tmp_path)
    paperplus.store_document(pl, 12, tmp_path)
    assert len(paperless.calls("GET", "/api/documents/12/download")) == 1


def test_store_document_pdf_nutzt_original(paperless, pl, tmp_path):
    paperless.add_document(3, file_name="scan.pdf", mime="application/pdf", original=b"%PDF-orig", archived=True)
    _, original, _ = paperplus.store_document(pl, 3, tmp_path)
    assert original.name == "original.pdf" and original.read_bytes() == b"%PDF-orig"


def test_store_document_office_nutzt_archivierte_pdf(paperless, pl, tmp_path):
    paperless.add_document(4, file_name="brief.docx", archived=True, archive=b"%PDF-archiv", original=b"DOCX")
    _, original, _ = paperplus.store_document(pl, 4, tmp_path)
    assert original.name == "original.pdf" and original.read_bytes() == b"%PDF-archiv"
    assert paperless.calls("GET", "/api/documents/4/download")[0][2] == {}  # ohne original=true


def test_store_document_nicht_unterstuetzt_ohne_archiv(paperless, pl, tmp_path):
    paperless.add_document(5, file_name="daten.csv", mime="text/csv")
    with pytest.raises(RuntimeError, match="nicht unterstützt"):
        paperplus.store_document(pl, 5, tmp_path)


def test_store_document_ohne_dateiname_und_titel(paperless, pl, tmp_path):
    paperless.add_document(6, title=None, file_name=None, archived=True)
    folder, original, _ = paperplus.store_document(pl, 6, tmp_path)
    assert folder.name == "6_dokument" and original.name == "original.pdf"


# ---------------------------------------------------------------- pending_ids (ADR 0004)

@pytest.fixture
def bestand(paperless):
    marker = paperless.add_tag(paperplus.MARKER)
    queue = paperless.add_tag(paperplus.QUEUE_TAG)
    paperless.add_tag("rechnung")
    d = paperless.add_document
    d(1, file_name="a.jpg")                                                    # Foto ohne Tags      -> ja
    d(2, file_name="b.jpg", tags=[marker])                                     # Foto angereichert   -> nein
    d(3, file_name="c.pdf", mime="application/pdf")                            # PDF ohne Tags       -> nein
    d(4, file_name="d.pdf", mime="application/pdf", tags=[queue])              # PDF in Warteschlange -> ja
    d(5, file_name="e.jpg", tags=[marker, queue])                              # erneut angefordert  -> ja
    d(6, file_name="f.pdf", mime="application/pdf", tags=[marker])             # PDF angereichert    -> nein
    d(7, file_name="g.csv", mime="text/csv")                                   # Text/CSV            -> nein
    d(8, file_name="h.png", mime="image/png", tags=[queue, 3])                 # PNG + Queue + Fremdtag -> ja
    d(9, file_name="i.jpg", mime=None)                                         # MIME unbekannt      -> nein
    return marker, queue


def test_pending_ids_alle_faelle(pl, bestand):
    marker, queue = bestand
    assert paperplus.pending_ids(pl, marker, queue) == [8, 5, 4, 1]


def test_pending_ids_neueste_zuerst_und_ohne_duplikate(pl, bestand):
    marker, queue = bestand
    ids = paperplus.pending_ids(pl, marker, queue)
    assert ids == sorted(set(ids), reverse=True)


def test_pending_ids_ueber_mehrere_seiten(paperless, pl, bestand):
    paperless.max_page_size = 2
    marker, queue = bestand
    assert paperplus.pending_ids(pl, marker, queue) == [8, 5, 4, 1]


def test_pending_ids_ohne_marker_tag_sind_alle_fotos_offen(pl, bestand):
    _, queue = bestand
    # Marker-Tag existiert in Paperless noch nicht -> kein Filter, alle Fotos kommen infrage
    assert paperplus.pending_ids(pl, None, queue) == [8, 5, 4, 2, 1]


def test_pending_ids_ohne_queue_tag(pl, bestand):
    marker, _ = bestand
    assert paperplus.pending_ids(pl, marker, None) == [8, 1]  # nur Fotos ohne Marker (PNG #8 zählt mit)


def test_pending_ids_leerer_bestand(pl):
    assert paperplus.pending_ids(pl, None, None) == []
