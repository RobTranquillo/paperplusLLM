"""Tests für die reinen Hilfsfunktionen in paperplus.py (ohne Netzwerk)."""
import json
import subprocess

import paperplus


def test_build_content_haengt_markierung_an():
    assert paperplus.build_content("Text", "chandra-ocr-2") == "Text\n\nllm-angereichert (chandra-ocr-2)"


def test_markierung_und_queue_tag_namen():
    # Diese Namen sind Teil der Schnittstelle zu Paperless (ADR 0002/0004) und der README.
    assert paperplus.MARKER == "llm-angereichert"
    assert paperplus.QUEUE_TAG == "llm-ausstehend"


def _fake_pmset(monkeypatch, stdout):
    def run(cmd, **kwargs):
        assert cmd[:2] == ["pmset", "-g"]
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")
    monkeypatch.setattr(paperplus.subprocess, "run", run)


def test_on_ac_power_netzteil(monkeypatch):
    _fake_pmset(monkeypatch, "Now drawing from 'AC Power'\n -InternalBattery-0 100%")
    assert paperplus.on_ac_power() is True


def test_on_ac_power_akku(monkeypatch):
    _fake_pmset(monkeypatch, "Now drawing from 'Battery Power'\n -InternalBattery-0 80%")
    assert paperplus.on_ac_power() is False


def test_on_ac_power_desktop_ohne_akku(monkeypatch):
    _fake_pmset(monkeypatch, "")
    assert paperplus.on_ac_power() is True


def test_notify_uebergibt_nachricht_sicher_quotiert(monkeypatch):
    calls = []
    monkeypatch.setattr(paperplus.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    paperplus.notify('2 "Dokumente" angereichert')
    (cmd,) = calls
    assert cmd[:2] == ["osascript", "-e"]
    assert json.dumps('2 "Dokumente" angereichert') in cmd[2]
    assert 'with title "paperplusLLM"' in cmd[2]
