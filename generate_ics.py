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


def _date_header_nodes(soup):
    """Return date-range header nodes once each, in document order."""
    nodes = []
    for tag in soup.find_all(True):
        text = " ".join(tag.get_text(" ", strip=True).split())
        if not DATE_BANNER_RE.search(text):
            continue
        # Keep the innermost matching node to avoid treating every wrapper
        # around one header as a new section boundary.
        if any(DATE_BANNER_RE.search(" ".join(child.get_text(" ", strip=True).split()))
               for child in tag.find_all(True)):
            continue
        nodes.append(tag)
    return nodes


def _header_status(header):
    """Read status from the date header (including its small header wrapper).

    A header with no explicit status is a new, neutral/confirmed section; it
    must not inherit TENTATIVE from the preceding date range.
    """
    candidates = [header]
    for parent in header.parents:
        if getattr(parent, "name", None) in ("[document]", "html", "body"):
            break
        text = " ".join(parent.get_text(" ", strip=True).split())
        # Header components may split the range and status into sibling spans.
        # Use the nearest compact parent containing exactly this one date range.
        if (len(text) <= 180 and len(DATE_BANNER_RE.findall(text)) == 1
                and parent.find("table") is None):
            candidates.append(parent)
            break
    header_text = " ".join(" ".join(c.get_text(" ", strip=True).split()) for c in candidates)
    match = STATUS_RE.search(header_text)
    return match.group(1).capitalize() if match else "Confirmed"


def table_status(table):
    """Status in the latest date-range header before this table in document order."""
    soup = table soup if False else None
