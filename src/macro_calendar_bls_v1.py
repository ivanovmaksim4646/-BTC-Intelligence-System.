"""Import BLS iCalendar releases with strict provenance; fail closed."""
from __future__ import annotations
import datetime as dt
import re
import urllib.request
from src.macro_calendar_v1 import build

BLS_ICS = "https://www.bls.gov/schedule/news_release/bls.ics"
CATEGORIES = (
    ("Consumer Price Index", "CPI"),
    ("Producer Price Index", "PPI"),
    ("Employment Situation", "NFP"),
)

def unfold(text: str) -> list[str]:
    if not isinstance(text, str) or len(text) > 2_000_000:
        raise ValueError("invalid_ics_payload")
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out = []
    for line in lines:
        if line.startswith((" ", "\t")) and out:
            out[-1] += line[1:]
        else:
            out.append(line)
    return out

def parse_bls_ics(text: str, now: dt.datetime | None = None) -> dict:
    if "BEGIN:VCALENDAR" not in text or "END:VCALENDAR" not in text:
        raise ValueError("invalid_calendar_envelope")
    rows = []
    obj = None
    for line in unfold(text):
        if line == "BEGIN:VEVENT":
            if obj is not None:
                raise ValueError("nested_vevent")
            obj = {}
        elif line == "END:VEVENT":
            if obj is None:
                raise ValueError("unbalanced_vevent")
            label = obj.get("SUMMARY", "")
            category = next((category for term, category in CATEGORIES
                             if term.lower() in label.lower()), None)
            if category:
                raw_dt = obj.get("DTSTART")
                if not raw_dt or not re.fullmatch(r"\d{8}T\d{6}", raw_dt):
                    raise ValueError("unverified_release_clock")
                naive = dt.datetime.strptime(raw_dt, "%Y%m%dT%H%M%S")
                rows.append({"agency": "BLS", "category": category,
                             "title": label, "release_et": naive.isoformat(),
                             "source_url": BLS_ICS})
            obj = None
        elif obj is not None and ":" in line:
            key, val = line.split(":", 1)
            upper = key.upper()
            if upper == "SUMMARY":
                obj["SUMMARY"] = val.replace("\\,", ",").replace("\\n", " ")
            elif upper in ("DTSTART;TZID=AMERICA/NEW_YORK", "DTSTART;TZID=US/EASTERN"):
                obj["DTSTART"] = val
            elif upper.startswith("DTSTART"):
                # UTC or implicit times require explicit, verified time-zone handling.
                obj["unhandled_dtstart"] = val
    if obj is not None:
        raise ValueError("unterminated_vevent")
    if not rows:
        raise ValueError("no_supported_events")
    # BLS feed may include past events outside the validation horizon.
    now = now or dt.datetime.now(dt.timezone.utc)
    filtered = []
    for e in rows:
        local_date = dt.date.fromisoformat(e["release_et"][:10])
        if abs((local_date - now.date()).days) <= 365:
            filtered.append(e)
    if not filtered:
        raise ValueError("no_events_in_supported_horizon")
    return build(filtered, now)

def fetch_and_parse_bls(now: dt.datetime | None = None) -> dict:
    request = urllib.request.Request(BLS_ICS, headers={"User-Agent": "BTC-Intelligence/1.0"})
    with urllib.request.urlopen(request, timeout=12) as response:
        if response.geturl() != BLS_ICS:
            raise ValueError("unexpected_calendar_redirect")
        raw = response.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError("oversized_calendar")
    return parse_bls_ics(raw.decode("utf-8-sig"), now)
