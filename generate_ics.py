import json
import os
import re
from datetime import datetime, timezone
import requests
from bs4 import BeautifulSoup

URL = "https://leagues.teamlinkt.com/fyha/U9Division"
TEAM_NUMBER = "11"
TEAM_NAME = "Blue Vipers"
OUTPUT_FILE = "team11.ics"
TEAM_NAMES_FILE = "team_names.json"

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
    resolved.update(load_custom_team_names())
    return resolved


def map_location(raw_rink):
    clean = raw_rink.replace("’", "'").strip()
    lower = clean.lower()

    if "willie o'ree 1" in lower:
        return "Willie O'Ree Place, Cliffe Street, Fredericton, NB, Canada", "Rink 1"
    if "willie o'ree 2" in lower:
        return "Willie O'Ree Place, Cliffe Street, Fredericton, NB, Canada", "Rink 2"
    if "grant harvey nhl" in lower:
        return "Grant-Harvey Centre", "NHL Rink"
    if "grant harvey olympic" in lower:
        return "Grant-Harvey Centre", "Olympic Rink"
    if lower == "york" or "york arena" in lower:
        return "York Arena", ""
    if "beaverbrook" in lower:
        return "Lady Beaverbrook Rink", ""

    return clean, ""


def escape_ics(text):
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def parse_schedule(soup, team_names):
    events = []

    for table in soup.find_all("table"):
        first_cell = table.find(["th", "td"])
        header_banner = first_cell.get_text(strip=True) if first_cell else ""
        is_tentative = "TENTATIVE" in header_banner.upper()

        for row in table.find_all("tr"):
            cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
            if len(cells) < 4 or "+" not in cells[0]:
                continue

            teams_raw, date_str, time_str, raw_rink = cells[0], cells[1], cells[2], cells[3]
            teams = [t.strip() for t in teams_raw.split("+")]

            if TEAM_NUMBER not in teams:
                continue

            opponent_num = teams[1] if teams[0] == TEAM_NUMBER else teams[0]
            opponent = team_names.get(opponent_num, f"Team {opponent_num}")
            location_name, rink_note = map_location(raw_rink)

            clean_date = re.sub(r"^[A-Za-z]+,\s*", "", date_str)
            now = datetime.now()
            dt_date = datetime.strptime(f"{clean_date} {now.year}", "%b %d %Y")
            if now.month >= 9 and dt_date.month <= 4:
                dt_date = dt_date.replace(year=now.year + 1)

            time_clean = time_str.replace("–", "-").replace("—", "-")
            start_part, end_part = [p.strip() for p in time_clean.split("-")]
            meridiem = "PM" if "PM" in end_part.upper() else "AM"
            if "AM" not in start_part.upper() and "PM" not in start_part.upper():
                start_part = f"{start_part} {meridiem}"

            start_dt = datetime.strptime(
                f"{dt_date.strftime('%Y-%m-%d')} {start_part}", "%Y-%m-%d %I:%M %p"
            )
            end_dt = datetime.strptime(
                f"{dt_date.strftime('%Y-%m-%d')} {end_part}", "%Y-%m-%d %I:%M %p"
            )

            status_prefix = "[TENTATIVE] " if is_tentative else ""
            status_label = "Tentative" if is_tentative else "Confirmed"
            uid = f"fyha-u9-t{TEAM_NUMBER}-{start_dt.strftime('%Y%m%dT%H%M')}@teamlinkt-sync"

            desc_parts = []
            if rink_note:
                desc_parts.append(rink_note)
            desc_parts.append(f"FYHA
