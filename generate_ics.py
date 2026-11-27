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
    # 1. Check caption and non-matchup rows inside the table itself.
    caption = table.find("caption")
    if caption is not None and TENTATIVE_RE.search(caption.get_text(" ", strip=True)):
        return True

    for row in table.find_all("tr"):
        cells = [" ".join(c.get_text(" ", strip=True).split()) for c in row.find_all(["td", "th"])]
        if cells and "+" in cells[0]:
            break
        if cells and TENTATIVE_RE.search(" ".join(cells)):
            return True

    # 2. Look backwards up to the previous table for the nearest date-range header/banner.
    for el in table.find_all_previous():
        if el is table:
            continue
        if el.name == "table" or any(t is not table for t in el.find_all("table")):
            break
        if el.name not in (
            "div", "p", "h1", "h2", "h3", "h4", "h5", "h6",
            "section", "header", "tr", "th", "span", "strong", "b",
        ):
            continue
        text = " ".join(el.get_text(" ", strip=True).split())
        if not text or len(text) > 200:
            continue
        if DATE_BANNER_RE.search(text):
            return bool(TENTATIVE_
