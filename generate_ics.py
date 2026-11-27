import json
import os
import re
from datetime import datetime, timezone
from bs4 import BeautifulSoup
import requests

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


def extract_roster
