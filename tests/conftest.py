"""Gemeinsame Fixtures. Die Tests brauchen weder Paperless noch LM Studio noch macOS."""
import os
from pathlib import Path

import pytest

import llm
from fake_paperless import FakePaperless

REFERENZ = Path(__file__).resolve().parent.parent / "referenz"
GOLDEN = Path(__file__).resolve().parent / "golden"


def reference_dirs():
    return sorted(p for p in REFERENZ.glob("*_*") if (p / "ground_truth.html").exists())


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Variablen aus einer echten .env dürfen die Tests nicht beeinflussen."""
    for key in ("LMSTUDIO_URL", "LMSTUDIO_MODEL", "PAPERLESS_URL", "PAPERLESS_TOKEN", "PAPERPLUS_OUT"):
        monkeypatch.delenv(key, raising=False)


_real_load_dotenv = llm.load_dotenv


@pytest.fixture(autouse=True)
def no_real_dotenv(monkeypatch):
    """main() ruft llm.load_dotenv() ohne Argument auf – das würde die echte .env laden.
    Mit explizitem Pfad (Tests von load_dotenv selbst) läuft die echte Funktion."""
    def guarded(path=None):
        if path is not None:
            _real_load_dotenv(path)
    monkeypatch.setattr(llm, "load_dotenv", guarded)


@pytest.fixture
def paperless():
    """Laufender Fake-Paperless-Server (localhost, zufälliger Port)."""
    server = FakePaperless().start()
    yield server
    server.stop()
