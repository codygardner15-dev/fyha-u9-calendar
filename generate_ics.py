import json
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from bs4 import BeautifulSoup
import requests

URL = "https://leagues.teamlinkt.com/fyha/U9Division"
TEAM_NUMBER = "11"
TEAM_NAME = "Blue Vipers"
OUTPUT_FILE = "team11.ics"
TEAM_NAMES_FILE = "team_names.json"
LOCATIONS_FILE = "locations.json"

DEFAULT_TEAM_NAMES = {
    "1": "Leafs",
    "2": "North Stars",
    "3": "Penguins",
    "4": "Oilers",
    "5": "Seabeasts",
    "6": "Red Wings",
    "7": "Creepers",
    "8": "Dragons",
    "9": "Hurricanes",
    "10": "Lumberjacks",
    "11": "Blue Vipers",
    "12": "Silver Rockets",
}

DEFAULT_LOCATIONS = {
    "willie o'ree 1": {
        "location": "Willie O'Ree Place, Cliffe Street, Fredericton, NB, Canada",
        "note": "Rink 1",
    },
    "willie o'ree 2": {
        "location": "Willie O'Ree Place, Cliffe Street, Fredericton, NB, Canada",
        "note": "Rink 2",
    },
    "grant harvey nhl": {
        "location": "Grant-Harvey Centre",
        "note": "NHL Rink",
    },
    "grant harvey olympic": {
        "location": "Grant-Harvey Centre",
        "note": "Olympic Rink",
    },
    "york": {
        "location": "York Arena",
        "note": "",
    },
    "york arena": {
        "location": "York Arena",
        "note": "",
    },
    "beaverbrook": {
        "location": "Lady Beaverbrook Rink",
        "note": "",
    },
    "lady beaverbrook rink": {
        "location": "Lady Beaverbrook Rink",
        "note": "",
    },
}

TENTATIVE_RE = re.compile(r"\bTENTATIVE\b", re.IGNORECASE)
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
        cleaned = {}
        for k, v in data.items():
            key_str = str(k).strip()
            val_str = str(v).strip()
            if key_str and val_str:
                cleaned[key_str] = val_str
        return cleaned
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
                loc = str(val.get("location", "")).strip()
                note = str(val.get("note", "")).strip()
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
        text = " ".join(tag.get_text(" ", strip=True).split())
        match = pattern.match(text)
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
    active_locations = locations_map if locations_map is not None else load_locations()

    if lower in active_locations:
        entry = active_locations[lower]
        return entry["location"], entry.get("note", "")

    for key, entry in active_locations.items():
        if key and key in lower:
            return entry["location"], entry.get("note", "")

    return clean, ""


def escape_ics(text):
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def table_is_tentative(table):
    # 1. Check caption and non-matchup rows inside this table first.
    caption = table.find("caption")
    if caption is not None and TENTATIVE_RE.search(caption.get_text(" ", strip=True)):
        return True

    for row in table.find_all("tr"):
        cells = [" ".join(c.get_text(" ", strip=True).split()) for c in row.find_all(["td", "th"])]
        if not cells:
            continue
        if any("+" in cell for cell in cells):
            break
        if TENTATIVE_RE.search(" ".join(cells)):
            return True

    # 2. Walk backwards up to the previous table to find the banner for this table.
    for el in table.find_all_previous():
        if el is table:
            continue
        if el.name == "table" or any(t is not table for t in el.find_all("table")):
            break
        if el.name not in (
            "div", "p", "h1", "h2", "h3", "h4", "h5", "h6",
            "section", "header", "tr", "th", "td", "span", "strong", "b",
        ):
            continue
        text = " ".join(el.get_text(" ", strip=True).split())
        if not text or len(text) > 200:
            continue
        if DATE_BANNER_RE.search(text):
            return bool(TENTATIVE_RE.search(text))

    return False


def infer_season_year(dt_month, now=None):
    ref = now or datetime.now()
    season_start_year = ref.year if ref.month >= 8 else ref.year - 1
    if dt_month >= 8:
        return season_start_year
    return season_start_year + 1


def parse_schedule(soup, team_names, locations_map=None):
    raw_events = []
    now = datetime.now()
    active_locations = locations_map if locations_map is not None else load_locations()

    for table in soup.find_all("table"):
        is_tentative = table_is_tentative(table)

        for row in table.find_all("tr"):
            cells = [" ".join(c.get_text(" ", strip=True).split()) for c in row.find_all(["td", "th"])]
            if len(cells) < 4 or "+" not in cells[0]:
                continue

            teams_raw, date_str, time_str, raw_rink = cells[0], cells[1], cells[2], cells[3]
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
            season_year = infer_season_year(month_day_dt.month, now)
            dt_date = month_day_dt.replace(year=season_year)

            time_clean = time_str.replace("\u2013", "-").replace("\u2014", "-")
            time_parts = [p.strip() for p in time_clean.split("-")]
            if len(time_parts) != 2:
                continue
            start_part, end_part = time_parts

            end_upper = end_part.upper()
            start_upper = start_part.upper()
            meridiem = "PM" if "PM" in end_upper else ("AM" if "AM" in end_upper else "AM")
            if "AM" not in start_upper and "PM" not in start_upper:
                start_part = f"{start_part} {meridiem}"
            if "AM" not in end_upper and "PM" not in end_upper:
                end_part = f"{end_part} {meridiem}"

            start_dt = datetime.strptime(
                f"{dt_date.strftime('%Y-%m-%d')} {start_part}",
                "%Y-%m-%d %I:%M %p",
            )
            end_dt = datetime.strptime(
                f"{dt_date.strftime('%Y-%m-%d')} {end_part}",
                "%Y-%m-%d %I:%M %p",
            )

            status_prefix = "[TENTATIVE] " if is_tentative else ""
            status_label = "Tentative" if is_tentative else "Confirmed"

            desc_parts = []
            if rink_note:
                desc_parts.append(rink_note)
            desc_parts.append(f"FYHA U9 Ice Time ({status_label}). Source: {URL}")
            description = " - ".join(desc_parts)

            raw_events.append({
                "date_key": start_dt.strftime("%Y%m%d"),
                "start_dt": start_dt,
                "summary": f"{status_prefix}{TEAM_NAME} vs {opponent}",
                "location": location_name,
                "dtstart": start_dt.strftime("%Y%m%dT%H%M%S"),
                "dtend": end_dt.strftime("%Y%m%dT%H%M%S"),
                "description": description,
            })

    raw_events.sort(key=lambda e: e["start_dt"])

    daily_slot_counts = defaultdict(int)
    events = []
    for ev in raw_events:
        date_key = ev["date_key"]
        daily_slot_counts[date_key] += 1
        slot_num = daily_slot_counts[date_key]
        uid = f"fyha-u9-t{TEAM_NUMBER}-{date_key}-slot{slot_num}@teamlinkt-sync"

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
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//FYHA U9 Auto-Sync//Blue Vipers 11//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:FYHA U9 - Blue Vipers (11)",
        "X-WR-TIMEZONE:America/Moncton",
        "REFRESH-INTERVAL;VALUE=DURATION:PT6H",
        "X-PUBLISHED-TTL:PT6H",
    ]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    for ev in events:
        lines.extend([
            "BEGIN:VEVENT",
            f"UID:{ev['uid']}",
            f"DTSTAMP:{stamp}",
            f"DTSTART;TZID=America/Moncton:{ev['dtstart']}",
            f"DTEND;TZID=America/Moncton:{ev['dtend']}",
            f"SUMMARY:{escape_ics(ev['summary'])}",
            f"LOCATION:{escape_ics(ev['location'])}",
            f"DESCRIPTION:{escape_ics(ev['description'])}",
            "END:VEVENT",
        ])

    lines.append("END:VCALENDAR")
    with open(OUTPUT_FILE, "w", encoding="utf-8", newline="\r\n") as f:
        f.write("\r\n".join(lines) + "\r\n")


def run_stress_checks():
    sample_html = """
    <div class="block-wrap"><div class="banner">Nov 23 - Nov 29</div></div>
    <div class="table-wrap">
      <table>
        <tr><th>Teams</th><th>Date</th><th>Time</th><th>Rink</th></tr>
        <tr><td>11 + 12</td><td>Saturday, Nov 28</td><td>7:30-8:30 AM</td><td>York</td></tr>
        <tr><td>9 + 11</td><td>Sunday, Nov 29</td><td>7:00-8:00 AM</td><td>Willie O'Ree 2</td></tr>
        <tr><td>11 + 13</td><td>Monday, Nov 30</td><td>4:30-5:30 PM</td><td>Grant Harvey NHL</td></tr>
      </table>
    </div>
    <div class="block-wrap"><div class="banner">Nov 30 - Dec 6 (TENTATIVE)</div></div>
    <div class="table-wrap">
      <table>
        <tr><th>Teams</th><th>Date</th><th>Time</th><th>Rink</th></tr>
        <tr><td>6 + 11</td><td>Saturday, Dec 5</td><td>9:00-10:00 AM</td><td>Willie O'Ree 1</td></tr>
        <tr><td>11 + 12</td><td>Sunday, Dec 6</td><td>7:00-8:00 AM</td><td>Grant Harvey Olympic</td></tr>
      </table>
    </div>
    <table>
      <tr><th>Hurricanes (9)</th><th>Silver Rockets (12)</th></tr>
    </table>
    """
    soup = BeautifulSoup(sample_html, "html.parser")

    original_names_file = globals()["TEAM_NAMES_FILE"]
    original_locations_file = globals()["LOCATIONS_FILE"]
    test_locations_file = "stress_test_locations.json"
    test_output = "stress_test_output.ics"
    original_output = globals()["OUTPUT_FILE"]

    try:
        globals()["TEAM_NAMES_FILE"] = "__nonexistent_stress_test_team_names__.json"
        globals()["LOCATIONS_FILE"] = test_locations_file
        with open(test_locations_file, "w", encoding="utf-8") as f:
            json.dump(
                {"aitken centre": {"location": "Aitken Centre",
