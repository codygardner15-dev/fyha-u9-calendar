import re
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup

URL = "https://leagues.teamlinkt.com/fyha/U9Division"
TEAM_NUMBER = "11"
TEAM_NAME = "Blue Vipers (11)"
OUTPUT_FILE = "team11.ics"

TEAM_NAMES = {
    "1": "Leafs (1)", "2": "North Stars (2)", "3": "Penguins (3)",
    "4": "Oilers (4)", "5": "Seabeasts (5)", "6": "Red Wings (6)",
    "7": "Creepers (7)", "8": "Dragons (8)", "9": "Hurricanes (9)",
    "10": "Lumberjacks (10)", "11": "Blue Vipers (11)", "12": "Silver Rockets (12)"
}

def parse_schedule():
    resp = requests.get(URL, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    events = []

    for table in soup.find_all("table"):
        headers = [th.get_text(strip=True) for th in table.find_all(["th", "td"])[:4]]
        # Match tables containing the Nov 23 - Nov 29 or Nov 30 - Dec 6 headers
        header_banner = table.find(["th", "td"]).get_text(strip=True) if table.find(["th", "td"]) else ""
        is_tentative = "TENTATIVE" in header_banner.upper()

        for row in table.find_all("tr"):
            cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
            if len(cells) < 4 or "+" not in cells[0]:
                continue

            teams_raw, date_str, time_str, rink = cells[0], cells[1], cells[2], cells[3]
            teams = [t.strip() for t in teams_raw.split("+")]

            if TEAM_NUMBER not in teams:
                continue

            opponent_num = teams[1] if teams[0] == TEAM_NUMBER else teams[0]
            opponent = TEAM_NAMES.get(opponent_num, f"Team {opponent_num}")

            # Parse date (e.g., "Saturday, Nov 28") using current season year
            clean_date = re.sub(r"^[A-Za-z]+,\s*", "", date_str)
            now = datetime.now()
            dt_date = datetime.strptime(f"{clean_date} {now.year}", "%b %d %Y")
            # Roll to next year if scraping in Nov/Dec for Jan-Mar dates
            if now.month >= 9 and dt_date.month <= 4:
                dt_date = dt_date.replace(year=now.year + 1)

            # Parse time range (e.g., "7:30–8:30 AM" or "4:30–5:30 PM")
            time_clean = time_str.replace("–", "-").replace("—", "-")
            start_part, end_part = [p.strip() for p in time_clean.split("-")]
            meridiem = "PM" if "PM" in end_part.upper() else "AM"
            if "AM" not in start_part.upper() and "PM" not in start_part.upper():
                start_part = f"{start_part} {meridiem}"

            start_dt = datetime.strptime(f"{dt_date.strftime('%Y-%m-%d')} {start_part}", "%Y-%m-%d %I:%M %p")
            end_dt = datetime.strptime(f"{dt_date.strftime('%Y-%m-%d')} {end_part}", "%Y-%m-%d %I:%M %p")

            status_prefix = "[TENTATIVE] " if is_tentative else ""
            uid = f"fyha-u9-t{TEAM_NUMBER}-{start_dt.strftime('%Y%m%dT%H%M')}@teamlinkt-sync"

            events.append({
                "uid": uid,
                "summary": f"{status_prefix}U9 Hockey: {TEAM_NAME} vs {opponent}",
                "location": rink,
                "dtstart": start_dt.strftime("%Y%m%dT%H%M%S"),
                "dtend": end_dt.strftime("%Y%m%dT%H%M%S"),
                "description": f"FYHA U9 Ice Time ({'Tentative' if is_tentative else 'Confirmed'}). Source: {URL}"
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
            f"SUMMARY:{ev['summary']}",
            f"LOCATION:{ev['location']}",
            f"DESCRIPTION:{ev['description']}",
            "END:VEVENT"
        ])

    lines.append("END:VCALENDAR")
    with open(OUTPUT_FILE, "w", encoding="utf-8", newline="\r\n") as f:
        f.write("\n".join(lines) + "\n")

if __name__ == "__main__":
    build_ics(parse_schedule())
