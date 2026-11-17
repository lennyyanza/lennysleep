"""Backfill Watch sleep from an iPhone Health export: python import_health.py path/to/export.xml"""
import sys
import xml.etree.ElementTree as ET

import collector


def parse(path):
    """Yield (stage, start, end) for every sleep record, streaming (export.xml can be GBs)."""
    for _, el in ET.iterparse(path):
        if el.tag == "Record" and el.get("type") == "HKCategoryTypeIdentifierSleepAnalysis":
            stage = el.get("value", "").replace("HKCategoryValueSleepAnalysis", "")
            yield stage, collector.parse_dt(el.get("startDate")), collector.parse_dt(el.get("endDate"))
        if el.tag == "Record":
            el.clear()


def main(path):
    collector.init_db()
    rows = collector.merge_watch(list(parse(path)))
    print(f"merged {len(rows)} nights" + (f" ({rows[0]['wake_date']} .. {rows[-1]['wake_date']})" if rows else ""))
    return rows


if __name__ == "__main__":
    main(sys.argv[1])
