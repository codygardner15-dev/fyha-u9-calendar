import json
import os
import re
from collections import defaultdict
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

URL = "https://leagues.teamlinkt.com/fyha/U9Division"
TEAM_NUMBER = "11"
TEAM_NAME = "Blue Vipers"
OUTPUT_FILE = "team11.ics"
TEAM_NAMES_FILE = "team_names.json"
LOCATIONS_FILE = "locations.json"

DEFAULT_TEAM_NAMES = {
    "1": "Leafs", "2": "North Stars", "3": "Penguins", "4": "Oilers",
    "5": "Seabeasts", "6": "Red Wings", "7": "Creepers", "8": "Dragons",
    "9": "Hurricanes", "10": "Lumberjacks", "11": "Blue Vipers", "12": "Silver Rockets",
}

DEFAULT_LOCATIONS = {
    "willie o'ree 1": {"location": "Willie O'Ree Place, Cliffe Street, Fredericton, NB, Canada", "note": "Rink 1"},
    "willie o'ree 2": {"location": "Willie O'Ree Place, Cliffe Street, Fredericton, NB, Canada", "note": "Rink 2"},
    "grant harvey nhl": {"location": "Grant-Harvey Centre", "note": "NHL Rink"},
    "grant harvey olympic": {"location": "Grant-Harvey Centre", "note": "Olympic Rink"},
    "york": {"location": "York Arena", "note": ""},
    "york arena": {"location": "York Arena", "note": ""},
    "beaverbrook": {"location": "Lady Beaverbrook Rink", "note": ""},
    "lady beaverbrook rink": {"location": "Lady Beaverbrook Rink", "note": ""},
}

STATUS_RE = re.compile(r"\b(CONFIRMED|TENTATIVE)\b", re.IGNORECASE)
DATE_BANNER_RE = re.compile(
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[\s\xa0]+\d{1,2}[\s\xa0]*[-–—][\s\xa0]*(?:[A-Za-z]+[\s\xa0]+)?\d{1,2}",
    re.IGNORECASE,
)


def normalize_key(text):
    return " ".join(text.replace("\u2019", "'").strip().lower().split())


def load_custom_team_names(filepath=TEAM_NAMES_FILE):
    if not os.path.exists(filepath):
        return {}
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        return {str(k).strip(): str(v).strip() for k, v in data.items() if str(k).strip() and str(v).strip()}
    except Exception as exc:
        print(f"Warning: Could not read {filepath} ({exc}). Using fallback names.")
        return {}


def load_locations(filepath=LOCATIONS_FILE):
    merged = {normalize_key(k): dict(v) for k, v in DEFAULT_LOCATIONS.items()}
    if not os.path.exists(filepath):
        return merged
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return merged
        for raw_key, val in data.items():
            key = normalize_key(str(raw_key))
            if not key:
                continue
            if isinstance(val, dict):
                loc, note = str(val.get("location", "")).strip(), str(val.get("note", "")).strip()
                if loc:
                    merged[key] = {"location": loc, "note": note}
            elif isinstance(val, str) and val.strip():
                merged[key] = {"location": val.strip(), "note": ""}
        return merged
    except Exception as exc:
        print(f"Warning: Could not read {filepath} ({exc}). Using default locations.")
        return merged


def extract_roster_names(soup):
    found = {}
    pattern = re.compile(r"^(.+?)\s*\((\d+)\)\s*$")
    for tag in soup.find_all(["th", "td", "h2", "h3", "h4", "strong", "b"]):
        match = pattern.match(" ".join(tag.get_text(" ", strip=True).split()))
        if match:
            name, num = match.group(1).strip(), match.group(2).strip()
            if name and num and num not in found:
                found[num] = name
    return found


def resolve_team_names(soup):
    resolved = dict(DEFAULT_TEAM_NAMES)
    resolved.update(extract_roster_names(soup))
    resolved.update(load_custom_team_names(TEAM_NAMES_FILE))
    return resolved


def map_location(raw_rink, locations_map=None):
    clean = " ".join(raw_rink.replace("\u2019", "'").strip().split())
    lower = clean.lower()
    active = locations_map if locations_map is not None else load_locations()
    if lower in active:
        entry = active[lower]
        return entry["location"], entry.get("note", "")
    for key, entry in active.items():
        if key and key in lower:
            return entry["location"], entry.get("note", "")
    return clean, ""


def escape_ics(text):
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def infer_season_year(dt_month, now=None):
    ref = now or datetime.now()
    season_start_year = ref.year if ref.month >= 8 else ref.year - 1
    return season_start_year if dt_month >= 8 else season_start_year + 1


def header_status(header_text):
    """An explicit status belongs to this header; otherwise the section is confirmed."""
    match = STATUS_RE.search(header_text)
    return match.group(1).capitalize() if match else "Confirmed"


def parse_schedule(soup, team_names, locations_map=None):
    """Parse headers and schedule rows in strict top-to-bottom document order."""
    raw_events = []
    now = datetime.now()
    active_locations = locations_map if locations_map is not None else load_locations()
    current_status = "Confirmed"

    for element in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "div", "section", "header", "caption", "table"]):
        if element.name == "table":
            for row in element.find_all("tr"):
                cells = [" ".join(c.get_text(" ", strip=True).split()) for c in row.find_all(["td", "th"])]

                if len(cells) == 1:
                    if DATE_BANNER_RE.search(cells[0]):
                        current_status = header_status(cells[0])
                    continue

                if len(cells) < 4 or "+" not in cells[0]:
                    continue

                teams_raw, date_str, time_str, raw_rink = cells[:4]
                if not raw_rink.strip():
                    continue

                teams = [t.strip() for t in teams_raw.split("+")]
                if TEAM_NUMBER not in teams:
                    continue

                opponent_num = teams[1] if teams[0] == TEAM_NUMBER else teams[0]
                opponent = team_names.get(opponent_num, f"Team {opponent_num}")
                location_name, rink_note = map_location(raw_rink, active_locations)

                clean_date = re.sub(r"^[A-Za-z]+,\s*", "", date_str).strip()
                month_day_dt = datetime.strptime(f"{clean_date} 2000", "%b %d %Y")
                dt_date = month_day_dt.replace(year=infer_season_year(month_day_dt.month, now))

                time_parts = [p.strip() for p in time_str.replace("\u2013", "-").replace("\u2014", "-").split("-")]
                if len(time_parts) != 2:
                    continue

                start_part, end_part = time_parts
                end_upper, start_upper = end_part.upper(), start_part.upper()
                meridiem = "PM" if "PM" in end_upper else ("AM" if "AM" in end_upper else "AM")
                if "AM" not in start_upper and "PM" not in start_upper:
                    start_part = f"{start_part} {meridiem}"
                if "AM" not in end_upper and "PM" not in end_upper:
                    end_part = f"{end_part} {meridiem}"

                start_dt = datetime.strptime(f"{dt_date:%Y-%m-%d} {start_part}", "%Y-%m-%d %I:%M %p")
                end_dt = datetime.strptime(f"{dt_date:%Y-%m-%d} {end_part}", "%Y-%m-%d %I:%M %p")

                status_prefix = "[TENTATIVE] " if current_status == "Tentative" else ""
                desc_parts = [rink_note] if rink_note else []
                desc_parts.append(f"FYHA U9 Ice Time ({current_status}). Source: {URL}")

                raw_events.append({
                    "date_key": start_dt.strftime("%Y%m%d"),
                    "start_dt": start_dt,
                    "summary": f"{status_prefix}{TEAM_NAME} vs {opponent}",
                    "location": location_name,
                    "dtstart": start_dt.strftime("%Y%m%dT%H%M%S"),
                    "dtend": end_dt.strftime("%Y%m%dT%H%M%S"),
                    "description": " - ".join(desc_parts),
                })
            continue

        text = " ".join(element.get_text(" ", strip=True).split())
        if DATE_BANNER_RE.search(text):
            current_status = header_status(text)

    raw_events.sort(key=lambda e: e["start_dt"])
    counts, events = defaultdict(int), []

    for ev in raw_events:
        date_key = ev["date_key"]
        counts[date_key] += 1
        uid = f"fyha-u9-t{TEAM_NUMBER}-{date_key}-slot{counts[date_key]}@teamlinkt-sync"
        events.append({
            "uid": uid,
            "summary": ev["summary"],
            "location": ev["location"],
            "dtstart": ev["dtstart"],
            "dtend": ev["dtend"],
            "description": ev["description"],
        })
    return events


def build_ics(events):
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//FYHA U9 Auto-Sync//Blue Vipers 11//EN",
        "CALSCALE:GREGORIAN", "METHOD:PUBLISH", "X-WR-CALNAME:FYHA U9 - Blue Vipers (11)",
        "X-WR-TIMEZONE:America/Moncton", "REFRESH-INTERVAL;VALUE=DURATION:PT6H", "X-PUBLISHED-TTL:PT6H",
        "BEGIN:VTIMEZONE", "TZID:America/Moncton",
        "BEGIN:STANDARD", "DTSTART:20071104T020000", "RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU",
        "TZOFFSETFROM:-0300", "TZOFFSETTO:-0400", "TZNAME:AST", "END:STANDARD",
        "BEGIN:DAYLIGHT", "DTSTART:20070311T020000", "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU",
        "TZOFFSETFROM:-0400", "TZOFFSETTO:-0300", "TZNAME:ADT", "END:DAYLIGHT",
        "END:VTIMEZONE",
    ]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for ev in events:
        lines.extend([
            "BEGIN:VEVENT", f"UID:{ev['uid']}", f"DTSTAMP:{stamp}",
            f"DTSTART;TZID=America/Moncton:{ev['dtstart']}", f"DTEND;TZID=America/Moncton:{ev['dtend']}",
            f"SUMMARY:{escape_ics(ev['summary'])}", f"LOCATION:{escape_ics(ev['location'])}",
            f"DESCRIPTION:{escape_ics(ev['description'])}", "END:VEVENT",
        ])
    lines.append("END:VCALENDAR")
    with open(OUTPUT_FILE, "w", encoding="utf-8", newline="\r\n") as f:
        f.write("\r\n".join(lines) + "\r\n")


def run_stress_checks():
    sample_html = """
    <h3>Nov 23 - Nov 29</h3>
    <table>
      <tr><th>Teams</th><th>Date</th><th>Time</th><th>Rink</th></tr>
      <tr><td>11 + 12</td><td>Saturday, Nov 28</td><td>7:30-8:30 AM</td><td>York</td></tr>
      <tr><td>9 + 11</td><td>Sunday, Nov 29</td><td>7:00-8:00 AM</td><td>Willie O'Ree 2</td></tr>
    </table>
    <h3>Nov 30 - Dec 6 (TENTATIVE)</h3>
    <table>
      <tr><th>Teams</th><th>Date</th><th>Time</th><th>Rink</th></tr>
      <tr><td>6 + 11</td><td>Saturday, Dec 5</td><td>9:00-10:00 AM</td><td>Willie O'Ree 1</td></tr>
      <tr><td>11 + 12</td><td>Sunday, Dec 6</td><td>7:00-8:00 AM</td><td>Grant Harvey Olympic</td></tr>
    </table>
    <h3>Dec 7 - Dec 13 (CONFIRMED)</h3>
    <table>
      <tr><th>Teams</th><th>Date</th><th>Time</th><th>Rink</th></tr>
      <tr><td>11 + 2</td><td>Saturday, Dec 12</td><td>9:00-10:00 AM</td><td>York</td></tr>
    </table>
    """
    soup = BeautifulSoup(sample_html, "html.parser")
    events = parse_schedule(soup, dict(DEFAULT_TEAM_NAMES), load_locations())
    assert len(events) == 5, f"Expected 5 events, got {len(events)}"
    assert all("(Confirmed)" in e["description"] and not e["summary"].startswith("[TENTATIVE]") for e in events[:2])
    assert all("(Tentative)" in e["description"] and e["summary"].startswith("[TENTATIVE]") for e in events[2:4])
    assert "(Confirmed)" in events[4]["description"]
    print("All stress tests passed.")


if __name__ == "__main__":
    if os.environ.get("RUN_STRESS_TESTS") == "1":
        run_stress_checks()
    response = requests.get(URL, timeout=15)
    response.raise_for_status()
    page_soup = BeautifulSoup(response.text, "html.parser")
    active_names = resolve_team_names(page_soup)
    active_locations = load_locations(LOCATIONS_FILE)
    build_ics(parse_schedule(page_soup, active_names, active_locations))
