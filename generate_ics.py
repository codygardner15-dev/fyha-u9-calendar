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

DEFAULT_ARENA_MAP = {
    "willie o'ree 1": ("Willie O'Ree Place, Cliffe Street, Fredericton, NB, Canada", "Rink 1"),
    "willie o'ree 2": ("Willie O'Ree Place, Cliffe Street, Fredericton, NB, Canada", "Rink 2"),
    "grant harvey nhl": ("Grant-Harvey Centre", "NHL Rink"),
    "grant harvey olympic": ("Grant-Harvey Centre", "Olympic Rink"),
    "york": ("York Arena", ""),
    "york arena": ("York Arena", ""),
    "beaverbrook": ("Lady Beaverbrook Rink", ""),
}

TENTATIVE_RE = re.compile(r"[\(\[]\s*TENTATIVE\s*[\)\]]|\bTENTATIVE\b", re.IGNORECASE)
DATE_BANNER_RE = re.compile(
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}\s*[-–—]\s*(?:[A-Za-z]+\s+)?\d{1,2}",
    re.IGNORECASE,
)


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


def load_locations(filepath=LOCATIONS_FILE):
    arenas = {k.lower(): v for k, v in DEFAULT_ARENA_MAP.items()}
    if not os.path.exists(filepath):
        return arenas
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            for raw_key, entry in data.items():
                key = " ".join(str(raw_key).replace("\u2019", "'").split()).strip().lower()
                if not key:
                    continue
                if isinstance(entry, dict):
                    loc = str(entry.get("location") or entry.get("name") or "").strip()
                    note = str(entry.get("note") or entry.get("description") or "").strip()
                    if loc:
                        arenas[key] = (loc, note)
                elif isinstance(entry, (list, tuple)) and len(entry) >= 1:
                    loc = str(entry[0]).strip()
                    note = str(entry[1]).strip() if len(entry) > 1 and entry[1] else ""
                    if loc:
                        arenas[key] = (loc, note)
                elif isinstance(entry, str) and entry.strip():
                    arenas[key] = (entry.strip(), "")
    except Exception as exc:
        print(f"Warning: Could not read {filepath} ({exc}). Using built-in locations.")
    return arenas


def map_location(raw_rink, locations_map=None):
    clean = " ".join(raw_rink.replace("\u2019", "'").split()).strip()
    if not clean:
        return "TBD", ""
    lower = clean.lower()
    lookup = locations_map if locations_map is not None else load_locations()

    if lower in lookup:
        return lookup[lower]

    for key, mapped in lookup.items():
        if key and key in lower:
            lookup[lower] = mapped
            return mapped

    fallback = (clean, "")
    lookup[lower] = fallback
    print(f"Unlisted arena '{clean}': add it to {LOCATIONS_FILE} to customize location/note.")
    return fallback


def escape_ics(text):
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def table_is_tentative(table):
    # 1. Inspect table caption and any header/banner rows before the first data row.
    parts = []
    caption = table.find("caption")
    if caption is not None:
        parts.append(caption.get_text(" ", strip=True))

    for row in table.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in row.find_all(["td", "th"])]
        if cells and "+" in cells[0]:
            break
        if cells:
            parts.append(" ".join(cells))

    if TENTATIVE_RE.search(" ".join(parts)):
        return True

    # 2. Walk backwards through preceding elements without crossing an earlier table,
    # checking only banner/heading-like blocks that contain a date range or TENTATIVE.
    for el in table.find_all_previous():
        if el is table:
            continue
        if el.name == "table" or any(t is not table for t in el.find_all("table")):
            break
        if el.name not in ("div", "p", "h1", "h2", "h3", "h4", "h5", "h6", "section", "header", "tr", "th"):
            continue
        text = " ".join(el.get_text(" ", strip=True).split())
        if not text or len(text) > 160:
            continue
        if DATE_BANNER_RE.search(text) or TENTATIVE_RE.search(text):
            return bool(TENTATIVE_RE.search(text))

    return False


def infer_season_year(dt_month, now=None):
    ref = now or datetime.now()
    # Hockey season runs roughly Aug/Sep through Mar/Apr.
    if ref.month >= 8:
        season_start_year = ref.year
    else:
        season_start_year = ref.year - 1

    if dt_month >= 8:
        return season_start_year
    return season_start_year + 1


def parse_schedule(soup, team_names, locations_map=None):
    raw_events = []
    now = datetime.now()
    locations = locations_map if locations_map is not None else load_locations()

    for table in soup.find_all("table"):
        is_tentative = table_is_tentative(table)

        for row in table.find_all("tr"):
            cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
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
            location_name, rink_note = map_location(raw_rink, locations)

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
    <div class="block-wrap"><div class="banner">Nov 30 - Dec 6 (Tentative)</div></div>
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
    test_output = "stress_test_output.ics"
    test_locations = "stress_test_locations.json"
    original_output = globals()["OUTPUT_FILE"]
    try:
        globals()["TEAM_NAMES_FILE"] = "__nonexistent_stress_test_team_names__.json"
        globals()["LOCATIONS_FILE"] = test_locations
        with open(test_locations, "w", encoding="utf-8") as f:
            json.dump({
                "aitken centre": {"location": "Aitken Centre", "note": "Main Pad"}
            }, f)

        names = resolve_team_names(soup)
        assert names["11"] == "Blue Vipers"
        assert names.get("13", "Team 13") == "Team 13"

        locs = load_locations(test_locations)
        york_loc, york_rink = map_location("York", locs)
        assert york_loc == "York Arena" and york_rink == ""

        new_arena_html = """
        <div>Dec 7 - Dec 13</div>
        <table>
          <tr><td>11 + 1</td><td>Saturday, Dec 12</td><td>8:00-9:00 AM</td><td>Aitken Centre</td></tr>
        </table>
        """
        new_evs = parse_schedule(BeautifulSoup(new_arena_html, "html.parser"), names, locs)
        assert len(new_evs) == 1
        assert new_evs[0]["location"] == "Aitken Centre"
        assert "Main Pad" in new_evs[0]["description"]

        evs = parse_schedule(soup, names, locs)
        assert len(evs) == 5, f"Expected 5 events, got {len(evs)}"
        assert evs[0]["summary"] == "Blue Vipers vs Silver Rockets"
        assert "(Confirmed)" in evs[0]["description"]
        assert evs[0]["location"] == "York Arena"
        assert evs[0]["uid"].endswith("-slot1@teamlinkt-sync")
        assert evs[3]["summary"] == "[TENTATIVE] Blue Vipers vs Red Wings"
        assert "(Tentative)" in evs[3]["description"]

        shifted_html = (
            sample_html.replace("9:00-10:00 AM", "8:15-9:15 AM")
            .replace("Willie O'Ree 1", "York")
            .replace("Nov 30 - Dec 6 (Tentative)", "Nov 30 - Dec 6")
        )
        shifted_evs = parse_schedule(BeautifulSoup(shifted_html, "html.parser"), names, locs)
        assert shifted_evs[3]["uid"] == evs[3]["uid"]
        assert shifted_evs[3]["summary"] == "Blue Vipers vs Red Wings"
        assert "(Confirmed)" in shifted_evs[3]["description"]

        assert escape_ics("A;B,C\\D\nE") == "A\\;B\\,C\\\\D\\nE"
        globals()["OUTPUT_FILE"] = test_output
        build_ics(evs)
        assert os.path.exists(test_output)
        with open(test_output, "rb") as f:
            ics_bytes = f.read()
        ics_text = ics_bytes.decode("utf-8")
        assert "BEGIN:VCALENDAR" in ics_text
        assert "END:VCALENDAR" in ics_text
        assert b"\r\n" in ics_bytes
    finally:
        globals()["TEAM_NAMES_FILE"] = original_names_file
        globals()["LOCATIONS_FILE"] = original_locations_file
        globals()["OUTPUT_FILE"] = original_output
        for path in (test_output, test_locations):
            if os.path.exists(path):
                os.remove(path)

    print("All stress tests passed.")


if __name__ == "__main__":
    if os.environ.get("RUN_STRESS_TESTS") == "1":
        run_stress_checks()
    resp = requests.get(URL, timeout=15)
    resp.raise_for_status()
    page_soup = BeautifulSoup(resp.text, "html.parser")
    active_names = resolve_team_names(page_soup)
    active_locations = load_locations(LOCATIONS_FILE)
    build_ics(parse_schedule(page_soup, active_names, active_locations))
