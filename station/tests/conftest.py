import os
import sys
import tempfile
from pathlib import Path

os.environ.update(DB=str(Path(tempfile.mkdtemp()) / "test.db"), NO_SERIAL="1", NO_ENGINE="1", ICAL_URL="")
sys.path.insert(0, str(Path(__file__).parent.parent))


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def no_hardware(monkeypatch):
    """Tests never touch the real speakers, Spotify or backlight."""
    import wake_engine
    monkeypatch.setattr(wake_engine, "_use", lambda *a: None)
    monkeypatch.setattr(wake_engine, "_pc", lambda *a: False)
    monkeypatch.setattr(wake_engine, "SPOTIFY_URI", "")
