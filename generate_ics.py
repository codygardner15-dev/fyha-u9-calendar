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


def map_location(raw_rink):
    clean = raw_rink.replace("\u2019", "'").strip()
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
        caption = table.find("caption")
        first_row = table.find("tr")
        prev_el = table.find_previous(["h1", "h2", "h3", "h4", "p", "div"])
        banner_text = " ".join(
            part.get_text(" ", strip=True)
            for part in (caption, first_row, prev_el)
            if part is not None
        )
        is_tentative = "TENTATIVE" in banner_text.upper()

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

            time_clean = time_str.replace("\u2013", "-").replace("\u2014", "-")
            start_part, end_part = [p.strip() for p in time_clean.split("-")]
            meridiem = "PM" if "PM" in end_part.upper() else "AM"
            if "AM" not in start_part.upper() and "PM" not in start_part.upper():
                start_part = f"{start_part} {meridiem}"

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
            uid = f"fyha-u9-t{TEAM_NUMBER}-{start_dt.strftime('%Y%m%dT%H%M')}@teamlinkt-sync"

            desc_parts = []
            if rink_note:
                desc_parts.append(rink_note)
            desc_parts.append(f"FYHA U9 Ice Time ({status_label}). Source: {URL}")
            description = " - ".join(desc_parts)

            events.append({
                "uid": uid,
                "summary": f"{status_prefix}{TEAM_NAME} vs {opponent}",
                "location": location_name,
                "dtstart": start_dt.strftime("%Y%m%dT%H%M%S"),
                "dtend": end_dt.strftime("%Y%m%dT%H%M%S"),
                "description": description,
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
        f.write("\n".join(lines) + "\n")


def run_stress_checks():
    sample_html = """
    <table>
      <tr><th>Nov 23 - Nov 29</th></tr>
      <tr><td>11 + 12</td><td>Saturday, Nov 28</td><td>7:30-8:30 AM</td><td>York</td></tr>
      <tr><td>9 + 11</td><td>Sunday, Nov 29</td><td>7:00-8:00 AM</td><td>Willie O'Ree 2</td></tr>
      <tr><td>11 + 13</td><td>Monday, Nov 30</td><td>4:30-5:30 PM</td><td>Grant Harvey NHL</td></tr>
    </table>
    <table>
      <tr><th>Nov 30 - Dec 6 (TENTATIVE)</th></tr>
      <tr><td>6 + 11</td><td>Saturday, Dec 5</td><td>9:00-10:00 AM</td><td>Willie O'Ree 1</td></tr>
      <tr><td>11 + 12</td><td>Sunday, Dec 6</td><td>7:00-8:00 AM</td><td>Grant Harvey Olympic</td></tr>
    </table>
    <table>
      <tr><th>Hurricanes (9)</th><th>Silver Rockets (12)</th></tr>
    </table>
    """
    soup = BeautifulSoup(sample_html, "html.parser")

    original_names_file = globals()["TEAM_NAMES_FILE"]
    test_output = "stress_test_output.ics"
    original_output = globals()["OUTPUT_FILE"]
    try:
        globals()["TEAM_NAMES_FILE"] = "__nonexistent_stress_test_team_names__.json"
        names = resolve_team_names(soup)
        assert names["1"] == "Leafs"
        assert names["2"] == "North Stars"
        assert names["3"] == "Penguins"
        assert names["4"] == "Oilers"
        assert names["5"] == "Seabeasts"
        assert names["6"] == "Red Wings"
        assert names["7"] == "Creepers"
        assert names["8"] == "Dragons"
        assert names["9"] == "Hurricanes", f"Expected Hurricanes, got {names['9']}"
        assert names["10"] == "Lumberjacks"
        assert names["11"] == "Blue Vipers"
        assert names["12"] == "Silver Rockets", f"Expected Silver Rockets, got {names['12']}"
        assert "13" not in names
        assert names.get("13", "Team 13") == "Team 13"

        york_loc, york_rink = map_location("York")
        assert york_loc == "York Arena" and york_rink == ""

        wor1_loc, wor1_rink = map_location("Willie O'Ree 1")
        assert wor1_loc == "Willie O'Ree Place, Cliffe Street, Fredericton, NB, Canada"
        assert wor1_rink == "Rink 1"

        wor2_loc, wor2_rink = map_location("Willie O'Ree 2")
        assert wor2_loc == "Willie O'Ree Place, Cliffe Street, Fredericton, NB, Canada"
        assert wor2_rink == "Rink 2"

        gh_nhl_loc, gh_nhl_rink = map_location("Grant Harvey NHL")
        assert gh_nhl_loc == "Grant-Harvey Centre" and gh_nhl_rink == "NHL Rink"

        gh_oly_loc, gh_oly_rink = map_location("Grant Harvey Olympic")
        assert gh_oly_loc == "Grant-Harvey Centre" and gh_oly_rink == "Olympic Rink"

        beav_loc, beav_rink = map_location("Beaverbrook")
        assert beav_loc == "Lady Beaverbrook Rink" and beav_rink == ""

        evs = parse_schedule(soup, names)
        assert len(evs) == 5, f"Expected 5 events, got {len(evs)}"
        assert evs[0]["summary"] == "Blue Vipers vs Silver Rockets"
        assert evs[0]["location"] == "York Arena"
        assert evs[1]["summary"] == "Blue Vipers vs Hurricanes"
        assert "Rink 2" in evs[1]["description"]
        assert evs[2]["summary"] == "Blue Vipers vs Team 13"
        assert "NHL Rink" in evs[2]["description"]
        assert evs[3]["summary"] == "[TENTATIVE] Blue Vipers vs Red Wings"
        assert "Rink 1" in evs[3]["description"]
        assert evs[4]["summary"] == "[TENTATIVE] Blue Vipers vs Silver Rockets"
        assert "Olympic Rink" in evs[4]["description"]

        assert escape_ics("A;B,C\\D\nE") == "A\\;B\\,C\\\\D\\nE"
        globals()["OUTPUT_FILE"] = test_output
        build_ics(evs)
        assert os.path.exists(test_output)
        with open(test_output, "r", encoding="utf-8") as f:
            ics_text = f.read()
        assert "BEGIN:VCALENDAR" in ics_text
        assert "END:VCALENDAR" in ics_text
        assert "SUMMARY:[TENTATIVE] Blue Vipers vs Red Wings" in ics_text
    finally:
        globals()["TEAM_NAMES_FILE"] = original_names_file
        globals()["OUTPUT_FILE"] = original_output
        if os.path.exists(test_output):
            os.remove(test_output)

    print("All stress tests passed.")


if __name__ == "__main__":
    if os.environ.get("RUN_STRESS_TESTS") == "1":
        run_stress_checks()
    resp = requests.get(URL, timeout=15)
    resp.raise_for_status()
    page_soup = BeautifulSoup(resp.text, "html.parser")
    active_names = resolve_team_names(page_soup)
    build_ics(parse_schedule(page_soup, active_names))
