import re
from datetime import datetime
import requests
from bs4 import BeautifulSoup

URL = "https://leagues.teamlinkt.com/fyha/U9Division"
TEAM_NUMBER = "11"
TEAM_NAME = "Blue Vipers"
OUTPUT_FILE = "team11.ics"

# Exact Opponent names from TeamLinkt
TEAM_NAMES = {
    "1": "Team 1",
    "2": "North Stars",
    "3": "Team 3",
    "4": "Team 4",
    "5": "Team 5",
    "6": "Team 6",
    "7": "Team 7",
    "8": "Team 8",
    "9": "Team 9",
    "10": "Team 10",
    "11": "Blue Vipers",
    "12": "Team 12"
}

def map_location(raw_rink):
    # Normalize curly apostrophes and extra whitespace
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

def parse_schedule():
    resp = requests.get(URL, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
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
            opponent = TEAM_NAMES.get(opponent_num, f"Team {opponent_num}")
            location_name, rink_note = map_location(raw_rink)

            # Parse date (e.g., "Saturday, Nov 28") using current season year
            clean_date = re.sub(r"^[A-Za-z]+,\s*", "", date_str)
            now = datetime.now()
            dt_date = datetime.strptime(f"{clean_date} {now.year}", "%b %d %Y")
            if now.month >= 9 and dt_date.month <= 4:
                dt_date = dt_date.replace(year=now.year + 1)

            # Parse time range (e.g., "7:30–8:30 AM")
            time_clean = time_str.replace("–", "-").replace("—", "-")
            start_part, end_part = [p.strip() for p in time_clean.split("-")]
            meridiem = "PM" if "PM" in end_part.upper() else "AM"
            if "AM" not in start_part.upper() and "PM" not in start_part.upper():
                start_part = f"{start_part} {meridiem}"

            start_dt = datetime.strptime(f"{dt_date.strftime('%Y-%m-%d')} {start_part}", "%Y-%m-%d %I:%M %p")
            end_dt = datetime.strptime(f"{dt_date.strftime('%Y-%m-%d')} {end_part}", "%Y-%m-%d %I:%M %p")

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
                "description": description
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
        "X-PUBLISHED-TTL:PT6H"
    ]
    stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

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
            "END:VEVENT"
        ])

    lines.append("END:VCALENDAR")
    with open(OUTPUT_FILE, "w", encoding="utf-8", newline="\r\n") as f:
        f.write("\n".join(lines) + "\n")

if __name__ == "__main__":
    build_ics(parse_schedule())
