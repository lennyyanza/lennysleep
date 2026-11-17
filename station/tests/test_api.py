from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

import collector
import import_health

SAMPLE = Path(__file__).parent / "sample_export.xml"


def client():
    return TestClient(collector.app)


def test_seed_plan_today_export():
    with client() as c:
        assert c.get("/nights").json()[-1]["note"].startswith("Day 0")
        p = c.get("/plan", params={"day": "2026-11-18"}).json()
        assert p["latest"] == "2026-11-18T05:12:00" and p["asleep_by"] == "2026-11-17T21:42:00"
        assert "plan" in c.get("/today").json()
        csv = c.get("/export.csv").text
        assert csv.startswith("wake_date,") and "2026-11-17" in csv
        assert c.get("/export.csv", params={"table": "readings"}).status_code == 200
        assert c.get("/").status_code == 200


def test_serial_line_parsing():
    assert collector.parse_line("12,21.50,,3,40.2\r\n") == (12, 21.5, None, 3.0, 40.2)
    assert collector.parse_line("# header") is None and collector.parse_line("garbage") is None


def test_post_sleep_merges_and_stores_gap():
    collector.upsert("2026-11-20", asleep=datetime(2026, 11, 19, 22, 30))
    body = "hr 54\nhrv=41\nIn Bed,2026-11-19T22:00:00,2026-11-20T05:20:00\n" \
           "Core,Nov 19, 2026 at 10:20 PM,Nov 19, 2026 at 11:40 PM\nAwake,2026-11-19T23:40,2026-11-19T23:45\n" \
           "Deep,2026-11-19T23:45:00,2026-11-20T05:10:00\n"
    with client() as c:
        r = c.post("/sleep", content=body)
        assert r.status_code == 200, r.text
        row = r.json()["merged"][0]
        assert row["wake_date"] == "2026-11-20" and row["watch_onset"] == "2026-11-19T22:20:00"
        assert row["onset_gap_min"] == 10 and row["hr"] == 54 and row["hrv"] == 41
        assert row["watch_asleep_min"] == 80 + 325
        assert c.post("/sleep", content="nothing here").status_code == 400


def test_log_and_persistence():
    with client() as c:
        c.post("/log", json={"wake_date": "2026-11-21", "rushed": 2, "woke_at": "now", "note": "ok"})
        assert c.post("/log", json={"evil": 1}).status_code == 400
    with client() as c:  # fresh app on the same DB file = restart
        row = [n for n in c.get("/nights").json() if n["wake_date"] == "2026-11-21"][0]
        assert row["rushed"] == 2 and row["woke_at"] and row["note"] == "ok"


def test_import_health_sample_xml():
    rows = import_health.main(SAMPLE)
    assert [r["wake_date"] for r in rows] == ["2026-11-15", "2026-11-16"]
    assert rows[0]["watch_onset"] == "2026-11-14T22:41:00" and rows[0]["watch_asleep_min"] == 380
