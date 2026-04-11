"""
Apple Health XML export parser.
Parses export.xml from iPhone Health app and bulk-inserts into health_events.

Apple Health export format:
<HealthData locale="en_US">
  <Record type="HKQuantityTypeIdentifierHeartRate"
          sourceName="Apple Watch"
          value="72"
          unit="count/min"
          startDate="2024-01-15 09:23:00 +0000"
          endDate="2024-01-15 09:23:00 +0000"/>
  ...
</HealthData>
"""
from __future__ import annotations

import io
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Iterator
import structlog

from services.wearables.normalize import APPLE_TYPE_MAP, to_health_event

log = structlog.get_logger()

# Parse up to this many records per call to avoid OOM on huge exports
MAX_RECORDS = 50_000
# Only ingest data from the last N days by default
DEFAULT_LOOKBACK_DAYS = 365


def parse_apple_health_export(
    file_bytes: bytes,
    user_id: str,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> list[dict]:
    """
    Parse an Apple Health export.zip or export.xml.
    Returns a list of health_event dicts ready for Supabase insert.
    """
    xml_bytes = _extract_xml(file_bytes)
    since = _since_timestamp(lookback_days)
    events = list(_parse_xml(xml_bytes, user_id, since))
    log.info("apple_health.parsed", user_id=user_id, n_events=len(events))
    return events


def _extract_xml(file_bytes: bytes) -> bytes:
    """Accept either raw export.xml or the export.zip wrapper."""
    if file_bytes[:4] == b"PK\x03\x04":
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
            names = zf.namelist()
            xml_name = next((n for n in names if n.endswith("export.xml")), None)
            if not xml_name:
                raise ValueError("No export.xml found inside zip")
            return zf.read(xml_name)
    return file_bytes


def _since_timestamp(lookback_days: int) -> datetime:
    from datetime import timedelta
    return datetime.now(timezone.utc) - timedelta(days=lookback_days)


def _parse_xml(
    xml_bytes: bytes,
    user_id: str,
    since: datetime,
) -> Iterator[dict]:
    """Streaming iterparse — handles exports >1 GB without loading into RAM."""
    count = 0
    ctx = ET.iterparse(io.BytesIO(xml_bytes), events=("end",))

    for _, elem in ctx:
        if elem.tag != "Record":
            elem.clear()
            continue
        if count >= MAX_RECORDS:
            log.warning("apple_health.max_records_reached", limit=MAX_RECORDS)
            break

        hk_type   = elem.get("type", "")
        mapping   = APPLE_TYPE_MAP.get(hk_type)
        if not mapping:
            elem.clear()
            continue

        # Sleep: value is a category string, not a number — derive duration from start/end dates
        if hk_type == "HKCategoryTypeIdentifierSleepAnalysis":
            start = _parse_apple_date(elem.get("startDate", ""))
            end   = _parse_apple_date(elem.get("endDate", ""))
            if start and end:
                value = (end - start).total_seconds() / 3600
            else:
                elem.clear()
                continue
        else:
            raw_value = elem.get("value")
            try:
                value = float(raw_value or "")
            except (ValueError, TypeError):
                elem.clear()
                continue

        occurred_str = elem.get("startDate", "")
        occurred_dt  = _parse_apple_date(occurred_str)
        if not occurred_dt or occurred_dt < since:
            elem.clear()
            continue

        # Unit conversion: Apple uses "count/min" for HR, we store as "bpm"
        source_device = elem.get("sourceName")

        # kg conversion: Apple stores weight in lbs for US locale sometimes
        unit = elem.get("unit", mapping["unit"])
        if "lb" in unit.lower() and mapping["unit"] == "kg":
            value = value * 0.453592

        yield to_health_event(
            user_id=user_id,
            mapping=mapping,
            value=value,
            occurred_at=occurred_dt.isoformat(),
            source="apple_health",
            source_device=source_device,
            metadata={"hk_type": hk_type, "original_unit": unit},
        )
        count += 1
        elem.clear()


def _parse_apple_date(date_str: str) -> datetime | None:
    """Parse Apple Health date: '2024-01-15 09:23:00 +0000'"""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S %z")
    except ValueError:
        try:
            return datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S%z")
        except ValueError:
            return None
