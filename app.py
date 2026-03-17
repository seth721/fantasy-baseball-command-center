import json
import os
import requests
import streamlit as st
import pandas as pd
from datetime import datetime, timezone, timedelta
from espn_api.baseball import League


# ── FanGraphs Projection Fetcher ──────────────────────────────────────────────
FG_PROJ_SYSTEMS = {
    "Steamer": "steamer",
    "ZiPS": "zips",
    "Depth Charts": "fangraphsdc",
    "ATC": "atc",
    "THE BAT": "the-bat",
}

FG_BAT_KEEP  = ["HR", "R", "RBI", "SB", "AVG", "OBP", "SLG", "OPS", "WAR"]
FG_PIT_KEEP  = ["W", "SV", "HLD", "IP", "SO", "ERA", "WHIP", "WAR"]

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_fg_projections(proj_type: str) -> dict:
    """Return {player_name: {fg_pts, stat_key: val, ...}} from FanGraphs."""
    base = "https://www.fangraphs.com/api/projections"
    lookup = {}
    for stats, keep in [("bat", FG_BAT_KEEP), ("pit", FG_PIT_KEEP)]:
        try:
            r = requests.get(base, params={"type": proj_type, "stats": stats,
                                           "pos": "all", "team": 0, "players": 0},
                             timeout=15)
            r.raise_for_status()
            for row in r.json():
                name = row.get("PlayerName", "")
                if not name:
                    continue
                entry = {"fg_pts": round(row.get("FPTS", 0) or 0, 1)}
                for k in keep:
                    v = row.get(k if k != "SO" else "SO")
                    if v is not None:
                        entry["K" if k == "SO" else k] = (
                            round(v, 3) if k in ("AVG", "OBP", "SLG", "OPS", "ERA", "WHIP")
                            else round(v, 1)
                        )
                lookup[name] = entry
        except Exception:
            pass
    return lookup

# ── Player News Feed ───────────────────────────────────────────────────────────
_ESPN_NEWS_URL = "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/news"

@st.cache_data(ttl=300, show_spinner=False)
def fetch_news_feed() -> list:
    """Fetch MLB player news from ESPN's API — last 24 hours, newest first."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    items  = []
    try:
        r = requests.get(
            _ESPN_NEWS_URL,
            params={"limit": 100},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        r.raise_for_status()
        for article in r.json().get("articles", []):
            pub_str = article.get("published", "")
            pub_dt  = None
            if pub_str:
                try:
                    pub_dt = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
                    if pub_dt < cutoff:
                        continue
                except ValueError:
                    pass

            # Pull athlete tags from categories
            athletes = [
                {"name": c.get("description", ""), "id": c.get("athleteId")}
                for c in article.get("categories", [])
                if c.get("type") == "athlete" and c.get("description")
            ]

            # Best available article link
            link_obj = article.get("links", {})
            link = (link_obj.get("web", {}) or {}).get("href", "")

            items.append({
                "headline":    article.get("headline", ""),
                "description": article.get("description", ""),
                "published":   pub_dt,
                "athletes":    athletes,   # [{name, id}, ...]
                "link":        link,
            })
    except Exception:
        pass

    items.sort(
        key=lambda x: x["published"] or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return items

def filter_news_for_players(news_items: list, player_names) -> list:
    """Return news items whose tagged athletes match a player in player_names."""
    name_set = {n.lower() for n in player_names}
    matched  = []
    for item in news_items:
        # Prefer exact athlete-tag matching from ESPN's own data
        hit = next((a for a in item["athletes"] if a["name"].lower() in name_set), None)
        if hit is None:
            # Fallback: plain text scan for players not tagged
            text = (item["headline"] + " " + item["description"]).lower()
            hit  = next(({"name": n, "id": None} for n in player_names if n.lower() in text), None)
        if hit:
            matched.append({**item, "matched_player": hit["name"], "matched_id": hit["id"]})
    return matched

def _time_ago(dt) -> str:
    if dt is None:
        return ""
    diff    = datetime.now(timezone.utc) - dt
    minutes = int(diff.total_seconds() / 60)
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    return f"{diff.days}d ago"

def news_card_html(item: dict, photo_url: str = "") -> str:
    time_str = _time_ago(item.get("published"))
    player   = item.get("matched_player", "")
    headline = item.get("headline", "")
    desc     = item.get("description", "")
    link     = item.get("link", "")

    photo_html = (
        f"<img src='{photo_url}' style='width:54px;height:54px;border-radius:50%;"
        f"object-fit:cover;object-position:top;border:2.5px solid #1565C0;box-shadow:0 2px 8px rgba(21,101,192,0.25)'>"
        if photo_url else
        "<div style='width:54px;height:54px;border-radius:50%;background:linear-gradient(135deg,#DBEAFE,#EFF6FF);"
        "display:flex;align-items:center;justify-content:center;font-size:24px;"
        "border:2px solid rgba(21,101,192,0.2)'>⚾</div>"
    )
    read_more = (
        f"<a href='{link}' target='_blank' style='color:#1565C0;font-size:11.5px;"
        f"text-decoration:none;font-weight:700;letter-spacing:0.2px'>Read more →</a>"
        if link else ""
    )
    return f"""
<div style="background:#ffffff;border:1px solid rgba(148,163,184,0.22);
            border-radius:12px;padding:16px 18px;margin-bottom:10px;
            display:flex;gap:16px;align-items:flex-start;
            box-shadow:0 2px 12px rgba(15,52,96,0.07)">
  <div style="flex-shrink:0">{photo_html}</div>
  <div style="flex:1;min-width:0">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:5px">
      <span style="font-weight:800;color:#0F3460;font-size:14px;letter-spacing:-0.2px">{player}</span>
      <span style="color:#94A3B8;font-size:11px;white-space:nowrap;margin-left:8px;
                   font-weight:500">{time_str}</span>
    </div>
    <div style="color:#1E293B;font-size:13.5px;font-weight:600;margin-bottom:5px;
                line-height:1.4">{headline}</div>
    <div style="color:#475569;font-size:12.5px;line-height:1.55;margin-bottom:8px">{desc}</div>
    {read_more}
  </div>
</div>"""

# ── Two-Start Pitcher Fetcher ─────────────────────────────────────────────────
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_weekly_starts(week_start_str: str) -> dict:
    """
    For a Monday–Sunday window, scrape ESPN scoreboard probable starters.
    Returns {pitcher_full_name: {"starts": int, "dates": [str], "team": str, "opp": str}}
    Only pitchers with 2+ starts are included.
    """
    from datetime import datetime as _dt, timedelta as _td
    base = _dt.strptime(week_start_str, "%Y%m%d")
    counts: dict = {}
    for offset in range(7):
        day = base + _td(days=offset)
        date_str = day.strftime("%Y%m%d")
        label    = day.strftime("%a %-m/%-d")
        try:
            r = requests.get(
                "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard",
                params={"dates": date_str, "limit": 30},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=12,
            )
            r.raise_for_status()
            for event in r.json().get("events", []):
                for comp in event.get("competitions", [{}]):
                    teams = comp.get("competitors", [])
                    for idx, team_data in enumerate(teams):
                        opp = teams[1 - idx].get("team", {}).get("abbreviation", "?") if len(teams) > 1 else "?"
                        team_abbr = team_data.get("team", {}).get("abbreviation", "?")
                        for prob in team_data.get("probables", []):
                            name = (prob.get("athlete") or {}).get("fullName", "")
                            if not name:
                                continue
                            if name not in counts:
                                counts[name] = {"starts": 0, "dates": [], "team": team_abbr, "opp": []}
                            counts[name]["starts"] += 1
                            counts[name]["dates"].append(label)
                            counts[name]["opp"].append(f"vs {opp}")
        except Exception:
            pass
    return {k: v for k, v in counts.items() if v["starts"] >= 2}


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_today_starters() -> dict:
    """
    Returns {pitcher_full_name: {"team": abbr, "opp": abbr, "ha": "vs"|"@"}}
    for all probable starters in today's MLB games.
    """
    try:
        today_str = datetime.now().strftime("%Y%m%d")
        r = requests.get(
            "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard",
            params={"dates": today_str, "limit": 30},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        r.raise_for_status()
        out = {}
        for event in r.json().get("events", []):
            for comp in event.get("competitions", [{}]):
                teams = comp.get("competitors", [])
                for idx, td in enumerate(teams):
                    opp   = teams[1-idx].get("team", {}).get("abbreviation", "?") if len(teams) > 1 else "?"
                    abbr  = td.get("team", {}).get("abbreviation", "?")
                    ha    = "vs" if td.get("homeAway") == "home" else "@"
                    for prob in td.get("probables", []):
                        name = (prob.get("athlete") or {}).get("fullName", "")
                        if name:
                            out[name] = {"team": abbr, "opp": opp, "ha": ha}
        return out
    except Exception:
        return {}

# ── MLB Scoreboard (ESPN) ──────────────────────────────────────────────────────
_ESPN_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard"

@st.cache_data(ttl=60, show_spinner=False)
def fetch_mlb_scoreboard_live(date_str: str) -> list:
    """Fetch games for a given YYYYMMDD date — short TTL for live/today use."""
    return _fetch_scoreboard(date_str)

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_mlb_scoreboard(date_str: str) -> list:
    """Fetch games for a given YYYYMMDD date — longer TTL for past/future days."""
    return _fetch_scoreboard(date_str)

def _fetch_scoreboard(date_str: str) -> list:
    try:
        r = requests.get(
            _ESPN_SCOREBOARD_URL,
            params={"dates": date_str, "limit": 30},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=12,
        )
        r.raise_for_status()
        return r.json().get("events", [])
    except Exception:
        return []

def _logo(team_id, size=40):
    return (f"<img src='https://a.espncdn.com/i/teamlogos/mlb/500/{team_id}.png' "
            f"style='width:{size}px;height:{size}px;object-fit:contain;vertical-align:middle;border-radius:4px'>")

def render_game_card(event: dict) -> str:
    """Return HTML for a single game card."""
    comps = event.get("competitions", [{}])
    comp = comps[0] if comps else {}
    competitors = comp.get("competitors", [])

    # Identify home/away
    away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[0] if competitors else {})
    home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[1] if len(competitors) > 1 else {})

    def team_name(c):
        return c.get("team", {}).get("abbreviation", "?")

    def team_full(c):
        return c.get("team", {}).get("displayName", "?")

    def team_id(c):
        return c.get("team", {}).get("id", "")

    def score(c):
        return c.get("score", "–")

    def record(c):
        recs = c.get("records", [])
        return next((r.get("summary", "") for r in recs if r.get("type") == "total"), "")

    # Status
    status = event.get("status", {})
    state = status.get("type", {}).get("state", "pre")  # pre / in / post
    detail = status.get("type", {}).get("detail", "")
    display_clock = status.get("displayClock", "")

    if state == "post":
        status_badge = ("<span style='background:#22C55E;color:#fff;font-size:10px;font-weight:800;"
                        "padding:3px 9px;border-radius:20px;letter-spacing:1px'>FINAL</span>")
    elif state == "in":
        status_badge = (f"<span style='background:#EF4444;color:#fff;font-size:10px;font-weight:800;"
                        f"padding:3px 9px;border-radius:20px;letter-spacing:1px;animation:pulse 1.5s infinite'>"
                        f"🔴 LIVE &nbsp;·&nbsp; {detail}</span>")
    else:
        # Pre-game — show scheduled time
        date_str_raw = event.get("date", "")
        try:
            dt = datetime.fromisoformat(date_str_raw.replace("Z", "+00:00"))
            local_time = dt.astimezone().strftime("%-I:%M %p")
        except Exception:
            local_time = detail or "TBD"
        status_badge = (f"<span style='background:#94A3B8;color:#fff;font-size:10px;font-weight:700;"
                        f"padding:3px 9px;border-radius:20px;letter-spacing:0.5px'>{local_time}</span>")

    # Scores — bold the winner for final games
    away_score = score(away)
    home_score = score(home)
    away_won = state == "post" and str(away_score).isdigit() and str(home_score).isdigit() and int(away_score) > int(home_score)
    home_won = state == "post" and str(away_score).isdigit() and str(home_score).isdigit() and int(home_score) > int(away_score)

    away_score_style = "font-size:28px;font-weight:900;color:" + ("#0F3460" if away_won else "#64748B")
    home_score_style = "font-size:28px;font-weight:900;color:" + ("#0F3460" if home_won else "#64748B")

    # Logo images
    away_logo = _logo(team_id(away), 36)
    home_logo = _logo(team_id(home), 36)

    # Starting pitchers
    def probable(c):
        probables = c.get("probables", [])
        if probables:
            p = probables[0]
            name = p.get("athlete", {}).get("shortName", "")
            rec  = p.get("statistics", [{}])
            # Sometimes record is in a stats list
            return name
        return ""

    away_pitcher = probable(away)
    home_pitcher = probable(home)
    pitchers_html = ""
    if away_pitcher or home_pitcher:
        pitchers_html = (
            f"<div style='font-size:11px;color:#64748B;margin-top:6px;padding-top:6px;"
            f"border-top:1px solid rgba(148,163,184,0.2)'>"
            f"<span style='font-weight:700;color:#94A3B8'>SP:&nbsp;</span>"
            f"<span style='color:#475569'>{away_pitcher or '?'}</span>"
            f"<span style='color:#CBD5E1;margin:0 6px'>·</span>"
            f"<span style='color:#475569'>{home_pitcher or '?'}</span>"
            f"</div>"
        )

    # Line score
    linescores_html = ""
    away_ls = away.get("linescores", [])
    home_ls = home.get("linescores", [])
    if away_ls or home_ls:
        innings = max(len(away_ls), len(home_ls), 9)
        header_cells = "".join(
            f"<th style='min-width:22px;text-align:center;font-size:10px;color:#94A3B8;font-weight:600'>{i+1}</th>"
            for i in range(innings)
        )
        def ls_cell(ls_list, idx):
            if idx < len(ls_list):
                val = ls_list[idx].get("value", "")
                return f"<td style='text-align:center;font-size:11px;color:#334155;padding:1px 3px'>{int(val) if str(val).replace('.','',1).isdigit() else val}</td>"
            return "<td style='text-align:center;font-size:11px;color:#CBD5E1'>-</td>"

        away_cells = "".join(ls_cell(away_ls, i) for i in range(innings))
        home_cells = "".join(ls_cell(home_ls, i) for i in range(innings))

        # R / H / E
        def rhe(c):
            score_val = c.get("score", "0") or "0"
            hits_val  = next((s.get("displayValue","–") for s in c.get("statistics",[]) if s.get("abbreviation")=="H"), "–")
            errors_val = next((s.get("displayValue","–") for s in c.get("statistics",[]) if s.get("abbreviation")=="E"), "–")
            return score_val, hits_val, errors_val

        ar, ah, ae = rhe(away)
        hr2, hh, he = rhe(home)

        rhe_header = "".join(f"<th style='min-width:26px;text-align:center;font-size:10px;color:#94A3B8;font-weight:700;padding-left:8px'>{x}</th>" for x in ["R","H","E"])
        away_rhe = "".join(f"<td style='text-align:center;font-size:11px;font-weight:700;color:#0F3460;padding-left:8px'>{v}</td>" for v in [ar, ah, ae])
        home_rhe = "".join(f"<td style='text-align:center;font-size:11px;font-weight:700;color:#0F3460;padding-left:8px'>{v}</td>" for v in [hr2, hh, he])

        # Divider between innings and RHE
        div_cell = "<td style='width:6px;border-left:1px solid rgba(148,163,184,0.3)'></td>"

        linescores_html = f"""
<div style='overflow-x:auto;margin-top:8px'>
<table style='border-collapse:collapse;width:100%;min-width:300px'>
  <thead>
    <tr>
      <th style='text-align:left;font-size:10px;color:#94A3B8;font-weight:600;min-width:36px'></th>
      {header_cells}
      {div_cell}
      {rhe_header}
    </tr>
  </thead>
  <tbody>
    <tr>
      <td style='font-size:11px;font-weight:700;color:#334155;white-space:nowrap'>{team_name(away)}</td>
      {away_cells}
      {div_cell}
      {away_rhe}
    </tr>
    <tr>
      <td style='font-size:11px;font-weight:700;color:#334155;white-space:nowrap'>{team_name(home)}</td>
      {home_cells}
      {div_cell}
      {home_rhe}
    </tr>
  </tbody>
</table>
</div>"""

    # Top performer
    top_perf_html = ""
    leaders = comp.get("leaders", [])
    if leaders:
        for cat in leaders:
            cat_leaders = cat.get("leaders", [])
            if cat_leaders:
                lead = cat_leaders[0]
                name = lead.get("athlete", {}).get("shortName", "")
                disp = lead.get("displayValue", "")
                if name and disp:
                    top_perf_html = (
                        f"<div style='font-size:11px;color:#64748B;margin-top:6px;display:flex;align-items:center;gap:4px'>"
                        f"<span style='font-size:13px'>⭐</span>"
                        f"<span style='font-weight:700;color:#0F3460'>{name}</span>"
                        f"<span style='color:#94A3B8'>·</span>"
                        f"<span style='color:#475569'>{disp}</span>"
                        f"</div>"
                    )
                    break

    # Venue
    venue = comp.get("venue", {}).get("fullName", "")
    venue_html = (f"<div style='font-size:10px;color:#94A3B8;margin-top:4px'>📍 {venue}</div>"
                  if venue else "")

    # Away record / home record
    away_rec = record(away)
    home_rec = record(home)

    return f"""
<div style="background:#fff;border:1px solid rgba(148,163,184,0.22);border-radius:14px;
            padding:16px 18px;box-shadow:0 2px 14px rgba(15,52,96,0.07);margin-bottom:14px">
  <!-- Status -->
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
    {status_badge}
    {venue_html}
  </div>
  <!-- Matchup row -->
  <div style="display:flex;align-items:center;justify-content:space-between;gap:12px">
    <!-- Away -->
    <div style="display:flex;flex-direction:column;align-items:center;gap:4px;min-width:64px">
      {away_logo}
      <div style="font-size:12px;font-weight:800;color:#334155;letter-spacing:0.5px">{team_name(away)}</div>
      <div style="font-size:10px;color:#94A3B8">{away_rec}</div>
    </div>
    <!-- Scores -->
    <div style="display:flex;align-items:center;gap:16px">
      <span style="{away_score_style}">{away_score}</span>
      <span style="font-size:14px;color:#CBD5E1;font-weight:300">–</span>
      <span style="{home_score_style}">{home_score}</span>
    </div>
    <!-- Home -->
    <div style="display:flex;flex-direction:column;align-items:center;gap:4px;min-width:64px">
      {home_logo}
      <div style="font-size:12px;font-weight:800;color:#334155;letter-spacing:0.5px">{team_name(home)}</div>
      <div style="font-size:10px;color:#94A3B8">{home_rec}</div>
    </div>
  </div>
  {linescores_html}
  {top_perf_html}
  {pitchers_html}
</div>"""


# ── Baseball Spirit Animal of the Day (animal-named affiliated MiLB teams) ────
# logo_id → https://www.mlbstatic.com/team-logos/{logo_id}.svg  (MLB official CDN)
_SPIRIT_ANIMALS = [
    {"team": "Rocket City Trash Pandas",  "league": "Double-A South",    "mascot": "Sprocket",      "emoji": "🦝",  "logo_id": 559},
    {"team": "El Paso Chihuahuas",        "league": "Triple-A West",     "mascot": "Chico",         "emoji": "🐕",  "logo_id": 4904},
    {"team": "Hartford Yard Goats",       "league": "Double-A Northeast","mascot": "Chomper",       "emoji": "🐐",  "logo_id": 538},
    {"team": "Richmond Flying Squirrels", "league": "Double-A Northeast","mascot": "Nutzy",         "emoji": "🐿️", "logo_id": 3410},
    {"team": "Akron RubberDucks",         "league": "Double-A Northeast","mascot": "Orbit",         "emoji": "🦆",  "logo_id": 402},
    {"team": "Lehigh Valley IronPigs",    "league": "Triple-A East",     "mascot": "Ferrous",       "emoji": "🐷",  "logo_id": 1410},
    {"team": "Fresno Grizzlies",          "league": "Triple-A West",     "mascot": "Ted E. Grizz",  "emoji": "🐻",  "logo_id": 259},
    {"team": "Durham Bulls",              "league": "Triple-A East",     "mascot": "Wool E. Bull",  "emoji": "🐂",  "logo_id": 234},
    {"team": "Binghamton Rumble Ponies",  "league": "Double-A Northeast","mascot": "Rowdy",         "emoji": "🐴",  "logo_id": 505},
    {"team": "Erie SeaWolves",            "league": "Double-A Northeast","mascot": "C.Wolf",        "emoji": "🐺",  "logo_id": 106},
    {"team": "New Hampshire Fisher Cats", "league": "Double-A Northeast","mascot": "Slider",        "emoji": "🦡",  "logo_id": 463},
    {"team": "Portland Sea Dogs",         "league": "Double-A Northeast","mascot": "Slugger",       "emoji": "🦭",  "logo_id": 546},
    {"team": "Buffalo Bisons",            "league": "Triple-A East",     "mascot": "Buster",        "emoji": "🦬",  "logo_id": 422},
    {"team": "Wisconsin Timber Rattlers", "league": "High-A Central",    "mascot": "Fang",          "emoji": "🐍",  "logo_id": 572},
    {"team": "Down East Wood Ducks",      "league": "High-A East",       "mascot": "Waddles",       "emoji": "🦆",  "logo_id": 485},
    {"team": "Great Lakes Loons",         "league": "High-A Central",    "mascot": "Louie",         "emoji": "🦅",  "logo_id": 456},
    {"team": "Delmarva Shorebirds",       "league": "Low-A East",        "mascot": "Sandy",         "emoji": "🐦",  "logo_id": 548},
    {"team": "Jacksonville Jumbo Shrimp", "league": "Triple-A East",     "mascot": "Southpaw",      "emoji": "🦐",  "logo_id": 564},
    {"team": "Pensacola Blue Wahoos",     "league": "Double-A South",    "mascot": "Kazoo",         "emoji": "🐟",  "logo_id": 4124},
    {"team": "Greensboro Grasshoppers",   "league": "High-A East",       "mascot": "Guilford",      "emoji": "🦗",  "logo_id": 477},
    {"team": "Columbia Fireflies",        "league": "Low-A East",        "mascot": "Blaze",         "emoji": "🫧",  "logo_id": 3705},
    {"team": "Everett AquaSox",           "league": "High-A West",       "mascot": "Webbly",        "emoji": "🐸",  "logo_id": 403},
    {"team": "Toledo Mud Hens",           "league": "Triple-A East",     "mascot": "Muddy",         "emoji": "🐦",  "logo_id": 512},
    {"team": "Clearwater Threshers",      "league": "High-A East",       "mascot": "Phinley",       "emoji": "🦈",  "logo_id": 566},
    {"team": "Carolina Mudcats",          "league": "Low-A East",        "mascot": "Muddy",         "emoji": "🐱",  "logo_id": 249},
    {"team": "Gwinnett Stripers",         "league": "Triple-A East",     "mascot": "Chopper",       "emoji": "🐟",  "logo_id": 431},
    {"team": "Salt Lake Bees",            "league": "Triple-A West",     "mascot": "BeeFurious",    "emoji": "🐝",  "logo_id": 561},
    {"team": "Lynchburg Hillcats",        "league": "Low-A East",        "mascot": "Boomer",        "emoji": "🐱",  "logo_id": 481},
    {"team": "Jupiter Hammerheads",       "league": "Low-A East",        "mascot": "Hammer",        "emoji": "🦈",  "logo_id": 479},
    {"team": "Beloit Sky Carp",           "league": "High-A Central",    "mascot": "Muddy",         "emoji": "🐟",  "logo_id": 554},
    {"team": "Daytona Tortugas",          "league": "Low-A East",        "mascot": "Shelldon",      "emoji": "🐢",  "logo_id": 450},
    {"team": "Vancouver Canadians",       "league": "High-A West",       "mascot": "Bob the Bear",  "emoji": "🐻",  "logo_id": 435},
    {"team": "Visalia Rawhide",           "league": "Low-A West",        "mascot": "Cactus Jack",   "emoji": "🐄",  "logo_id": 516},
    {"team": "West Michigan Whitecaps",   "league": "High-A Central",    "mascot": "Crash",         "emoji": "🐟",  "logo_id": 582},
    {"team": "Quad Cities River Bandits", "league": "High-A Central",    "mascot": "Bandi",         "emoji": "🦝",  "logo_id": 565},
    {"team": "Augusta GreenJackets",      "league": "Low-A East",        "mascot": "Augie",         "emoji": "🪲",  "logo_id": 478},
    {"team": "Rancho Cucamonga Quakes",   "league": "Low-A West",        "mascot": "Tremor",        "emoji": "🦎",  "logo_id": 526},
    {"team": "Modesto Nuts",              "league": "Low-A West",        "mascot": "Rally",         "emoji": "🐿️", "logo_id": 515},
    {"team": "Bowling Green Hot Rods",    "league": "High-A East",       "mascot": "Axle",          "emoji": "🦎",  "logo_id": 2498},
    {"team": "Aberdeen IronBirds",        "league": "Low-A East",        "mascot": "Irby",          "emoji": "🐦",  "logo_id": 488},
]

st.set_page_config(
    page_title="Fantasy Baseball Command Center",
    page_icon="⚾",
    layout="wide"
)

# ── Styled header ─────────────────────────────────────────────────────────────
import datetime as _dt_hdr
_hdr_doy   = _dt_hdr.date.today().timetuple().tm_yday
_sa        = _SPIRIT_ANIMALS[_hdr_doy % len(_SPIRIT_ANIMALS)]
_sa_emoji  = _sa["emoji"]
_sa_team   = _sa["team"]
_sa_mascot = _sa["mascot"]
_sa_league = _sa["league"]
_sa_logo   = f"https://www.mlbstatic.com/team-logos/{_sa['logo_id']}.svg"

# Logo img with emoji fallback if CDN ever fails
_sa_img_html = (
    f'<img src="{_sa_logo}" '
    f'style="width:56px;height:56px;object-fit:contain;'
    f'filter:drop-shadow(0 2px 8px rgba(0,0,0,0.50));margin-bottom:4px" '
    f'onerror="this.style.display=\'none\';'
    f'document.getElementById(\'sa-emoji-fb\').style.display=\'block\'">'
    f'<span id="sa-emoji-fb" style="font-size:38px;line-height:1;display:none">{_sa_emoji}</span>'
)

st.markdown(f"""
<div style="
    background: linear-gradient(135deg, #0F3460 0%, #1565C0 55%, #1E88E5 100%);
    border-radius: 16px; padding: 22px 30px; margin-bottom: 12px;
    display: flex; align-items: center; justify-content: space-between;
    box-shadow: 0 6px 28px rgba(15,52,96,0.35);
">
  <div style="display:flex;align-items:center;gap:18px">
    <span style="font-size:44px;filter:drop-shadow(0 2px 6px rgba(0,0,0,0.3))">⚾</span>
    <div>
      <div style="font-size:1.65rem;font-weight:800;color:#fff;letter-spacing:-0.5px;line-height:1.15">
        Fantasy Baseball Command Center
      </div>
      <div style="font-size:0.78rem;color:rgba(255,255,255,0.7);font-weight:500;
                  letter-spacing:1.4px;text-transform:uppercase;margin-top:4px">
        2026 Season &nbsp;·&nbsp; Opening Day
      </div>
    </div>
  </div>
  <div style="text-align:center;border-left:1px solid rgba(255,255,255,0.18);
              padding-left:24px;min-width:190px">
    <div style="font-size:9.5px;font-weight:800;color:rgba(255,255,255,0.50);
                letter-spacing:1.3px;text-transform:uppercase;margin-bottom:8px">
      ⚡ Baseball Spirit Animal of the Day
    </div>
    {_sa_img_html}
    <div style="font-size:14px;font-weight:800;color:#fff;line-height:1.3;
                margin-top:6px;margin-bottom:3px">
      {_sa_team}
    </div>
    <div style="font-size:11px;color:rgba(255,255,255,0.55)">
      {_sa_mascot} &nbsp;·&nbsp; {_sa_league}
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

# ── Global theme ──────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* ── Background: stadium with light sky overlay ── */
.stApp {
    background-image: url("/app/static/dodger_stadium.jpg");
    background-size: cover;
    background-position: center;
    background-attachment: fixed;
}
.stApp::before {
    content: "";
    position: fixed;
    inset: 0;
    background: linear-gradient(160deg, rgba(224,238,255,0.84) 0%, rgba(255,255,255,0.80) 100%);
    z-index: 0;
}
.stApp > * { position: relative; z-index: 1; }

/* ── Main content: white glass card ── */
.main .block-container,
.block-container,
[data-testid="stMainBlockContainer"],
[data-testid="block-container"],
[data-testid="stAppViewContainer"] > section > div,
div.stMainBlockContainer {
    background: rgba(255, 255, 255, 0.96) !important;
    border-radius: 18px !important;
    backdrop-filter: blur(24px) !important;
    box-shadow: 0 8px 40px rgba(15,52,96,0.13) !important;
}
/* Tab panels */
[data-testid="stTabsTabPanel"],
[data-testid="stTabPanel"],
.stTabsTabPanel {
    background: rgba(248, 251, 255, 0.99) !important;
    border: 1px solid rgba(148,163,184,0.18) !important;
    border-top: none !important;
    padding: 20px 24px !important;
    border-radius: 0 0 14px 14px !important;
}

/* ── Sidebar: deep MLB navy — fully opaque, above the app overlay ── */
[data-testid="stSidebar"],
[data-testid="stSidebarContent"],
section[data-testid="stSidebar"] > div {
    background: #071A3E !important;
    background-image: none !important;
    border-right: 1px solid rgba(100,160,255,0.12) !important;
    position: relative !important;
    z-index: 10 !important;
}
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] .stMarkdown,
[data-testid="stSidebar"] .stCaption,
[data-testid="stSidebar"] span { color: #BFDBFE !important; }
[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3 { color: #ffffff !important; }
[data-testid="stSidebar"] [data-testid="stSelectbox"] > div,
[data-testid="stSidebar"] [data-testid="stNumberInput"] input,
[data-testid="stSidebar"] [data-testid="stTextInput"] input {
    background: rgba(255,255,255,0.08) !important;
    border: 1px solid rgba(100,160,255,0.3) !important;
    color: #ffffff !important;
    border-radius: 8px !important;
}

/* ── Global text on light background ── */
h1, h2, h3, h4 { color: #0D2550 !important; }
h1 { font-size: 1.7rem !important; font-weight: 800 !important; letter-spacing: -0.4px; }
h2 { font-size: 1.25rem !important; font-weight: 700 !important; }
h3 { font-size: 1.05rem !important; font-weight: 600 !important; }
p, label, .stMarkdown { color: #1E3A5F !important; }
.stCaption, [data-testid="stCaptionContainer"] { color: #64748B !important; }

/* ── Metric cards ── */
[data-testid="stMetric"] {
    background: linear-gradient(135deg, #EFF6FF 0%, #DBEAFE 100%) !important;
    border-radius: 14px !important;
    padding: 16px 20px !important;
    border: 1px solid rgba(29,78,216,0.14) !important;
    box-shadow: 0 2px 14px rgba(29,78,216,0.08) !important;
}
[data-testid="stMetricValue"] {
    font-size: 1.65rem !important;
    font-weight: 800 !important;
    color: #0D2550 !important;
}
[data-testid="stMetricLabel"] {
    font-size: 0.73rem !important;
    color: #3B5998 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.9px !important;
    font-weight: 600 !important;
}

/* ── DataFrames ── */
[data-testid="stDataFrame"] {
    background: #ffffff !important;
    border-radius: 12px !important;
    border: 1px solid rgba(148,163,184,0.22) !important;
    overflow: hidden;
    box-shadow: 0 2px 14px rgba(15,52,96,0.07) !important;
}
[data-testid="stDataFrame"] th {
    background: #0F3460 !important;
    color: #BFDBFE !important;
    font-size: 10.5px !important;
    font-weight: 700 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.9px !important;
    padding: 10px 14px !important;
    border-bottom: none !important;
    white-space: nowrap !important;
}
[data-testid="stDataFrame"] td {
    font-size: 13px !important;
    color: #1E293B !important;
    padding: 8px 14px !important;
    border-bottom: 1px solid rgba(148,163,184,0.1) !important;
    font-variant-numeric: tabular-nums !important;
}
[data-testid="stDataFrame"] tbody tr:nth-child(even) td {
    background: rgba(239,246,255,0.55) !important;
}
[data-testid="stDataFrame"] tbody tr:hover td {
    background: rgba(29,78,216,0.06) !important;
}

/* ── Tabs ── */
[data-testid="stTabs"] {
    border-bottom: 2px solid rgba(29,78,216,0.15) !important;
}
[data-testid="stTabs"] button {
    color: #64748B !important;
    font-size: 13px !important;
    font-weight: 500 !important;
    padding: 10px 18px !important;
    border-radius: 8px 8px 0 0 !important;
    transition: all 0.18s !important;
}
[data-testid="stTabs"] button:hover {
    color: #1565C0 !important;
    background: rgba(21,101,192,0.07) !important;
}
[data-testid="stTabs"] button[aria-selected="true"] {
    color: #1565C0 !important;
    background: rgba(21,101,192,0.09) !important;
    border-bottom: 3px solid #1565C0 !important;
    font-weight: 700 !important;
}

/* ── Buttons ── */
[data-testid="stButton"] > button {
    background: linear-gradient(135deg, #1565C0, #1E88E5) !important;
    color: #ffffff !important;
    border: none !important;
    border-radius: 9px !important;
    font-weight: 600 !important;
    font-size: 13px !important;
    padding: 9px 22px !important;
    box-shadow: 0 3px 10px rgba(21,101,192,0.28) !important;
    transition: all 0.18s !important;
    letter-spacing: 0.2px !important;
}
[data-testid="stButton"] > button:hover {
    background: linear-gradient(135deg, #0D47A1, #1565C0) !important;
    box-shadow: 0 5px 18px rgba(21,101,192,0.38) !important;
    transform: translateY(-1px) !important;
}

/* ── Main area inputs ── */
.main [data-testid="stSelectbox"] > div,
.main [data-testid="stNumberInput"] input,
.main [data-testid="stTextInput"] input {
    background: #F8FAFF !important;
    border: 1.5px solid rgba(21,101,192,0.22) !important;
    color: #0D2550 !important;
    border-radius: 8px !important;
}

/* ── Alerts / banners ── */
[data-testid="stAlert"] {
    border-radius: 10px !important;
    border-left-width: 4px !important;
}

/* ── Dividers ── */
hr { border-color: rgba(148,163,184,0.25) !important; }

/* ── Spinner ── */
.stSpinner > div { border-top-color: #1565C0 !important; }

/* ── Sidebar — scrollable at all resolutions ── */
[data-testid="stSidebar"] > div:first-child {
    overflow-y: auto !important;
    height: 100vh !important;
    padding-bottom: 2rem !important;
}

/* ── Tab bar — pill active tab ── */
[data-testid="stTabs"] {
    border-bottom: none !important;
    gap: 4px !important;
}
[data-testid="stTabs"] button {
    border-radius: 22px !important;
    padding: 8px 20px !important;
    font-size: 13px !important;
    font-weight: 500 !important;
    color: #64748B !important;
    border: 1.5px solid transparent !important;
    transition: all 0.20s ease !important;
    margin-bottom: 6px !important;
}
[data-testid="stTabs"] button:hover {
    color: #1565C0 !important;
    background: rgba(21,101,192,0.07) !important;
    border-color: rgba(21,101,192,0.18) !important;
}
[data-testid="stTabs"] button[aria-selected="true"] {
    background: linear-gradient(135deg, #1565C0 0%, #1E88E5 100%) !important;
    color: #ffffff !important;
    font-weight: 700 !important;
    border-color: transparent !important;
    box-shadow: 0 4px 14px rgba(21,101,192,0.38) !important;
}
[data-testid="stTabs"] [data-testid="stTabsContent"] {
    border-top: 2px solid rgba(21,101,192,0.10) !important;
    padding-top: 18px !important;
}

/* ── Section header accent bars ── */
.sec-head {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 11px 18px;
    background: linear-gradient(135deg, #F0F7FF 0%, #E8F2FF 100%);
    border-radius: 12px;
    border-left: 4px solid #1565C0;
    margin-bottom: 14px;
    margin-top: 6px;
}
.sec-head-icon { font-size: 20px; line-height: 1; }
.sec-head-title {
    font-size: 14.5px; font-weight: 800;
    color: #0F3460; letter-spacing: -0.2px;
}
.sec-head-sub {
    font-size: 11.5px; color: #64748B;
    margin-top: 1px; font-weight: 400;
}

/* ── Streak player rows ── */
.streak-card {
    display: flex; align-items: center; gap: 10px;
    border-radius: 0 9px 9px 0;
    padding: 9px 14px; margin-bottom: 5px;
    font-size: 13px; line-height: 1.4;
}
.pos-badge {
    display: inline-block;
    font-size: 10px; font-weight: 700;
    padding: 2px 7px; border-radius: 20px;
    background: rgba(21,101,192,0.12);
    color: #1565C0; letter-spacing: 0.3px;
    margin-left: 5px; vertical-align: middle;
}
.trend-up   { color: #DC2626; font-weight: 800; font-size: 14px; }
.trend-down { color: #2563EB; font-weight: 800; font-size: 14px; }

/* ── Page fade-in ── */
@keyframes ccFadeIn {
    from { opacity: 0; transform: translateY(6px); }
    to   { opacity: 1; transform: translateY(0);   }
}
.main .block-container { animation: ccFadeIn 0.30s ease-out; }

/* ── Empty state ── */
.empty-state {
    text-align: center; padding: 28px 20px;
    color: #94A3B8; font-size: 13px;
    background: #F8FAFF; border-radius: 12px;
    border: 1.5px dashed rgba(148,163,184,0.35);
}
.empty-state .es-icon { font-size: 32px; margin-bottom: 8px; }
.empty-state .es-msg  { font-weight: 600; color: #64748B; }

</style>
""", unsafe_allow_html=True)

# ── Credentials: Streamlit Cloud secrets → local file → sidebar entry ────────
CONFIG_PATH = os.path.join(os.path.dirname(__file__), ".espn_config.json")

def load_config() -> dict:
    """
    Priority order:
      1. st.secrets["espn"]  — Streamlit Cloud / production deployment
      2. .espn_config.json   — local dev convenience
      3. {}                  — user must fill in the sidebar
    """
    try:
        sec = st.secrets.get("espn", {})
        if sec.get("league_id") and sec.get("espn_s2") and sec.get("swid"):
            return {
                "league_id": int(sec["league_id"]),
                "year":      int(sec.get("year", datetime.now().year)),
                "team_id":   int(sec.get("team_id", 1)),
                "espn_s2":   str(sec["espn_s2"]),
                "swid":      str(sec["swid"]),
            }
    except Exception:
        pass
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH) as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_config(data: dict) -> None:
    """Save to local file only — no-ops silently on read-only file systems (Streamlit Cloud)."""
    try:
        with open(CONFIG_PATH, "w") as f:
            json.dump(data, f)
    except OSError:
        pass  # read-only filesystem on Streamlit Cloud — credentials come from st.secrets

cfg = load_config()

# ── Sidebar: Auth ────────────────────────────────────────────────────────────
already_connected = bool(cfg.get("league_id") and cfg.get("espn_s2") and cfg.get("swid"))

with st.sidebar:
    st.markdown(
        "<div style='font-size:18px;font-weight:800;color:#0F3460;margin-bottom:4px'>"
        "⚾ Fantasy HQ</div>"
        "<div style='font-size:12px;color:#64748B;margin-bottom:12px'>"
        "Connect your ESPN league to get started</div>",
        unsafe_allow_html=True,
    )

    with st.expander(
        "✅ Connected — click to update" if already_connected else "🔑 Connect Your ESPN League",
        expanded=not already_connected,
    ):

        # ── Step 1 ────────────────────────────────────────────────────────────
        st.markdown(
            "<div style='font-size:12px;font-weight:800;color:#1565C0;"
            "letter-spacing:0.5px;margin-bottom:6px'>STEP 1 — YOUR LEAGUE</div>",
            unsafe_allow_html=True,
        )
        league_id = st.number_input(
            "League ID",
            min_value=1, step=1,
            value=cfg.get("league_id") or None,
            placeholder="e.g. 336594",
            help="Find this in your ESPN Fantasy Baseball URL — it's the number after ?leagueId= or /leagues/",
        )
        year = st.number_input(
            "Season Year",
            min_value=2020, max_value=2030,
            value=cfg.get("year", 2026), step=1,
        )
        team_id = st.number_input(
            "My Team Number",
            min_value=1, step=1,
            value=cfg.get("team_id") or None,
            placeholder="e.g. 3",
            help="Go to your ESPN team page. Look at the URL for ?teamId=3 — that number is your team ID.",
        )

        st.divider()

        # ── Step 2 ────────────────────────────────────────────────────────────
        st.markdown(
            "<div style='font-size:12px;font-weight:800;color:#1565C0;"
            "letter-spacing:0.5px;margin-bottom:6px'>STEP 2 — ESPN LOGIN TOKENS</div>",
            unsafe_allow_html=True,
        )
        st.info(
            "ESPN requires two login tokens to access your private league. "
            "You only need to do this once — they don't expire.",
            icon="🔐",
        )

        with st.expander("📖 How to find your tokens (step by step)"):
            st.markdown(
                """
**On Chrome or Edge:**
1. Go to [fantasy.espn.com](https://fantasy.espn.com) and make sure you're **logged in**
2. Press **F12** on your keyboard (or right-click anywhere → **Inspect**)
3. Click the **Application** tab at the top of the panel that opens
4. On the left side, click **Cookies** → then click **fantasy.espn.com**
5. Find the row named **espn_s2** — click it and copy the long value
6. Find the row named **SWID** — click it and copy the value (it has curly braces `{}`)

**On Safari:**
1. Go to [fantasy.espn.com](https://fantasy.espn.com) and log in
2. In the menu bar click **Develop** → **Show Web Inspector**
   *(If you don't see Develop: Safari → Preferences → Advanced → check "Show Develop menu")*
3. Click **Storage** → **Cookies** → **fantasy.espn.com**
4. Find and copy **espn_s2** and **SWID**

**On Firefox:**
1. Go to [fantasy.espn.com](https://fantasy.espn.com) and log in
2. Press **F12** → click **Storage** tab → **Cookies** → **fantasy.espn.com**
3. Find and copy **espn_s2** and **SWID**
                """
            )

        espn_s2 = st.text_input(
            "ESPN Token  (espn_s2)",
            type="password",
            value=cfg.get("espn_s2", ""),
            placeholder="Starts with AEB...",
            help="The long token from ESPN's cookies. Starts with 'AEB' and is several hundred characters long.",
        )
        swid = st.text_input(
            "User ID  (SWID)",
            value=cfg.get("swid", ""),
            placeholder="{XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX}",
            help="Include the curly braces { } when you paste this in.",
        )

        st.divider()
        connect = st.button("🔌 Connect to My League", type="primary", use_container_width=True)

    st.divider()
    st.subheader("⚙️ Projections")

    FG_PROJ_DESCRIPTIONS = {
        "Steamer": (
            "**Steamer** — The gold standard for pre-season projections. "
            "Blends **3 years of MLB stats** (most recent weighted highest), "
            "minor-league performance, age curves, and regression to the mean. "
            "Widely considered the most accurate system overall."
        ),
        "ZiPS": (
            "**ZiPS** (Dan Szymborski) — Uses **historical comparables** to find "
            "similar players at the same age and stage of career, then projects "
            "forward. Applies heavy regression on small samples and is especially "
            "strong on **pitchers** and aging curves."
        ),
        "Depth Charts": (
            "**Depth Charts** — Takes Steamer's rate-stat projections and adjusts "
            "them for **real playing time** based on FanGraphs' current depth charts. "
            "Best when rosters are in flux — injuries, trades, or spring competitions "
            "are already baked in."
        ),
        "ATC": (
            "**ATC** (Average of the Crowd) — Averages **multiple projection systems** "
            "(Steamer, ZiPS, THE BAT, and others) to smooth out any single model's "
            "blind spots. Consistently finishes near the top in accuracy studies. "
            "A safe, consensus choice."
        ),
        "THE BAT": (
            "**THE BAT** (Derek Carty) — Leans more heavily on **recent performance "
            "and batted-ball / Statcast data** than other systems. Better at identifying "
            "breakouts and players whose skills have genuinely changed. Slightly "
            "more aggressive on upside picks."
        ),
    }

    fg_proj_label = st.selectbox(
        "Projection System",
        list(FG_PROJ_SYSTEMS.keys()),
        index=0,
    )
    desc = FG_PROJ_DESCRIPTIONS.get(fg_proj_label, "")
    st.markdown(
        f"<div style='font-size:12px; color:#b0c4de; line-height:1.6; "
        f"padding:6px 2px; white-space:normal; word-wrap:break-word;'>{desc}</div>",
        unsafe_allow_html=True,
    )

# Fallback values when expander is collapsed (widgets don't render → vars undefined)
if "connect"   not in dir(): connect   = False
if "league_id" not in dir(): league_id = cfg.get("league_id")
if "year"      not in dir(): year      = cfg.get("year", 2025)
if "team_id"   not in dir(): team_id   = cfg.get("team_id")
if "espn_s2"   not in dir(): espn_s2   = cfg.get("espn_s2", "")
if "swid"      not in dir(): swid      = cfg.get("swid", "")

# ── Session State ────────────────────────────────────────────────────────────
if "league" not in st.session_state:
    st.session_state.league = None
if "league_prev" not in st.session_state:
    st.session_state.league_prev = None

# ── Auto-connect on page load if credentials are saved ───────────────────────
_auto_creds = (cfg.get("league_id") and cfg.get("espn_s2") and cfg.get("swid"))
if st.session_state.league is None and _auto_creds:
    with st.spinner("Connecting to ESPN…"):
        try:
            st.session_state.league = League(
                league_id=int(cfg["league_id"]),
                year=int(cfg.get("year", 2026)),
                espn_s2=cfg["espn_s2"],
                swid=cfg["swid"],
            )
            try:
                st.session_state.league_prev = League(
                    league_id=int(cfg["league_id"]),
                    year=int(cfg.get("year", 2026)) - 1,
                    espn_s2=cfg["espn_s2"],
                    swid=cfg["swid"],
                )
            except Exception:
                st.session_state.league_prev = None
        except Exception as e:
            st.sidebar.error(f"Auto-connect failed: {e}")

# ── 2025 stats helpers ────────────────────────────────────────────────────────
BATTER_STATS  = ["HR", "RBI", "R", "SB", "AVG", "OPS"]
PITCHER_STATS = ["W", "SV", "ERA", "WHIP", "K"]
PITCHER_SLOTS = {"SP", "RP", "P"}

def is_pitcher(player):
    slots = set(player.eligibleSlots or [player.position])
    return bool(slots & PITCHER_SLOTS)

def build_prev_stats(league_prev):
    """Return {player_name: {stat_key: val, ...}} from prior season ESPN breakdown."""
    lookup = {}
    for team in league_prev.teams:
        for p in team.roster:
            season = p.stats.get(0, {})
            bd = season.get("breakdown", {})
            # ESPN doesn't return fantasy point totals for completed seasons via mRoster;
            # skip prev_pts (it would always be 0) and just store the actual MLB stats.
            entry = {}
            keys = PITCHER_STATS if is_pitcher(p) else BATTER_STATS
            for k in keys:
                v = bd.get(k)
                if v is not None:
                    entry[k] = round(v, 3) if k in ("AVG", "OPS", "ERA", "WHIP") else int(round(v))
            if entry:  # only store if we got real stats
                lookup[p.name] = entry
    return lookup

# ── Connect ──────────────────────────────────────────────────────────────────
if connect:
    if not league_id or not espn_s2 or not swid:
        st.sidebar.error("Please fill in all fields.")
    else:
        with st.spinner("Connecting to ESPN…"):
            try:
                league = League(
                    league_id=int(league_id),
                    year=int(year),
                    espn_s2=espn_s2,
                    swid=swid,
                )
                st.session_state.league = league
                # Load prior season quietly for historical stats
                try:
                    league_prev = League(
                        league_id=int(league_id),
                        year=int(year) - 1,
                        espn_s2=espn_s2,
                        swid=swid,
                    )
                    st.session_state.league_prev = league_prev
                except Exception:
                    st.session_state.league_prev = None
                save_config({"league_id": int(league_id), "year": int(year),
                             "team_id": int(team_id) if team_id else None,
                             "espn_s2": espn_s2, "swid": swid})
                st.rerun()
            except Exception as e:
                st.sidebar.error(f"Connection failed: {e}")

league = st.session_state.league
league_prev = st.session_state.league_prev

if league is None:
    st.info("Enter your ESPN league credentials in the sidebar to get started.")
    st.stop()

# Build prior-season lookup (empty dict if unavailable)
prev_stats = build_prev_stats(league_prev) if league_prev else {}

# ── FanGraphs projections ─────────────────────────────────────────────────────
fg_proj_type = FG_PROJ_SYSTEMS.get(fg_proj_label, "steamer")
with st.spinner(f"Loading {fg_proj_label} projections from FanGraphs…"):
    fg = fetch_fg_projections(fg_proj_type)

# ── Vin Scully Daily Quotes ───────────────────────────────────────────────────
_SCULLY_QUOTES = [
    "It's time for Dodger baseball!",
    "Pull up a chair and spend the next three hours with us.",
    "Hi everybody, and a very pleasant good evening to you, wherever you may be.",
    "Statistics are used much like a drunk uses a lamppost: for support, not illumination.",
    "Andre Dawson has a bruised knee and is listed as day-to-day. Aren't we all?",
    "Baseball is not a sport you can achieve individually.",
    "In a year that has been so improbable, the impossible has happened.",
    "It's a great day for a ball game; let's play two!",
    "The Brooklyn Dodgers have won the World Series — and I don't believe it!",
    "Sandy Koufax, with a new Dodger record, his 25th victory of the season.",
    "There are three things you can do in a baseball game: you can win, or you can lose, or it can rain.",
    "I'd rather have a life I can be proud of than a name people remember.",
    "Baseball is the theater of the unexpected.",
    "Good evening, everyone, and a pleasant good evening it is — tonight under the lights.",
    "The game's the thing, and it's always been the thing.",
    "Some days you're the Louisville Slugger. Some days you're the ball.",
    "Once a Dodger, always a Dodger.",
    "Behind the plate, the heart of the defense — the catcher sees everything.",
    "Heeee struck him out! And the place is going absolutely wild!",
    "Two teams on a diamond. Simple as it sounds, there's nothing simple about it.",
    "Every great hitter works on the theory that the pitcher is more afraid of him than he is of the pitcher.",
    "The most beautiful thing in the world is a ballpark filled with people.",
    "He's sitting on a curveball… and he got it!",
    "Vin Scully, honored to be here — and honored to share it with all of you.",
    "The bullpen stirs. The crowd murmurs. Something's about to happen.",
    "I've had a blessed life. Baseball gave me all of it.",
    "A moment of silence in a ballpark is the loudest thing I've ever heard.",
    "Nobody goes undefeated all the time. If you can pick up after a crushing defeat, and go on to win again, you are going to be a champion someday.",
    "The stands are electric, the pitcher winds… this is why we love the game.",
    "You know, friends, you can talk about your football and your basketball and your hockey — this is baseball. This is ours.",
    "Pennant fever: there's no cure, and nobody's looking for one.",
    "Don't be afraid to take an extra base. Fortune favors the bold.",
    "It's the bottom of the ninth, two out, and the whole season on the line.",
    "The pitcher has his sign. The catcher crouches. The batter digs in. Baseball.",
    "Three balls, two strikes. The most beautiful count in sports.",
    "That ball is… way back… and gone! A home run!",
    "He winds and fires — strike three, called! And the crowd erupts!",
    "There's nothing like a sunny afternoon in April when the season is brand new.",
    "Hit deep to left field… back, back, back — it is GONE! Farewell!",
    "In all my years behind the microphone, this game still surprises me every night.",
    "The manager heads to the mound — this is the moment that separates good teams from great teams.",
    "A ground ball through the left side, and here comes the tying run!",
    "Every at-bat is a story. Every game is a novel.",
    "The infield shift defies convention. Baseball always finds a way to keep you honest.",
    "Line drive, right field — that's a base hit and the runner scores easily!",
    "He's thrown out at second, but what a play by the center fielder!",
    "Two on, two out, the cleanup hitter digs in. This is what it's all about.",
    "They say you can't go home again. Nonsense. Come to a ballpark.",
    "He checks the runners, he winds, he delivers — and that ball sails into the night.",
    "And a very pleasant good night to you, wherever you may be.",
    "Baseball: the game that time forgets, and fathers never do.",
    "It was a September night in Los Angeles and the pennant was on the line.",
]

# ── This Day in MLB History ───────────────────────────────────────────────────
_MLB_HISTORY = {
    (1,  1): "1876 — The National League was formally organized in New York City, giving birth to Major League Baseball.",
    (1,  5): "1920 — Babe Ruth was sold by the Red Sox to the Yankees for $100,000 — the most infamous trade in baseball history.",
    (1, 26): "1939 — Lou Gehrig played in his 2,130th consecutive game just months before his retirement.",
    (2,  2): "1876 — Albert Spalding published the first official baseball rulebook, standardizing the game nationwide.",
    (2,  6): "1895 — Babe Ruth was born in Baltimore, Maryland. Happy Birthday, Sultan of Swat.",
    (2, 10): "1936 — The Baseball Hall of Fame inducted its first five members: Cobb, Wagner, Ruth, Mathewson, and Johnson.",
    (2, 26): "1934 — Hank Aaron was born in Mobile, Alabama. He would go on to hit 755 career home runs.",
    (3,  2): "1962 — The New York Mets played their first-ever spring training game.",
    (3,  5): "1946 — Enos Slaughter signed the first $50,000 contract in Cardinals history.",
    (3, 16): "1962 — The Houston Colt .45s (later the Astros) played their inaugural spring training contest.",
    (3, 26): "1953 — The Boston Braves officially became the Milwaukee Braves — the first franchise move in 50 years.",
    (4,  1): "1973 — Ron Blomberg of the Yankees became baseball's first-ever designated hitter, walking in his debut PA.",
    (4,  4): "1974 — Hank Aaron hit home run #715, breaking Babe Ruth's all-time record before a national TV audience.",
    (4,  6): "1973 — The American League used the DH for the first time in regular-season play.",
    (4,  8): "1974 — Hammerin' Hank Aaron launched #715 off Al Downing. 'What a marvelous moment for baseball.'",
    (4, 11): "1954 — Hank Aaron played his first MLB game, going 0-for-5 but beginning a legendary 23-year career.",
    (4, 14): "1910 — President William Howard Taft threw out the first ceremonial first pitch, starting a presidential tradition.",
    (4, 15): "1947 — Jackie Robinson broke baseball's color barrier, stepping onto Ebbets Field in a Brooklyn Dodgers uniform.",
    (4, 18): "1923 — Yankee Stadium opened. Babe Ruth christened it with a home run. The New York Times called it 'The House That Ruth Built.'",
    (4, 22): "1970 — Tom Seaver struck out 19 Padres, including the last 10 in a row — a then-MLB record.",
    (4, 27): "1983 — Montreal's Steve Rogers threw a complete-game shutout, becoming the 100th pitcher to reach 100 career wins.",
    (4, 30): "1961 — Willie Mays hit four home runs in a single game against the Milwaukee Braves.",
    (5,  1): "1991 — Nolan Ryan, age 44, threw his seventh career no-hitter — the most in MLB history.",
    (5,  5): "1904 — Cy Young threw the first perfect game of the modern era.",
    (5,  6): "1953 — Bobo Holloman threw a no-hitter in his very first Major League start.",
    (5,  7): "1959 — Roy Campanella Night at the LA Coliseum drew 93,103 fans — the largest crowd in MLB history.",
    (5, 10): "1970 — Ernie Banks played his 2,500th career game — all of them in a Cubs uniform.",
    (5, 15): "1941 — Joe DiMaggio began his legendary 56-game hitting streak.",
    (5, 17): "1998 — David Wells threw a perfect game for the Yankees vs. the Minnesota Twins.",
    (5, 24): "1935 — The first-ever MLB night game was played at Crosley Field in Cincinnati under the lights.",
    (5, 26): "1959 — Harvey Haddix pitched 12 perfect innings for Pittsburgh but lost the game in the 13th — the most heartbreaking near-perfecto ever.",
    (6,  2): "1941 — Lou Gehrig passed away at age 37, two years after calling himself 'the luckiest man on the face of the earth.'",
    (6,  3): "1932 — Lou Gehrig hit four home runs in a single game against the Philadelphia Athletics.",
    (6, 10): "1944 — Joe Nuxhall, age 15, pitched in a game for the Reds — the youngest player in modern MLB history.",
    (6, 11): "2003 — Roger Clemens earned his 300th career win, also recording his 4,000th strikeout in the same game.",
    (6, 12): "1939 — The Baseball Hall of Fame officially opened in Cooperstown, New York.",
    (6, 19): "1846 — The first officially recorded baseball game under Cartwright's rules was played in Hoboken, New Jersey.",
    (6, 21): "1964 — Jim Bunning of the Phillies threw a perfect game on Father's Day.",
    (6, 23): "1917 — Babe Ruth was ejected after one pitch; Ernie Shore retired 26 straight batters in one of the most unusual near-perfecftos ever recorded.",
    (7,  2): "1941 — Joe DiMaggio extended his hitting streak to 45 games, setting a then-American League record.",
    (7,  4): "1939 — Lou Gehrig delivered his farewell speech at Yankee Stadium. 'Today I consider myself the luckiest man on the face of the earth.'",
    (7,  6): "1933 — The first All-Star Game was played at Comiskey Park, with Babe Ruth hitting the game's first-ever homer.",
    (7, 17): "1941 — Joe DiMaggio's 56-game hitting streak ended when Cleveland's pitchers held him hitless.",
    (7, 24): "1983 — The Pine Tar Incident: George Brett's go-ahead HR was nullified by umpires. He stormed out of the dugout in fury.",
    (7, 25): "1956 — Robin Roberts won his 200th career game, the first pitcher in NL history to reach that milestone.",
    (7, 29): "1975 — Henry Aaron collected the 3,000th hit of his career.",
    (8,  1): "1972 — Roberto Clemente recorded his 3,000th career hit — the last of his life. He died in a plane crash five months later.",
    (8,  6): "1986 — Roger Clemens struck out 20 batters in a single game, setting an MLB record that still stands.",
    (8, 12): "1994 — The MLB Players' Strike began, eventually canceling the World Series for the first time since 1904.",
    (8, 16): "1948 — Babe Ruth passed away at age 53. Sixty thousand fans filed past his casket at Yankee Stadium.",
    (8, 22): "1851 — The first recorded baseball game between two clubs took place in New York City.",
    (8, 26): "1939 — The first MLB game was televised — a Reds-Dodgers doubleheader broadcast on W2XBS in New York.",
    (9,  6): "1995 — Cal Ripken Jr. played in his 2,131st consecutive game, breaking Lou Gehrig's 'unbreakable' record.",
    (9,  8): "1998 — Mark McGwire hit his 62nd home run, breaking Roger Maris's single-season record.",
    (9, 11): "1985 — Pete Rose singled off Eric Show for career hit #4,192, surpassing Ty Cobb's all-time record.",
    (9, 14): "1968 — Denny McLain won his 30th game of the season — a feat no pitcher has matched since.",
    (9, 22): "1969 — Willie Mays hit his 600th career home run, joining a very exclusive club.",
    (9, 28): "1941 — Ted Williams went 6-for-8 on the final day of the season to finish at .406, the last .400 season in MLB history.",
    (10, 1): "1961 — Roger Maris hit home run #61 on the final day of the season, breaking Babe Ruth's single-season record.",
    (10, 3): "1951 — Bobby Thomson hit the 'Shot Heard 'Round the World' to win the pennant for the Giants over Brooklyn.",
    (10, 8): "1956 — Don Larsen threw the only perfect game in World Series history — Yankees vs. Dodgers, Game 5.",
    (10,13): "1960 — Bill Mazeroski hit the only walk-off home run to end a World Series, Game 7, for the Pittsburgh Pirates.",
    (10,15): "1988 — Kirk Gibson hobbled to the plate and hit one of the most famous home runs in history — Dodgers vs. Oakland.",
    (10,17): "1989 — The Loma Prieta earthquake struck during the World Series, shaking Candlestick Park and delaying the Series 10 days.",
    (10,21): "1975 — Carlton Fisk waved his iconic walk-off HR fair in Game 6 of the World Series. One of the greatest moments in baseball history.",
    (10,25): "1986 — The ball rolled through Bill Buckner's legs, extending the World Series for the Mets. Shea Stadium erupted.",
    (10,27): "2004 — The Boston Red Sox won the World Series, ending the 86-year 'Curse of the Bambino.'",
    (11, 1): "2001 — Tino Martinez and Scott Brosius hit back-to-back 9th-inning HRs in successive games; the Yankees won both in extras.",
    (11, 4): "2001 — Luis Gonzalez blooped a walk-off single in Game 7 to give Arizona the World Series title over the Yankees.",
    (11, 7): "1991 — Kirby Puckett homered in extra innings to force a Game 7 in what many call the greatest World Series ever.",
    (12, 8): "1975 — Free agency officially began in baseball after arbitrator Peter Seitz ruled for Andy Messersmith and Dave McNally.",
    (12,11): "1937 — Joe DiMaggio signed for $25,000 — a then-record salary for a second-year player.",
    (12,24): "1974 — Catfish Hunter became baseball's first modern free agent, signing a landmark deal with the Yankees.",
}

# ── Roto Value (replaces fantasy-points for roto leagues) ─────────────────────
# Anchors: MLB full-season league-average ± 1 SD for each roto category.
# Tuple layout: (stat_key, avg, sd, invert?)  invert=True means lower is better.
_ROTO_BAT_CATS = [
    ("HR",  20.0, 10.0, False),
    ("R",   75.0, 20.0, False),
    ("RBI", 70.0, 22.0, False),
    ("SB",  15.0, 12.0, False),
    ("AVG",  .252,  .030, False),
]
_ROTO_PIT_CATS = [
    ("W",    10.0,  4.0,  False),
    ("SV",    5.0, 15.0,  False),
    ("K",   150.0, 50.0,  False),
    ("ERA",   4.20,  .90, True),
    ("WHIP",  1.32,  .20, True),
]

def fg_roto_value_by_name(name: str) -> float:
    """Roto value lookup by player name (used when we only have a name string)."""
    entry = fg.get(name, {})
    if not entry:
        return 0.0
    # Determine pitcher vs batter heuristically from entry keys
    cats = _ROTO_PIT_CATS if ("ERA" in entry or "WHIP" in entry) else _ROTO_BAT_CATS
    total = 0.0
    for cat, avg, sd, inv in cats:
        v = entry.get(cat)
        if v is None:
            continue
        z = (float(v) - avg) / sd
        total += (-z if inv else z)
    return round(total, 2)

def fg_roto_value(player) -> float:
    """
    Roto league value = sum of per-category z-scores from FanGraphs projections.
    Positive = above average contributor; higher = more roto value.
    Typical range: elite hitter/pitcher ≈ +5–9 ; average ≈ 0 ; below avg < 0.
    """
    entry = fg.get(player.name, {})
    if not entry:
        return 0.0
    cats = _ROTO_PIT_CATS if is_pitcher(player) else _ROTO_BAT_CATS
    total = 0.0
    for cat, avg, sd, inv in cats:
        v = entry.get(cat)
        if v is None:
            continue
        z = (float(v) - avg) / sd
        total += (-z if inv else z)
    return round(total, 2)

def fg_roto_cats(player) -> dict:
    """Return {category: z_score} for each roto category — used for category-level views."""
    entry = fg.get(player.name, {})
    cats = _ROTO_PIT_CATS if is_pitcher(player) else _ROTO_BAT_CATS
    result = {}
    for cat, avg, sd, inv in cats:
        v = entry.get(cat)
        if v is not None:
            z = (float(v) - avg) / sd
            result[cat] = round(-z if inv else z, 2)
    return result

def roto_helps_str(player) -> str:
    """Short string of categories where the player is meaningfully above average: '+HR +SB'"""
    cats = fg_roto_cats(player)
    above = [c for c, z in sorted(cats.items(), key=lambda x: -x[1]) if z > 0.25]
    return (" ".join(f"+{c}" for c in above)) or "—"

def roto_hurts_str(player) -> str:
    """Short string of categories where a pitcher meaningfully hurts (ERA/WHIP): '⚠️ERA'"""
    if not is_pitcher(player):
        return ""
    cats = fg_roto_cats(player)
    bad = [c for c in ("ERA", "WHIP") if cats.get(c, 0) < -0.3]
    return (" ".join(f"⚠️{c}" for c in bad)) if bad else ""

def roto_cfg(label: str = "Roto Val"):
    return st.column_config.NumberColumn(
        label, format="%.2f",
        help="Sum of category z-scores (roto value). Higher = better overall contributor."
    )

# Legacy shim so internal sort/comparison logic still works
def fg_pts(player, fallback_attr="projected_total_points") -> float:
    """Alias for fg_roto_value — kept for backward compatibility with sort/comparison logic."""
    return fg_roto_value(player)

def fg_stat_str(player) -> str:
    """Return a compact key-stats string from FanGraphs for a player."""
    entry = fg.get(player.name, {})
    keys = [k for k in (FG_PIT_KEEP if is_pitcher(player) else FG_BAT_KEEP)
            if ("K" if k == "SO" else k) in entry]
    return "  ".join(f"{('K' if k=='SO' else k)}:{entry['K' if k=='SO' else k]}" for k in keys) or "—"

# ── Display helpers ────────────────────────────────────────────────────────────
_STATUS_BADGE = {
    "INJURY_RESERVE": "🔴 IR",
    "OUT":            "🔴 Out",
    "DOUBTFUL":       "🟠 Dtf",
    "QUESTIONABLE":   "🟡 Q",
    "PROBABLE":       "🟢 Prob",
    "ACTIVE":         "🟢",
    "NORMAL":         "🟢",
}
def badge(s: str) -> str:
    return _STATUS_BADGE.get(s, "🟢" if not s else f"⚪ {s}")

# Slots that are roster spots, not actual positions
_NON_POSITIONS = {"BE", "BN", "IL", "IL10", "IL15", "IL60", "NA", "UTIL", "INJ"}

def pos_str(player) -> str:
    """Return only real baseball positions from a player's eligibleSlots."""
    slots = player.eligibleSlots or [player.position]
    real  = [s for s in slots if s.upper() not in _NON_POSITIONS and not s.upper().startswith("IL")]
    return ", ".join(real) if real else (player.position or "—")

def apply_badges(df: pd.DataFrame, col: str = "Status") -> pd.DataFrame:
    df = df.copy()
    if col in df.columns:
        df[col] = df[col].apply(lambda v: badge(str(v)) if pd.notna(v) else "🟢")
    return df

_BAT_COLS = ["HR", "R", "RBI", "SB", "AVG"]
_PIT_COLS = ["W", "ERA", "WHIP", "K", "SV"]
_DASH     = "—"   # placeholder for irrelevant stats

def pts_cfg(label: str):
    return st.column_config.NumberColumn(label, format="%.1f")

def war_cfg(label: str = "WAR"):
    return st.column_config.NumberColumn(label, format="%.1f",
                                         help="Projected Wins Above Replacement (FanGraphs)")

def pct_cfg(label: str = "% Own"):
    return st.column_config.ProgressColumn(label, min_value=0, max_value=100, format="%.0f%%")

def num_cfg(label: str, fmt: str = "%.0f"):
    return st.column_config.NumberColumn(label, format=fmt)

def fg_war(player) -> float:
    """Return FanGraphs projected WAR for a player."""
    return round(fg.get(player.name, {}).get("WAR", 0) or 0, 1)

def _fmt_stat(v, decimals: int = 0) -> str:
    """Format a stat value as a string, or return '—' if missing."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return _DASH
    return f"{v:.{decimals}f}" if decimals else str(int(round(float(v))))

def fg_stat_cols(player) -> dict:
    """Return individual FanGraphs stat columns as formatted strings.
    Irrelevant stats are '—' so cells are visually distinct."""
    entry = fg.get(player.name, {})
    if is_pitcher(player):
        return {
            "HR": _DASH, "R": _DASH, "RBI": _DASH, "SB": _DASH, "AVG": _DASH,
            "W":    _fmt_stat(entry.get("W")),
            "ERA":  _fmt_stat(entry.get("ERA"),  2),
            "WHIP": _fmt_stat(entry.get("WHIP"), 2),
            "K":    _fmt_stat(entry.get("K")),
            "SV":   _fmt_stat(entry.get("SV")),
        }
    else:
        return {
            "HR":  _fmt_stat(entry.get("HR")),
            "R":   _fmt_stat(entry.get("R")),
            "RBI": _fmt_stat(entry.get("RBI")),
            "SB":  _fmt_stat(entry.get("SB")),
            "AVG": _fmt_stat(entry.get("AVG"), 3),
            "W": _DASH, "ERA": _DASH, "WHIP": _DASH, "K": _DASH, "SV": _DASH,
        }

# All stat columns use TextColumn since values are now pre-formatted strings
STAT_COL_CFG = {c: st.column_config.TextColumn(c, width="small")
                for c in _BAT_COLS + _PIT_COLS}

def grey_na_stats(df: pd.DataFrame):
    """Dim '—' cells in stat columns using applymap (color only — most reliable in Streamlit)."""
    stat_cols = [c for c in _BAT_COLS + _PIT_COLS if c in df.columns]
    if not stat_cols:
        return df.style

    def dim_dash(v):
        return "color: #CBD5E1" if v == _DASH else "color: #0F172A; font-weight: 700"

    return df.style.applymap(dim_dash, subset=stat_cols)

# ── Player Grade System ────────────────────────────────────────────────────────
_GRADE_THRESHOLDS = [
    (97, "A+"), (93, "A"), (90, "A-"),
    (87, "B+"), (83, "B"), (80, "B-"),
    (77, "C+"), (73, "C"), (70, "C-"),
    (67, "D+"), (63, "D"), (60, "D-"),
    (55, "F+"), (50, "F"),
]
GRADE_COLS = ["G '25", "G '26 YTD", "G '26 Proj"]

def _score_to_grade(score: float) -> str:
    for threshold, grade in _GRADE_THRESHOLDS:
        if score >= threshold:
            return grade
    return "F-"

def _batter_score(stats: dict) -> float:
    """Composite 0-100 score for a batter vs. MLB league-average anchors."""
    def z(key, avg, sd):
        v = stats.get(key)
        if v is None:
            return 0.0
        try:
            return (float(v) - avg) / sd
        except Exception:
            return 0.0
    composite = (z("HR",  20.0, 10.0) * 0.25 +
                 z("RBI", 70.0, 22.0) * 0.25 +
                 z("R",   75.0, 20.0) * 0.20 +
                 z("SB",  15.0, 12.0) * 0.10 +
                 z("AVG",  .252,  .030) * 0.20)
    # z=0 (league avg) → 75 (C);  z≈2.1 → 100 (A+)
    return max(0.0, min(100.0, composite * 12.0 + 75.0))

def _pitcher_score(stats: dict) -> float:
    """
    Composite 0-100 score for a pitcher — splits starters vs. closers.
    z=0 (league-avg ERA/WHIP/W) → 75 (C).
    Cy Young tier (ERA ~1.90, WHIP ~0.90) → z≈2.0 → ~99 (A+).
    """
    sv = float(stats.get("SV") or 0)
    is_closer = sv >= 10

    def z(key, avg, sd, inv=False):
        v = stats.get(key)
        if v is None:
            return 0.0
        try:
            zv = (float(v) - avg) / sd
            return -zv if inv else zv
        except Exception:
            return 0.0

    zw    = z("W",    10.0,  4.0)
    zera  = z("ERA",  4.20,  0.90, inv=True)
    zwhip = z("WHIP", 1.32,  0.20, inv=True)
    zk    = z("K",   150.0, 50.0)
    zsv   = (sv - 5.0) / 15.0

    if is_closer:
        composite = zsv*0.35 + zera*0.20 + zwhip*0.20 + zk*0.15 + zw*0.10
    else:
        composite = zw*0.25 + zera*0.25 + zwhip*0.25 + zk*0.20 + zsv*0.05
    # z=0 (league avg) → 75 (C);  z≈2.1 → 100 (A+)
    return max(0.0, min(100.0, composite * 12.0 + 75.0))

def _war_grade(war) -> str:
    """Convert projected WAR to a letter grade."""
    try:
        war = float(war)
    except Exception:
        return "—"
    for threshold, grade in [
        (7.0, "A+"), (6.0, "A"), (5.0, "A-"),
        (4.5, "B+"), (4.0, "B"), (3.5, "B-"),
        (3.0, "C+"), (2.5, "C"), (2.0, "C-"),
        (1.5, "D+"), (1.0, "D"), (0.5, "D-"), (0.0, "F+"),
    ]:
        if war >= threshold:
            return grade
    return "F-"

def player_grades(player, prev_stats_dict: dict, fg_dict: dict) -> tuple:
    """
    Return (g2025, g_ytd_2026, g_proj_2026) letter grades for any player.
      g2025       — 2025 actual stats grade (ESPN breakdown)
      g_ytd_2026  — 2026 season-to-date grade (current league stats)
      g_proj_2026 — 2026 projected grade (FanGraphs WAR)
    """
    is_pit = is_pitcher(player)
    score_fn = _pitcher_score if is_pit else _batter_score

    # ── 2025 Grade ──────────────────────────────────────────────────────────
    ps = prev_stats_dict.get(player.name, {})
    g2025 = _score_to_grade(score_fn(ps)) if ps else "—"

    # ── 2026 YTD Grade ──────────────────────────────────────────────────────
    ytd: dict = {}
    try:
        ytd = player.stats.get(0, {}).get("breakdown", {}) or {}
    except Exception:
        pass
    sig_keys = ["W", "K", "SV"] if is_pit else ["HR", "R", "RBI"]
    g_ytd = _score_to_grade(score_fn(ytd)) if any(ytd.get(k, 0) for k in sig_keys) else "—"

    # ── 2026 Projected Grade ─────────────────────────────────────────────────
    war = fg_dict.get(player.name, {}).get("WAR")
    g_proj = _war_grade(war) if war is not None else "—"

    return g2025, g_ytd, g_proj

def _grade_style(val: str) -> str:
    """Return CSS for a letter-grade cell."""
    if val in ("A+", "A", "A-"):
        return "background-color:rgba(34,197,94,0.18);color:#15803D;font-weight:700"
    if val in ("B+", "B", "B-"):
        return "background-color:rgba(59,130,246,0.18);color:#1565C0;font-weight:700"
    if val in ("C+", "C", "C-"):
        return "background-color:rgba(234,179,8,0.18);color:#92400E;font-weight:700"
    if val in ("D+", "D", "D-"):
        return "background-color:rgba(249,115,22,0.18);color:#C2410C;font-weight:700"
    if val in ("F+", "F", "F-"):
        return "background-color:rgba(239,68,68,0.18);color:#B91C1C;font-weight:700"
    return "color:#94A3B8"  # "—"

def apply_grade_colors(styler):
    """Chain grade color styling onto an existing Pandas Styler."""
    present = [c for c in GRADE_COLS if c in styler.data.columns]
    if present:
        styler = styler.applymap(_grade_style, subset=present)
    return styler

GRADE_COL_CFG = {
    "G '25":     st.column_config.TextColumn("'25 Season", width="small",
                     help="2025 actual season grade (A+ → F-)"),
    "G '26 YTD": st.column_config.TextColumn("'26 YTD",    width="small",
                     help="2026 season-to-date grade (A+ → F-)"),
    "G '26 Proj":st.column_config.TextColumn("'26 Proj",   width="small",
                     help="2026 projected grade based on FanGraphs WAR (A+ → F-)"),
}

# ── Heat Meter ────────────────────────────────────────────────────────────────
_TOTAL_SEASON_WEEKS = 26   # approximate fantasy baseball season length

def heat_score(player, current_period: int) -> int:
    """
    Return a 1-10 heat score based on recent form vs FanGraphs projected pace.
      5  = exactly on projected pace
      10 = 2× projected pace or better  (🔥🔥)
      1  = barely scoring vs projection (🧊)
    Falls back to 5 (neutral) when there is no recent data.
    """
    expected_per_wk = fg_pts(player) / _TOTAL_SEASON_WEEKS

    if expected_per_wk <= 0 or current_period <= 1:
        return 5

    recent_keys = sorted(
        [k for k in player.stats if isinstance(k, int) and k > 0 and k < current_period],
        reverse=True
    )[:3]

    if not recent_keys:
        return 5

    recent_avg = sum(player.stats[k].get("points", 0) for k in recent_keys) / len(recent_keys)
    ratio      = recent_avg / expected_per_wk          # 1.0 = on pace
    score      = 5.0 + (ratio - 1.0) * 5.0            # 0→0, 1.0→5, 2.0→10
    return max(1, min(10, round(score)))

def heat_label(score: int) -> str:
    if score >= 9:  return f"🔥🔥 {score}"
    if score >= 7:  return f"🔥 {score}"
    if score >= 5:  return f"⚡ {score}"
    if score >= 3:  return f"❄️ {score}"
    return              f"🧊 {score}"

HEAT_CFG = st.column_config.TextColumn("🌡️ Heat", width="small")

# How far into current season? Use for blending weight
current_period = getattr(league, "currentMatchupPeriod", 1) or 1
# Blend weight: week 0→1.0 (all prior), week 6→0.0 (all current)
prior_weight = max(0.0, min(1.0, 1.0 - (current_period - 1) / 6.0))
cur_weight   = 1.0 - prior_weight

prev_year = cfg.get("year", 2026) - 1
if prev_stats:
    if prior_weight > 0.65:
        blend_label = f"📅 Pre-season: showing {prev_year} stats (no {cfg.get('year',2026)} data yet)"
    elif prior_weight > 0.1:
        blend_label = f"📊 Blending {prev_year} ({round(prior_weight*100)}%) + {cfg.get('year',2026)} ({round(cur_weight*100)}%) stats"
    else:
        blend_label = f"📊 Using {cfg.get('year',2026)} stats (full season sample)"
    st.sidebar.info(blend_label)

# ── Team Selector ─────────────────────────────────────────────────────────────
team_names = [t.team_name for t in league.teams]
saved_team_id = cfg.get("team_id")
default_index = 0
if saved_team_id:
    for i, t in enumerate(league.teams):
        if t.team_id == saved_team_id:
            default_index = i
            break

selected_team_name = st.sidebar.selectbox(
    "My Team", team_names, index=default_index
)
# Save team choice whenever it changes
selected_team = next(t for t in league.teams if t.team_name == selected_team_name)
if selected_team.team_id != cfg.get("team_id"):
    cfg["team_id"] = selected_team.team_id
    save_config(cfg)

my_team = selected_team

# ── Shared helper: build projected team stats + ranks ─────────────────────────
def _build_team_proj_shared():
    """Return (team_proj, team_ranks, all_cats, lower_better, n_teams).
    Shared by Front Office tab and Roto Tools tab."""
    _all   = ["HR", "R", "RBI", "SB", "AVG", "W", "SV", "K", "ERA", "WHIP"]
    _lower = {"ERA", "WHIP"}
    tp, tr = {}, {}
    for t in league.teams:
        bat = {"HR":0.,"R":0.,"RBI":0.,"SB":0.,"_an":0.,"_ad":0.}
        pit = {"W":0.,"SV":0.,"K":0.,"_er":0.,"_wb":0.,"_ip":0.}
        for p in t.roster:
            e = fg.get(p.name, {})
            if not e:
                continue
            if is_pitcher(p):
                for c in ("W","SV","K"): pit[c] += float(e.get(c) or 0)
                ip = float(e.get("IP") or 0)
                pit["_ip"] += ip
                pit["_er"] += float(e.get("ERA")  or 0) * ip / 9.0
                pit["_wb"] += float(e.get("WHIP") or 0) * ip
            else:
                for c in ("HR","R","RBI","SB"): bat[c] += float(e.get(c) or 0)
                avg = float(e.get("AVG") or 0)
                r   = max(float(e.get("R") or 0), 1.0)
                bat["_an"] += avg * r; bat["_ad"] += r
        ip = pit["_ip"] if pit["_ip"] > 0 else 1.0
        tp[t.team_name] = {
            "HR":   round(bat["HR"], 0),  "R":   round(bat["R"],  0),
            "RBI":  round(bat["RBI"],0),  "SB":  round(bat["SB"], 0),
            "AVG":  round(bat["_an"]/bat["_ad"], 3) if bat["_ad"] > 0 else 0.0,
            "W":    round(pit["W"],  0),  "SV":  round(pit["SV"], 0),
            "K":    round(pit["K"],  0),
            "ERA":  round(pit["_er"]*9.0/ip, 2),
            "WHIP": round(pit["_wb"]/ip,     3),
        }
    n = len(league.teams)
    for cat in _all:
        for rank, (name, _) in enumerate(
            sorted(tp.items(), key=lambda x: x[1][cat], reverse=(cat not in _lower)), 1
        ):
            tr.setdefault(name, {})[cat] = rank
    return tp, tr, _all, _lower, n

# ── Shared UI helpers ─────────────────────────────────────────────────────────
def _section_header(icon: str, title: str, subtitle: str = "") -> None:
    """Render a consistent left-accent-bar section header (inline styles only)."""
    sub_html = (
        f"<div style='font-size:11.5px;color:#64748B;margin-top:2px;font-weight:400'>"
        f"{subtitle}</div>"
    ) if subtitle else ""
    st.markdown(
        f"<div style='display:flex;align-items:center;gap:12px;padding:11px 18px;"
        f"background:linear-gradient(135deg,#F0F7FF 0%,#E8F2FF 100%);"
        f"border-radius:12px;border-left:4px solid #1565C0;"
        f"margin-bottom:14px;margin-top:6px'>"
        f"<span style='font-size:20px;line-height:1'>{icon}</span>"
        f"<div><div style='font-size:14.5px;font-weight:800;color:#0F3460;"
        f"letter-spacing:-0.2px'>{title}</div>{sub_html}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

def _empty_state(icon: str, message: str, hint: str = "") -> None:
    """Render a friendly empty-state card (inline styles only)."""
    hint_html = (
        f"<div style='margin-top:4px;font-size:12px;color:#94A3B8'>{hint}</div>"
    ) if hint else ""
    st.markdown(
        f"<div style='text-align:center;padding:28px 20px;color:#94A3B8;font-size:13px;"
        f"background:#F8FAFF;border-radius:12px;"
        f"border:1.5px dashed rgba(148,163,184,0.35)'>"
        f"<div style='font-size:32px;margin-bottom:8px'>{icon}</div>"
        f"<div style='font-weight:600;color:#64748B'>{message}</div>"
        f"{hint_html}</div>",
        unsafe_allow_html=True,
    )

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab0, tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8, tab9 = st.tabs([
    "🏢 Front Office",
    "📋 Lineup Optimizer",
    "🔍 Waiver Wire",
    "📊 Team Overview",
    "🔄 Trade Analyzer",
    "🪑 Start / Sit",
    "🌊 Streaming Pitchers",
    "📰 Player News",
    "⚾ Games",
    "🎯 Roto Tools",
])

# ─────────────────────────────────────────────────────────────────────────────
# TAB 0: FRONT OFFICE
# ─────────────────────────────────────────────────────────────────────────────
with tab0:
    _today      = datetime.now().astimezone()
    _week_num   = getattr(league, "currentMatchupPeriod", "?")
    _LOWER_FO   = {"ERA", "WHIP"}
    _ALL_CATS   = ["HR", "R", "RBI", "SB", "AVG", "W", "SV", "K", "ERA", "WHIP"]
    _BAT_CATS_S = {"HR", "R", "RBI", "SB", "AVG"}
    _PIT_CATS_S = {"W", "SV", "K", "ERA", "WHIP"}

    # ── Find current opponent ──────────────────────────────────────────────────
    _opp_fo = None
    for _m in my_team.schedule:
        _ht = getattr(_m, "home_team", None)
        _at = getattr(_m, "away_team", None)
        if _ht == my_team:   _opp_fo = _at;  break
        elif _at == my_team: _opp_fo = _ht;  break
    _opp_name_fo = getattr(_opp_fo, "team_name", "Unknown") if _opp_fo else "Unknown"

    # ── Shared projected stats ─────────────────────────────────────────────────
    _tp, _tr, _, _, _n = _build_team_proj_shared()
    _my_proj  = _tp.get(my_team.team_name, {})
    _opp_proj = _tp.get(_opp_name_fo, {})
    _my_ranks = _tr.get(my_team.team_name, {})

    # ════════════════════════════════════════════════════════════════════════════
    # SECTION A — DAILY BRIEF
    # ════════════════════════════════════════════════════════════════════════════
    st.markdown(
        f"<div style='font-size:26px;font-weight:800;color:#0F3460;margin-bottom:2px'>"
        f"🏢 Front Office</div>"
        f"<div style='color:#64748B;font-size:13px;margin-bottom:18px'>"
        f"{_today.strftime('%A, %B %-d, %Y')} · "
        f"League data refreshes hourly · "
        f"<span style='color:#1565C0;font-weight:600'>Season Week {_week_num}</span></div>",
        unsafe_allow_html=True,
    )

    # ── Pre-compute matchup W/L/T (used by weather cards + matchup section) ────
    _wins_fo = _losses_fo = _ties_fo = 0
    _lose_cats_fo, _close_cats_fo, _win_cats_fo = [], [], []
    if _opp_fo and _my_proj and _opp_proj:
        for _cat in _ALL_CATS:
            _mv  = float(_my_proj.get(_cat, 0))
            _ov  = float(_opp_proj.get(_cat, 0))
            _inv = _cat in _LOWER_FO
            _i_win = (_mv < _ov) if _inv else (_mv > _ov)
            if _mv == _ov:
                _ties_fo += 1
            elif _i_win:
                _wins_fo += 1
                _win_cats_fo.append(_cat)
            else:
                _losses_fo += 1
                _lose_cats_fo.append(_cat)
                if abs(_mv - _ov) / max(abs(_ov), 0.001) < 0.12:
                    _close_cats_fo.append(_cat)

    # ── Pre-compute season rank ───────────────────────────────────────────────
    _season_pts_pre = {nm: sum(_tr.get(nm, {}).get(c, _n) for c in _ALL_CATS) for nm in _tp}
    _ranked_pre     = sorted(_season_pts_pre.items(), key=lambda x: x[1], reverse=True)
    _my_season_pts_pre = _season_pts_pre.get(my_team.team_name, 0)
    _my_season_rank_pre = next(
        (i + 1 for i, (nm, _) in enumerate(_ranked_pre) if nm == my_team.team_name), _n
    )

    # ── Weather forecast helpers ──────────────────────────────────────────────
    def _weather_matchup(wins, losses):
        """Return (emoji, label, description, bg_gradient) for weekly matchup."""
        if wins >= 8:
            return ("☀️",  "Amazing",       "Dominating the matchup — keep it going.",
                    "linear-gradient(135deg,#FEF9C3,#FEF08A)")
        if wins >= 6:
            return ("🌤️", "Looking Good",  "Winning more than losing — stay the course.",
                    "linear-gradient(135deg,#FEF9C3,#FDE68A)")
        if wins >= 5:
            return ("⛅",  "Even Battle",   "Too close to call — one smart add could swing it.",
                    "linear-gradient(135deg,#F1F5F9,#E2E8F0)")
        if wins >= 3:
            return ("🌥️", "Cloudy",        "Falling behind — time to target the losing cats.",
                    "linear-gradient(135deg,#F1F5F9,#CBD5E1)")
        if wins >= 1:
            return ("🌦️", "Rough Week",    "Losing badly — aggressive FA moves needed now.",
                    "linear-gradient(135deg,#EFF6FF,#DBEAFE)")
        return          ("⛈️", "Storm Warning", "Being shut out — emergency roster moves required.",
                    "linear-gradient(135deg,#FEF2F2,#FECACA)")

    def _weather_season(rank, n):
        """Return (emoji, label, description, bg_gradient) for season outlook."""
        pct = rank / max(n, 1)
        if pct <= 0.10:
            return ("☀️",  "Dominant",       f"#{rank} in the league — you're the team to beat.",
                    "linear-gradient(135deg,#FEF9C3,#FEF08A)")
        if pct <= 0.30:
            return ("🌤️", "Strong Season",  f"#{rank} of {n} — well-positioned for a run.",
                    "linear-gradient(135deg,#FEF9C3,#FDE68A)")
        if pct <= 0.55:
            return ("⛅",  "Holding Steady", f"#{rank} of {n} — in the hunt but not comfortable.",
                    "linear-gradient(135deg,#F1F5F9,#E2E8F0)")
        if pct <= 0.70:
            return ("🌥️", "Cloudy",         f"#{rank} of {n} — just outside the top half.",
                    "linear-gradient(135deg,#F1F5F9,#CBD5E1)")
        if pct <= 0.85:
            return ("🌦️", "Falling Behind", f"#{rank} of {n} — significant work needed.",
                    "linear-gradient(135deg,#EFF6FF,#DBEAFE)")
        return          ("⛈️", "Storm Warning",  f"#{rank} of {n} — near the bottom, bold moves required.",
                    "linear-gradient(135deg,#FEF2F2,#FECACA)")

    # ── Weather Forecast Cards ────────────────────────────────────────────────
    _wm_emoji, _wm_label, _wm_desc, _wm_bg = _weather_matchup(_wins_fo, _losses_fo)
    _ws_emoji, _ws_label, _ws_desc, _ws_bg = _weather_season(_my_season_rank_pre, _n)

    _wfc1, _wfc2 = st.columns(2)

    _wfc1.markdown(
        f"""<div style="background:{_wm_bg};border:1px solid rgba(148,163,184,0.30);
                border-radius:16px;padding:22px 24px;text-align:center;height:100%">
          <div style="font-size:11px;font-weight:800;color:#64748B;letter-spacing:1.2px;
                      margin-bottom:10px">WEEKLY MATCHUP OUTLOOK</div>
          <div style="font-size:72px;line-height:1;margin-bottom:10px">{_wm_emoji}</div>
          <div style="font-size:22px;font-weight:800;color:#0F3460;margin-bottom:6px">{_wm_label}</div>
          <div style="font-size:13px;color:#475569;line-height:1.5">{_wm_desc}</div>
          <div style="font-size:12px;color:#94A3B8;margin-top:10px">
            Week {_week_num} · {_wins_fo}W – {_losses_fo}L – {_ties_fo}T
          </div>
        </div>""",
        unsafe_allow_html=True,
    )

    _wfc2.markdown(
        f"""<div style="background:{_ws_bg};border:1px solid rgba(148,163,184,0.30);
                border-radius:16px;padding:22px 24px;text-align:center;height:100%">
          <div style="font-size:11px;font-weight:800;color:#64748B;letter-spacing:1.2px;
                      margin-bottom:10px">SEASON OUTLOOK</div>
          <div style="font-size:72px;line-height:1;margin-bottom:10px">{_ws_emoji}</div>
          <div style="font-size:22px;font-weight:800;color:#0F3460;margin-bottom:6px">{_ws_label}</div>
          <div style="font-size:13px;color:#475569;line-height:1.5">{_ws_desc}</div>
          <div style="font-size:12px;color:#94A3B8;margin-top:10px">
            {_my_season_pts_pre} projected roto pts · {_n}-team league
          </div>
        </div>""",
        unsafe_allow_html=True,
    )

    # ── Vin Scully Quote (cycles daily by day-of-year) ────────────────────────
    _scully_idx   = _today.timetuple().tm_yday % len(_SCULLY_QUOTES)
    _scully_text  = _SCULLY_QUOTES[_scully_idx]

    # ── This Day in MLB History ───────────────────────────────────────────────
    _history_key  = (_today.month, _today.day)
    _history_text = _MLB_HISTORY.get(
        _history_key,
        f"On this date throughout baseball history, countless games have been played, "
        f"records broken, and legends made — proof that every day is a great day for baseball.",
    )

    _qc1, _qc2 = st.columns(2)

    _qc1.markdown(
        f"""<div style="background:linear-gradient(135deg,#0F3460,#1565C0);
                border-radius:14px;padding:20px 22px;height:100%">
          <div style="font-size:10px;font-weight:800;color:rgba(255,255,255,0.55);
                      letter-spacing:1.4px;margin-bottom:10px">VIN SCULLY · DAILY QUOTE</div>
          <div style="font-size:15px;color:#FFFFFF;font-style:italic;line-height:1.6;
                      margin-bottom:10px">"{_scully_text}"</div>
          <div style="font-size:11px;color:rgba(255,255,255,0.45)">— Vin Scully</div>
        </div>""",
        unsafe_allow_html=True,
    )

    _qc2.markdown(
        f"""<div style="background:linear-gradient(135deg,#7C3AED,#4F46E5);
                border-radius:14px;padding:20px 22px;height:100%">
          <div style="font-size:10px;font-weight:800;color:rgba(255,255,255,0.55);
                      letter-spacing:1.4px;margin-bottom:10px">
            ⚾ THIS DAY IN MLB HISTORY · {_today.strftime("%B %-d")}
          </div>
          <div style="font-size:14px;color:#FFFFFF;line-height:1.6">{_history_text}</div>
        </div>""",
        unsafe_allow_html=True,
    )

    st.divider()

    _fo_tab_today, _fo_tab_season = st.tabs([
        "📅 Today", "📊 This Season",
    ])

    with _fo_tab_today:

        # Placeholder — filled after all daily data is computed (stays at top visually)
        _todo_ph = st.empty()

        # ── A1. Matchup Pulse ──────────────────────────────────────────────────────
        _section_header("📅", "This Week's Matchup",
                        f"Week {_week_num} · {my_team.team_name} vs {_opp_name_fo}")

        if _opp_fo and _my_proj and _opp_proj:
            _verdict = (
                "🟢 On track to win" if _wins_fo > _losses_fo
                else "🔴 Currently losing" if _losses_fo > _wins_fo
                else "🟡 Deadlocked"
            )

            # Matchup card
            st.markdown(
                f"""<div style="background:linear-gradient(135deg,#EFF6FF,#DBEAFE);
                    border:1px solid rgba(21,101,192,0.22);border-radius:14px;
                    padding:20px 24px;margin-bottom:16px">
                  <div style="font-size:12px;color:#64748B;font-weight:700;
                              letter-spacing:1px;margin-bottom:6px">WEEK {_week_num} MATCHUP</div>
                  <div style="font-size:20px;font-weight:800;color:#0F3460;margin-bottom:10px">
                    {my_team.team_name} <span style="color:#94A3B8">vs</span> {_opp_name_fo}
                  </div>
                  <div style="display:flex;gap:28px;flex-wrap:wrap;font-size:15px">
                    <span style="color:#15803D;font-weight:700">✅ Winning {_wins_fo} cats</span>
                    <span style="color:#B91C1C;font-weight:700">❌ Losing {_losses_fo} cats</span>
                    <span style="color:#64748B">➖ Tied {_ties_fo}</span>
                    <span style="font-weight:700;color:#1565C0">{_verdict}</span>
                  </div>
                </div>""",
                unsafe_allow_html=True,
            )

            _mc1, _mc2 = st.columns(2)
            if _win_cats_fo:
                _mc1.success(f"**Winning:** {', '.join(_win_cats_fo)}")
            if _lose_cats_fo:
                _mc2.error(f"**Losing:** {', '.join(_lose_cats_fo)}")
            if _close_cats_fo:
                st.warning(
                    f"⚡ **Flippable this week** (within 12%): **{', '.join(_close_cats_fo)}** — "
                    "a single good pickup or hot day could swing these."
                )
        else:
            st.info("No matchup data available yet for this week.")

        # ── A2. Roster Alerts ─────────────────────────────────────────────────────
        _section_header("🚨", "Roster Alerts", "Injuries, dead weight, and players needing attention")

        _alerts = []

        # Injured / IL
        for _p in my_team.roster:
            _status = getattr(_p, "injuryStatus", "ACTIVE")
            if _status in ("INJURY_RESERVE", "OUT", "DOUBTFUL", "QUESTIONABLE"):
                _alerts.append(
                    (
                        "error" if _status in ("INJURY_RESERVE", "OUT")
                        else "warning",
                        f"{badge(_status)} **{_p.name}** ({pos_str(_p)}) — "
                        f"{'Check Emergency Replacements tab for FA swaps.' if _status in ('INJURY_RESERVE','OUT') else 'Monitor before locking lineup.'}"
                    )
                )

        # Negative roto value players (dead weight)
        _dead_weight = sorted(
            [_p for _p in my_team.roster if fg_roto_value(_p) < -0.5],
            key=fg_roto_value,
        )
        for _p in _dead_weight[:2]:
            _alerts.append((
                "warning",
                f"🗑️ **{_p.name}** has roto value of **{fg_roto_value(_p):+.2f}** — "
                "actively hurting your team. Consider a waiver swap."
            ))

        if not _alerts:
            st.success("✅ No urgent roster issues — you're in good shape.")
        else:
            for _lvl, _msg in _alerts:
                getattr(st, _lvl)(_msg)

        # ── A3. Today's Best FA Adds ───────────────────────────────────────────────
        _section_header("🆓", "Best FA Adds Right Now",
                        "Targeted at your losing categories · includes suggested drops")
        _cap_txt = (
            f"Targeted at your **losing categories** ({', '.join(_lose_cats_fo)}). "
            if _lose_cats_fo else "Top available free agents by roto value. "
        )
        st.caption(_cap_txt + "Refresh the page for updated availability.")

        with st.spinner("Scanning free agents…"):
            try:
                _fo_fa_pool = league.free_agents(size=200)
            except Exception:
                _fo_fa_pool = []

        # Score each FA on losing-category help (or overall if no losing cats)
        _fo_fa_scored = []
        for _fa in _fo_fa_pool:
            if getattr(_fa, "injuryStatus", "ACTIVE") in ("INJURY_RESERVE", "OUT"):
                continue
            if not fg.get(_fa.name):
                continue
            _fa_cats  = fg_roto_cats(_fa)
            _rel_lose = (
                [c for c in _lose_cats_fo if c in (_PIT_CATS_S if is_pitcher(_fa) else _BAT_CATS_S)]
                if _lose_cats_fo else list(_fa_cats.keys())
            )
            _help = sum(_fa_cats.get(c, 0) for c in _rel_lose)
            if _help > 0:
                _fo_fa_scored.append((_fa, _help,
                                      [c for c in _rel_lose if _fa_cats.get(c, 0) > 0.10]))

        _fo_fa_scored.sort(key=lambda x: x[1], reverse=True)

        # Roster sorted worst→best for drop pairing
        _fo_roster_sorted = sorted(my_team.roster, key=fg_roto_value)

        _fo_add_rows = []
        for _fa, _help, _helped in _fo_fa_scored[:8]:
            _fa_slots = {s.upper() for s in (_fa.eligibleSlots or [])
                         if s.upper() not in _NON_POSITIONS and not s.upper().startswith("IL")}
            _drop_p = next(
                (_p for _p in _fo_roster_sorted
                 if {s.upper() for s in (_p.eligibleSlots or [])
                     if s.upper() not in _NON_POSITIONS and not s.upper().startswith("IL")} & _fa_slots
                 and getattr(_p, "injuryStatus", "ACTIVE") not in ("INJURY_RESERVE",)),
                None,
            )
            _drop_val = fg_roto_value(_drop_p) if _drop_p else 0.0
            _fo_add_rows.append({
                "Add":          _fa.name,
                "Pos":          pos_str(_fa),
                "Roto Val":     fg_roto_value(_fa),
                "Helps":        " ".join(f"+{c}" for c in _helped) or "—",
                "% Own":        round(getattr(_fa, "percent_owned", 0) or 0, 1),
                "Drop":         _drop_p.name if _drop_p else "—",
                "Drop Val":     round(_drop_val, 2) if _drop_p else None,
                "Net":          round(fg_roto_value(_fa) - _drop_val, 2),
            })

        if not _fo_add_rows:
            st.info("No matching free agents found — try refreshing.")
        else:
            def _fo_net_style(v):
                try:
                    f = float(v)
                    if f > 0.5: return "color:#15803D;font-weight:700"
                    if f < 0:   return "color:#B91C1C"
                except Exception: pass
                return "color:#92400E"

            _fo_df = pd.DataFrame(_fo_add_rows)
            st.dataframe(
                _fo_df.style.applymap(_fo_net_style, subset=["Net"]),
                use_container_width=True, hide_index=True,
                column_config={
                    "Add":      st.column_config.TextColumn("Add (FA)",  width="medium"),
                    "Pos":      st.column_config.TextColumn("Pos",       width="small"),
                    "Roto Val": roto_cfg("Roto Val"),
                    "Helps":    st.column_config.TextColumn("Helps",     width="small"),
                    "% Own":    pct_cfg("% Own"),
                    "Drop":     st.column_config.TextColumn("Drop",      width="medium"),
                    "Drop Val": num_cfg("Drop Val", "%.2f"),
                    "Net":      num_cfg("Net Gain", "%.2f"),
                },
            )
            _fo_best = _fo_add_rows[0]
            if _fo_best["Net"] > 0:
                _fo_drop_txt = (
                    f", dropping **{_fo_best['Drop']}** ({_fo_best['Drop Val']:+.2f})"
                    if _fo_best["Drop"] != "—" else ""
                )
                st.success(
                    f"🎯 **Top add**: **{_fo_best['Add']}** (helps **{_fo_best['Helps']}**)"
                    f"{_fo_drop_txt} — net gain **+{_fo_best['Net']:.2f}**."
                )

        with st.expander("📅 Two-Start FA Pitchers This Week", expanded=False):
            # ── A4. Two-Start Pitchers Available as FAs ────────────────────────────────
            _section_header("📅", "Two-Start FA Pitchers This Week",
                            "Free agent SPs with 2 confirmed starts · highest-leverage weekly move")
            _today_d  = datetime.now().date()
            _monday   = _today_d - timedelta(days=_today_d.weekday())
            _week_str = _monday.strftime("%Y%m%d")

            with st.spinner("Checking two-start pitchers…"):
                _ts_data = fetch_weekly_starts(_week_str)

            _my_pit_names = {_p.name for _p in my_team.roster if is_pitcher(_p)}
            _fa_two_start = [
                (_nm, _info) for _nm, _info in _ts_data.items()
                if _nm not in _my_pit_names
            ]
            _fa_two_start.sort(key=lambda x: fg_roto_value_by_name(x[0]), reverse=True)

            if not _fa_two_start:
                st.info("No two-start FA pitchers identified yet — ESPN confirms probable starters a few days out.")
            else:
                _ts_rows = []
                for _nm, _info in _fa_two_start[:6]:
                    _e = fg.get(_nm, {})
                    _ts_rows.append({
                        "Pitcher":     _nm,
                        "Team":        _info["team"],
                        "Starts":      _info["starts"],
                        "Schedule":    "  ·  ".join(
                            f"{d} {o}" for d, o in zip(_info["dates"], _info.get("opp", []))
                        ),
                        "Roto Val":    round(fg_roto_value_by_name(_nm), 2),
                        "Proj ERA":    _e.get("ERA", "—"),
                        "Proj WHIP":   _e.get("WHIP", "—"),
                    })
                st.dataframe(
                    pd.DataFrame(_ts_rows),
                    use_container_width=True, hide_index=True,
                    column_config={
                        "Roto Val":  roto_cfg(),
                        "Schedule":  st.column_config.TextColumn("Schedule", width="large"),
                    },
                )

            # ── A5. Today's Starting Pitchers ─────────────────────────────────────────
        _section_header("⚾", "Your Starters Today",
                        f"{_today.strftime('%A, %B %-d')} · confirm active before first pitch")
        with st.spinner("Loading today's probable starters…"):
            _today_prob = fetch_today_starters()

        _my_starting_today = [
            (p, _today_prob[p.name])
            for p in my_team.roster
            if is_pitcher(p) and p.name in _today_prob
        ]

        if not _my_starting_today:
            st.info("None of your pitchers are confirmed to start today — "
                    "ESPN posts probable starters a few hours before first pitch.")
        else:
            _ts_cols = st.columns(min(len(_my_starting_today), 4))
            for _ci, (_sp, _info) in enumerate(_my_starting_today):
                _pid    = getattr(_sp, "playerId", None)
                _photo  = (f"https://a.espncdn.com/i/headshots/mlb/players/full/{_pid}.png"
                           if _pid else "")
                _sp_fg  = fg.get(_sp.name, {})
                _era    = _sp_fg.get("ERA", "—")
                _whip   = _sp_fg.get("WHIP", "—")
                _risk   = roto_hurts_str(_sp)
                _era_clr = ("#B91C1C" if isinstance(_era, (int, float)) and float(_era) > 4.50
                            else "#15803D")
                _risk_html = (
                    f"<div style='font-size:10px;color:#B91C1C;margin-top:5px'>{_risk}</div>"
                ) if _risk else ""
                with _ts_cols[_ci % 4]:
                    # Render headshot separately so Streamlit handles the image safely
                    if _photo:
                        st.markdown(
                            f"<div style='text-align:center;margin-bottom:4px'>"
                            f"<img src='{_photo}' width='52' height='52' "
                            f"style='border-radius:50%;object-fit:cover;"
                            f"border:2px solid rgba(21,101,192,0.30)'>"
                            f"</div>",
                            unsafe_allow_html=True,
                        )
                    st.markdown(
                        f"<div style='background:linear-gradient(135deg,#EFF6FF,#DBEAFE);"
                        f"border:1px solid rgba(21,101,192,0.22);border-radius:12px;"
                        f"padding:12px 16px;text-align:center'>"
                        f"<div style='font-size:13px;font-weight:800;color:#0F3460;"
                        f"margin-bottom:4px'>{_sp.name}</div>"
                        f"<div style='font-size:13px;color:#1565C0;font-weight:700;"
                        f"margin-bottom:6px'>{_info['ha']} {_info['opp']}</div>"
                        f"<div style='font-size:11px;color:#475569'>"
                        f"ERA <b style='color:{_era_clr}'>{_era}</b>"
                        f"&nbsp;&middot;&nbsp;WHIP <b>{_whip}</b></div>"
                        f"{_risk_html}"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
        with st.expander("🔥 Hot & Cold Players", expanded=False):
            # ── A6. Hot / Cold Streak Tracker ─────────────────────────────────────────
            _section_header("🔥", "Hot & Cold Players",
                            "Actual stat pace vs FanGraphs projection · 🔥 Hot = +20%  ·  ❄️ Cold = −20%  ·  ✅ On track")

            _streak_rows = []
            for _sp2 in my_team.roster:
                _fg2  = fg.get(_sp2.name, {})
                if not _fg2:
                    continue
                _st0  = (_sp2.stats.get(0, {}).get("breakdown", {})
                         if hasattr(_sp2, "stats") and isinstance(_sp2.stats, dict) else {})
                _isp  = is_pitcher(_sp2)

                # Games-played proxy
                if _isp:
                    _ip2 = float(_st0.get("IP", _st0.get("pitchingInningsPitched", 0)) or 0)
                    _gp2 = _ip2 / 6.0
                    _cats2 = [("ERA","ERA",True),("WHIP","WHIP",True),
                              ("K","K",False),("W","W",False),("SV","SV",False)]
                else:
                    _ab2 = float(_st0.get("AB", _st0.get("battingAtBats", 0)) or 0)
                    _bb2 = float(_st0.get("BB", _st0.get("battingWalks", 0)) or 0)
                    _gp2 = (_ab2 + _bb2) / 4.0
                    _cats2 = [("HR","HR",False),("RBI","RBI",False),("R","R",False),
                              ("SB","SB",False),("AVG","AVG",False)]

                if _gp2 < 5:
                    continue

                _scale2 = 162.0 / max(_gp2, 1)
                _diffs2 = []
                for _sk, _fk, _inv2 in _cats2:
                    _actual2 = float(_st0.get(_sk, 0) or 0)
                    _proj2   = float(_fg2.get(_fk, 0) or 0)
                    if _proj2 == 0:
                        continue
                    if _fk in ("AVG", "ERA", "WHIP"):
                        _pd = (_actual2 - _proj2) / abs(_proj2)
                        if _inv2:
                            _pd = -_pd
                    else:
                        _pct_pace = (_actual2 * _scale2 - _proj2) / abs(_proj2)
                        _pd = _pct_pace
                    _diffs2.append(_pd)

                if not _diffs2:
                    continue

                _avg_d2 = sum(_diffs2) / len(_diffs2)
                if _avg_d2 >= 0.20:
                    _sico, _slbl, _sbg = "🔥", "Hot",      "rgba(254,226,226,0.70)"
                elif _avg_d2 <= -0.20:
                    _sico, _slbl, _sbg = "❄️", "Cold",     "rgba(219,234,254,0.70)"
                else:
                    _sico, _slbl, _sbg = "✅", "On Track",  "rgba(240,253,244,0.70)"

                _streak_rows.append({
                    "Player":   _sp2.name,
                    "Pos":      pos_str(_sp2),
                    "Status":   f"{_sico} {_slbl}",
                    "Pace":     f"{_avg_d2:+.0%}",
                    "Roto Val": round(fg_roto_value(_sp2), 2),
                    "_diff":    _avg_d2,
                    "_bg":      _sbg,
                    "_icon":    _sico,
                })

            _hot_rows2  = sorted([r for r in _streak_rows if r["_diff"] >= 0.20],  key=lambda x: -x["_diff"])
            _cold_rows2 = sorted([r for r in _streak_rows if r["_diff"] <= -0.20], key=lambda x:  x["_diff"])
            _ok_rows2   = [r for r in _streak_rows if -0.20 < r["_diff"] < 0.20]

            if not _streak_rows:
                st.info("Not enough season data yet — check back once more games have been played.")
            else:
                _hc1, _hc2 = st.columns(2)

                def _streak_card_html(row, accent, arrow_cls):
                    bg       = row["_bg"]
                    arrow    = "↑↑" if arrow_cls == "trend-up" else "↓↓"
                    pace_clr = "#DC2626" if arrow_cls == "trend-up" else "#2563EB"
                    arr_clr  = pace_clr
                    return (
                        f"<div style='display:flex;align-items:center;gap:10px;"
                        f"border-radius:0 9px 9px 0;padding:9px 14px;margin-bottom:5px;"
                        f"font-size:13px;line-height:1.4;background:{bg};"
                        f"border-left:4px solid {accent}'>"
                        f"<span style='color:{arr_clr};font-weight:800;font-size:14px'>{arrow}</span>"
                        f"<div style='flex:1'>"
                        f"<b style='font-size:13px'>{row['Player']}</b>"
                        f"<span style='display:inline-block;font-size:10px;font-weight:700;"
                        f"padding:2px 7px;border-radius:20px;background:rgba(21,101,192,0.12);"
                        f"color:#1565C0;letter-spacing:0.3px;margin-left:5px;"
                        f"vertical-align:middle'>{row['Pos']}</span>"
                        f"</div>"
                        f"<b style='color:{pace_clr};font-size:13px'>{row['Pace']}</b>"
                        f"</div>"
                    )

                with _hc1:
                    st.markdown(
                        "<div style='font-size:12px;font-weight:800;color:#DC2626;"
                        "letter-spacing:0.5px;text-transform:uppercase;margin-bottom:10px'>"
                        "🔥 Running Hot — ride these players</div>",
                        unsafe_allow_html=True,
                    )
                    if _hot_rows2:
                        for _r2 in _hot_rows2[:5]:
                            st.markdown(_streak_card_html(_r2, "#EF4444", "trend-up"),
                                        unsafe_allow_html=True)
                    else:
                        _empty_state("😴", "No one running hot right now",
                                     "Check back as the season progresses")

                with _hc2:
                    st.markdown(
                        "<div style='font-size:12px;font-weight:800;color:#2563EB;"
                        "letter-spacing:0.5px;text-transform:uppercase;margin-bottom:10px'>"
                        "❄️ Running Cold — consider benching or trading</div>",
                        unsafe_allow_html=True,
                    )
                    if _cold_rows2:
                        for _r2 in _cold_rows2[:5]:
                            st.markdown(_streak_card_html(_r2, "#3B82F6", "trend-down"),
                                        unsafe_allow_html=True)
                    else:
                        _empty_state("🎉", "No one in a significant slump",
                                     "Your roster is performing as expected")

                with st.expander("📋 Full Roster — Pace vs Projection", expanded=False):
                    _all_sorted2 = _hot_rows2 + _ok_rows2 + _cold_rows2
                    st.dataframe(
                        pd.DataFrame([{
                            "Player":   r["Player"],
                            "Pos":      r["Pos"],
                            "Status":   r["Status"],
                            "Pace %":   r["Pace"],
                            "Roto Val": r["Roto Val"],
                        } for r in _all_sorted2]),
                        use_container_width=True, hide_index=True,
                        column_config={
                            "Status":   st.column_config.TextColumn("Streak",       width="small"),
                            "Pace %":   st.column_config.TextColumn("Pace vs Proj", width="small"),
                            "Roto Val": roto_cfg(),
                        },
                    )

            # ── A7. GM Daily To-Do Checklist (fills the placeholder near the top) ──────
        _todo_items = []   # list of (priority, icon, text)
        _HIGH, _MED, _LOW = "high", "med", "low"

        # URGENT: injured starters needing replacement
        for _p in my_team.roster:
            _st = getattr(_p, "injuryStatus", "ACTIVE")
            if _st in ("INJURY_RESERVE", "OUT"):
                _todo_items.append((_HIGH, "🏥",
                    f"**{_p.name}** is {_st.replace('_',' ')} — find a replacement now."))

        # URGENT: best FA add if meaningful net gain
        if _fo_add_rows and _fo_add_rows[0].get("Net", 0) > 0.4:
            _best = _fo_add_rows[0]
            _drop_txt = f", drop **{_best['Drop']}**" if _best["Drop"] != "—" else ""
            _todo_items.append((_HIGH, "🆓",
                f"Claim **{_best['Add']}** (net **+{_best['Net']:.1f}**){_drop_txt} — "
                f"helps your **{_best['Helps']}**."))

        # HIGH: two-start SP available
        if _fa_two_start:
            _ts_name = _fa_two_start[0][0]
            _todo_items.append((_HIGH, "📅",
                f"Stream **{_ts_name}** — two starts this week, best available on waivers."))

        # HIGH: pitchers starting today (ride them, check lineups)
        if _my_starting_today:
            _names_today = ", ".join(f"**{p.name}**" for p, _ in _my_starting_today)
            _todo_items.append((_HIGH, "⚾",
                f"{_names_today} {'start' if len(_my_starting_today) > 1 else 'starts'} today — "
                "confirm they're active in your lineup."))

        # MEDIUM: hot players to make sure they're starting
        if _hot_rows2:
            _todo_items.append((_MED, "🔥",
                f"**{_hot_rows2[0]['Player']}** is your hottest player "
                f"({_hot_rows2[0]['Pace']} vs projection) — make sure they're in your active lineup."))

        # MEDIUM: cold players to consider benching
        if _cold_rows2:
            _todo_items.append((_MED, "❄️",
                f"**{_cold_rows2[0]['Player']}** is running cold "
                f"({_cold_rows2[0]['Pace']} vs projection) — "
                "consider a short bench or look for a swap."))

        # MEDIUM: flippable matchup categories
        if _close_cats_fo:
            _todo_items.append((_MED, "⚡",
                f"You're within striking distance in **{', '.join(_close_cats_fo)}** this week — "
                "one good streaming move could flip these categories."))

        # MEDIUM: doubtful/questionable players to monitor
        _dtd_players = [
            p for p in my_team.roster
            if getattr(p, "injuryStatus", "ACTIVE") in ("DOUBTFUL", "QUESTIONABLE")
        ]
        if _dtd_players:
            _dtd_names = ", ".join(f"**{p.name}**" for p in _dtd_players[:3])
            _todo_items.append((_MED, "⚠️",
                f"Check injury reports for {_dtd_names} before locking your lineup."))

        # LOW: routine weekly reminders
        _todo_items.append((_LOW, "📊",
            "Review the **Category Gap Tracker** — know exactly how many HR/SB/K "
            "you need to gain or protect this week."))
        _todo_playoff_cutoff = max(1, round(_n / 2))
        if _my_season_rank_pre <= _todo_playoff_cutoff:
            _todo_items.append((_LOW, "🛡️",
                f"You're **#{_my_season_rank_pre}** and in playoff position — "
                "don't make panic trades. Protect your category leads."))
        else:
            _todo_items.append((_LOW, "📈",
                f"You're **#{_my_season_rank_pre}**, outside the playoff line — "
                "be aggressive. The status quo won't get you in."))

        # Build the To-Do HTML and fill placeholder
        def _todo_row(icon, text, bg, border):
            return (
                f"<div style='background:{bg};border-left:3px solid {border};"
                f"border-radius:0 8px 8px 0;padding:9px 14px;"
                f"margin-bottom:6px;font-size:13px;line-height:1.5'>"
                f"{icon} {text}</div>"
            )

        _todo_html = (
            "<div style='background:linear-gradient(135deg,#0F3460,#1565C0);"
            "border-radius:14px;padding:18px 22px;margin-bottom:6px'>"
            "<div style='font-size:10px;font-weight:800;color:rgba(255,255,255,0.55);"
            "letter-spacing:1.3px;margin-bottom:14px'>📋 TODAY'S GM CHECKLIST</div>"
        )
        _section_map = {
            _HIGH: ("rgba(254,226,226,0.90)", "#EF4444"),
            _MED:  ("rgba(254,243,199,0.90)", "#F59E0B"),
            _LOW:  ("rgba(240,253,244,0.90)", "#22C55E"),
        }
        _prev_pri = None
        for _pri, _ico, _txt in _todo_items:
            if _pri != _prev_pri:
                _label = {"high": "🔴 URGENT", "med": "🟡 TODAY", "low": "🟢 THIS WEEK"}[_pri]
                _todo_html += (
                    f"<div style='font-size:10px;font-weight:800;"
                    f"color:rgba(255,255,255,0.45);letter-spacing:1px;"
                    f"margin:{'12px' if _prev_pri else '0'} 0 6px 0'>{_label}</div>"
                )
                _prev_pri = _pri
            _bg_c, _bd_c = _section_map[_pri]
            _todo_html += _todo_row(_ico, _txt, _bg_c, _bd_c)

        _todo_html += "</div>"
        _todo_ph.markdown(_todo_html, unsafe_allow_html=True)


    with _fo_tab_season:
        st.caption(
            "Your season-long standing and strategic priorities — reflects your current roster and FanGraphs projections."
        )

        # ── B1. Standing Snapshot ─────────────────────────────────────────────────
        _section_header("🏆", "Where You Stand", "Projected season-long roto standings")

        # Compute total roto points per team (sum of category ranks)
        _season_pts = {}
        for _t_name, _ranks in _tr.items():
            _season_pts[_t_name] = sum(_ranks.get(c, _n) for c in _ALL_CATS)

        _ranked_teams = sorted(_season_pts.items(), key=lambda x: x[1], reverse=True)
        _my_season_pts = _season_pts.get(my_team.team_name, 0)
        _my_season_rank = next(
            (i + 1 for i, (n, _) in enumerate(_ranked_teams) if n == my_team.team_name), _n
        )
        _pts_to_first = (_ranked_teams[0][1] - _my_season_pts) if _ranked_teams else 0
        _pts_to_playoffs = 0
        _playoff_cutoff = max(1, round(_n / 2))  # top half makes playoffs
        if _my_season_rank > _playoff_cutoff and len(_ranked_teams) >= _playoff_cutoff:
            _pts_to_playoffs = _ranked_teams[_playoff_cutoff - 1][1] - _my_season_pts

        _sb1, _sb2, _sb3, _sb4 = st.columns(4)
        _sb1.metric("Season Rank",        f"#{_my_season_rank} of {_n}")
        _sb2.metric("Projected Roto Pts", f"{_my_season_pts}")
        _sb3.metric(
            "Gap to 1st",
            f"{abs(int(_pts_to_first))} pts",
            delta=f"{'Behind' if _pts_to_first < 0 else '1st place!'}",
            delta_color="inverse" if _pts_to_first < 0 else "normal",
        )
        _sb4.metric(
            "Playoff Bubble",
            f"{'In ✅' if _my_season_rank <= _playoff_cutoff else 'Out ❌'}",
            delta=(
                f"{abs(int(_pts_to_playoffs))} pts back"
                if _pts_to_playoffs > 0 else "You're in"
            ),
            delta_color="inverse" if _pts_to_playoffs > 0 else "normal",
        )

        # ── B2. Category Grade Card ────────────────────────────────────────────────
        _section_header("📋", "Category Report Card",
                        f"Projected rank per roto category · 1 = best · {_n} = worst · green top 3 · red bottom 3")

        _cat_cols_a = st.columns(5)
        _cat_cols_b = st.columns(5)
        for _i, _cat in enumerate(_ALL_CATS):
            _rk      = _my_ranks.get(_cat, _n)
            _val_fmt = (f"{_my_proj.get(_cat, 0):.3f}"
                        if _cat in ("AVG", "ERA", "WHIP")
                        else f"{int(_my_proj.get(_cat, 0))}")
            # Rank percentile: 0 = best (rank 1), 1 = worst (rank _n)
            _pct     = (_rk - 1) / max(_n - 1, 1)
            # Progress bar: full green at rank 1, full red at rank _n
            _bar_clr = (
                "#22C55E" if _rk <= 3
                else "#EF4444" if _rk >= _n - 2
                else "#F59E0B"
            )
            _card_bg = (
                "linear-gradient(135deg,#F0FDF4,#DCFCE7)" if _rk <= 3
                else "linear-gradient(135deg,#FFF5F5,#FEE2E2)" if _rk >= _n - 2
                else "linear-gradient(135deg,#FFFBEB,#FEF3C7)"
            )
            _rank_lbl_clr = (
                "#15803D" if _rk <= 3
                else "#B91C1C" if _rk >= _n - 2
                else "#92400E"
            )
            _bar_fill = max(4, int((1 - _pct) * 100))   # invert: rank 1 = 100% fill
            _col = (_cat_cols_a if _i < 5 else _cat_cols_b)[_i % 5]
            _col.markdown(
                f"<div style='text-align:center;background:{_card_bg};"
                f"border:1px solid rgba(0,0,0,0.06);border-radius:12px;"
                f"padding:12px 6px 10px;margin:2px'>"
                f"<div style='font-size:10px;color:#64748B;font-weight:800;"
                f"letter-spacing:0.8px;text-transform:uppercase'>{_cat}</div>"
                f"<div style='font-size:20px;font-weight:900;color:#0F3460;"
                f"margin:5px 0 2px;line-height:1'>{_val_fmt}</div>"
                f"<div style='font-size:13px;font-weight:800;color:{_rank_lbl_clr};"
                f"margin-bottom:8px'>#{_rk} of {_n}</div>"
                f"<div style='height:5px;background:rgba(0,0,0,0.08);"
                f"border-radius:99px;overflow:hidden;margin:0 8px'>"
                f"<div style='height:100%;width:{_bar_fill}%;background:{_bar_clr};"
                f"border-radius:99px;transition:width 0.4s ease'></div>"
                f"</div></div>",
                unsafe_allow_html=True,
            )

        # ── B3. Strategic Action Plan ─────────────────────────────────────────────
        _section_header("🎯", "Your Action Plan",
                        "Prioritized moves — big strategic shifts down to quick weekly tweaks")

        _strong_cats = [c for c in _ALL_CATS if _my_ranks.get(c, _n) <= 3]
        _weak_cats   = [c for c in _ALL_CATS if _my_ranks.get(c, _n) >= _n - 2]
        _mid_cats    = [c for c in _ALL_CATS if c not in _strong_cats and c not in _weak_cats]

        # Generate action items
        _big_actions, _med_actions, _small_actions = [], [], []

        # BIG: structural roster holes
        if "SV" in _weak_cats:
            _best_sv_fa = next(
                (_fa for _fa in _fo_fa_pool
                 if is_pitcher(_fa) and not fg.get(_fa.name, {}).get("ERA")
                 and fg.get(_fa.name, {}).get("SV", 0) and
                 float(fg.get(_fa.name, {}).get("SV", 0)) > 10), None
            )
            _fa_sv_hint = f" Best available closer: **{_best_sv_fa.name}**." if _best_sv_fa else ""
            _big_actions.append(
                f"🔒 **You're struggling in SV (#{_my_ranks.get('SV',_n)})** — "
                f"your bullpen needs a real closer.{_fa_sv_hint} "
                "Target a save source in trades or use the Closer Monitor."
            )
        if "SB" in _weak_cats:
            _big_actions.append(
                f"🏃 **You're last in SB (#{_my_ranks.get('SB',_n)})** — "
                "speed is very hard to add mid-season. Look for a trade that brings speed "
                "even if you give up power, or stream speedsters from the waiver wire."
            )
        if len(_weak_cats) >= 3:
            _big_actions.append(
                f"🎯 **You're in the bottom 3 in {len(_weak_cats)} categories** "
                f"({', '.join(_weak_cats)}). Consider the Punt Advisor — "
                "deliberately punting 1-2 of these frees you to dominate the others."
            )
        if _my_season_rank > _playoff_cutoff:
            _big_actions.append(
                f"⚠️ **You're currently outside the playoff line** (#{_my_season_rank}, "
                f"need top {_playoff_cutoff}). Time to get aggressive on trades and "
                "high-upside waiver adds — playing it safe won't move the needle."
            )
        if not _big_actions:
            _big_actions.append(
                f"✅ **No major structural issues.** You're in a strong position "
                f"(#{_my_season_rank}). Focus on maintaining your edges in {', '.join(_strong_cats[:3])} "
                "and chipping away at the gap to 1st."
            )

        # MEDIUM: roster optimization
        _neg_players = sorted(
            [_p for _p in my_team.roster if fg_roto_value(_p) < -0.3],
            key=fg_roto_value,
        )
        if _neg_players:
            _neg_list = ", ".join(
                f"**{_p.name}** ({fg_roto_value(_p):+.2f})" for _p in _neg_players[:3]
            )
            _med_actions.append(
                f"📋 **Roster cleanup needed**: {_neg_list} — "
                "these players are dragging down your category totals. "
                "Check the Waiver Wire tab for upgrades."
            )

        # Close categories you could flip
        _close_season = [
            c for c in _ALL_CATS
            if _n // 2 < _my_ranks.get(c, _n) <= _n // 2 + 2   # just below median
        ]
        if _close_season:
            _med_actions.append(
                f"📈 **Close to flipping**: you're just outside the top half in "
                f"**{', '.join(_close_season)}**. A targeted FA add or trade in these "
                "categories could jump you 1-2 standings spots."
            )

        _il_count = sum(
            1 for _p in my_team.roster
            if getattr(_p, "injuryStatus", "ACTIVE") in ("INJURY_RESERVE", "OUT")
        )
        if _il_count > 0:
            _med_actions.append(
                f"🏥 **{_il_count} player(s) on IL/Out** — "
                "their roster spots are dead weight until they return. "
                "Use the Emergency Replacements tool to find the best fill-ins."
            )

        if not _med_actions:
            _med_actions.append(
                "✅ Your roster is in solid shape. Focus on weekly streaming to maximize "
                "games played and pitcher starts."
            )

        # SMALL: weekly tactics
        _small_actions.append(
            "⚡ **Check the Two-Start Pitchers tracker** above every Monday — "
            "grabbing a two-start SP for a week is the single highest-leverage free move in roto."
        )

        _cat_gap_weak = [c for c in _weak_cats if c in _BAT_CATS_S]
        if _cat_gap_weak:
            _small_actions.append(
                f"📊 **Stream hitters** with favorable matchups to close the gap in "
                f"**{', '.join(_cat_gap_weak)}**. Check the Category Gap Tracker to see "
                "exactly how many units you need."
            )

        if _strong_cats:
            _small_actions.append(
                f"🛡️ **Protect your leads** in **{', '.join(_strong_cats[:3])}** — "
                "don't trade these strengths away for speculative upgrades elsewhere."
            )

        # Render action plan — build self-contained HTML to avoid orphaned </div> tags
        import re as _re
        def _md_bold(text):
            """Convert **bold** markdown to <b> HTML tags."""
            return _re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)

        def _action_card_html(actions, bg, border_clr, label_clr, label):
            items = "".join(
                f"<li style='margin-bottom:7px;line-height:1.5'>{_md_bold(a)}</li>"
                for a in actions
            )
            return (
                f"<div style='background:{bg};border:1px solid {border_clr};"
                f"border-radius:12px;padding:14px 16px'>"
                f"<div style='font-size:13px;font-weight:800;color:{label_clr};"
                f"margin-bottom:10px;letter-spacing:0.3px'>{label}</div>"
                f"<ul style='margin:0;padding-left:18px;font-size:13px;"
                f"color:#374151;line-height:1.6'>{items}</ul>"
                f"</div>"
            )

        _ap1, _ap2, _ap3 = st.columns(3)
        with _ap1:
            st.markdown(_action_card_html(
                _big_actions,
                "rgba(239,68,68,0.07)", "rgba(239,68,68,0.25)", "#B91C1C", "🔴 BIG MOVES",
            ), unsafe_allow_html=True)
        with _ap2:
            st.markdown(_action_card_html(
                _med_actions,
                "rgba(234,179,8,0.07)", "rgba(234,179,8,0.30)", "#92400E", "🟡 MEDIUM MOVES",
            ), unsafe_allow_html=True)
        with _ap3:
            st.markdown(_action_card_html(
                _small_actions,
                "rgba(34,197,94,0.07)", "rgba(34,197,94,0.25)", "#15803D", "🟢 SMALL MOVES",
            ), unsafe_allow_html=True)

        st.divider()

        # ── B4. Opponent Scouting Report ──────────────────────────────────────────
        _section_header("⚔️", "Opponent Scouting Report",
                        f"Week {_week_num} vs {_opp_name_fo} — where to attack, where to defend")

        if _opp_fo:
            _opp_ranks_sc = _tr.get(_opp_name_fo, {})
            _my_ranks_sc  = _tr.get(my_team.team_name, {})
            _attack_cats, _defend_cats, _even_cats = [], [], []
            for _cat in _ALL_CATS:
                _myrk  = _my_ranks_sc.get(_cat, _n)
                _opprk = _opp_ranks_sc.get(_cat, _n)
                _diff  = _opprk - _myrk          # positive = I'm ranked better
                if   _diff >= 2:  _attack_cats.append((_cat, _myrk, _opprk))
                elif _diff <= -2: _defend_cats.append((_cat, _myrk, _opprk))
                else:             _even_cats.append((_cat, _myrk, _opprk))

            _sc1, _sc2, _sc3 = st.columns(3)
            def _scout_row(cat, myrk, opprk, bg, border):
                return (
                    f"<div style='background:{bg};border-left:3px solid {border};"
                    f"border-radius:0 8px 8px 0;padding:7px 11px;margin-bottom:5px;font-size:13px'>"
                    f"<b>{cat}</b>&nbsp;&nbsp;"
                    f"<span style='color:#64748B;font-size:11px'>You #{myrk} · Them #{opprk}</span>"
                    f"</div>"
                )
            with _sc1:
                st.markdown(
                    "<div style='font-size:12px;font-weight:800;color:#15803D;"
                    "letter-spacing:0.5px;text-transform:uppercase;margin-bottom:8px'>"
                    "⚔️ Attack — You're Stronger</div>", unsafe_allow_html=True)
                if _attack_cats:
                    for _c, _mr, _or in sorted(_attack_cats, key=lambda x: x[2]-x[1], reverse=True):
                        st.markdown(_scout_row(_c,_mr,_or,"rgba(34,197,94,0.08)","#22C55E"),
                                    unsafe_allow_html=True)
                else:
                    _empty_state("🤝", "No clear advantages this week", "Evenly matched across categories")
            with _sc2:
                st.markdown(
                    "<div style='font-size:12px;font-weight:800;color:#B91C1C;"
                    "letter-spacing:0.5px;text-transform:uppercase;margin-bottom:8px'>"
                    "🛡️ Defend — They're Stronger</div>", unsafe_allow_html=True)
                if _defend_cats:
                    for _c, _mr, _or in sorted(_defend_cats, key=lambda x: x[1]-x[2], reverse=True):
                        st.markdown(_scout_row(_c,_mr,_or,"rgba(239,68,68,0.08)","#EF4444"),
                                    unsafe_allow_html=True)
                else:
                    _empty_state("💪", "No categories where they dominate you")
            with _sc3:
                st.markdown(
                    "<div style='font-size:12px;font-weight:800;color:#64748B;"
                    "letter-spacing:0.5px;text-transform:uppercase;margin-bottom:8px'>"
                    "⚖️ Toss-Up — Too Close to Call</div>", unsafe_allow_html=True)
                if _even_cats:
                    for _c, _mr, _or in _even_cats:
                        st.markdown(_scout_row(_c,_mr,_or,"rgba(148,163,184,0.08)","#94A3B8"),
                                    unsafe_allow_html=True)
                else:
                    _empty_state("📊", "No evenly matched categories")
        else:
            _empty_state("⚔️", "No opponent data yet", "Check back once the week's matchup is confirmed")

        st.divider()

        # ── B5. Injury Impact Calculator ──────────────────────────────────────────
        _section_header("🏥", "Injury Impact Calculator",
                        "Roto value lost to injuries — and the best available FA replacement for each")

        _il_players = [
            _p for _p in my_team.roster
            if getattr(_p, "injuryStatus", "ACTIVE") in ("INJURY_RESERVE", "OUT", "DOUBTFUL")
        ]
        if _il_players:
            _total_lost = sum(max(0.0, fg_roto_value(_p)) for _p in _il_players)
            st.markdown(
                f"<div style='background:rgba(239,68,68,0.07);border:1px solid rgba(239,68,68,0.25);"
                f"border-radius:12px;padding:13px 18px;margin-bottom:14px'>"
                f"<span style='color:#B91C1C;font-weight:700'>⚠️ Estimated roto value lost to injuries: </span>"
                f"<span style='font-size:20px;font-weight:900;color:#991B1B'>{_total_lost:.2f} pts</span>"
                f"<span style='color:#64748B;font-size:12px;margin-left:10px'>"
                f"across {len(_il_players)} player(s)</span></div>",
                unsafe_allow_html=True,
            )
            for _ip in sorted(_il_players, key=fg_roto_value, reverse=True):
                _ip_rv     = fg_roto_value(_ip)
                _ip_status = getattr(_ip, "injuryStatus", "ACTIVE")
                _ip_pos    = getattr(_ip, "position", "?")
                _stat_clr  = "#B91C1C" if _ip_status in ("INJURY_RESERVE","OUT") else "#92400E"
                _best_repl = max(
                    (_fa for _fa in _fo_fa_pool
                     if _ip_pos in (getattr(_fa,"eligibleSlots",[]) or [getattr(_fa,"position","?")])),
                    key=fg_roto_value, default=None,
                )
                _repl_txt = (
                    f"Best FA replacement: <b>{_best_repl.name}</b> "
                    f"({fg_roto_value(_best_repl):+.2f} roto val)"
                    if _best_repl else "No clear FA replacement available at this position"
                )
                st.markdown(
                    f"<div style='background:#FFF5F5;border-left:4px solid #EF4444;"
                    f"border-radius:0 10px 10px 0;padding:9px 14px;margin-bottom:6px;font-size:13px'>"
                    f"<b>{_ip.name}</b>&nbsp;"
                    f"<span style='color:{_stat_clr};font-size:11px;font-weight:800'>[{_ip_status}]</span>"
                    f"&nbsp;·&nbsp;Roto Val: <b>{_ip_rv:+.2f}</b><br>"
                    f"<span style='color:#64748B;font-size:12px'>{_repl_txt}</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
        else:
            _empty_state("💪", "Full squad available — no IL or Out players",
                         "Keep an eye on the injury report before setting your lineup")

        st.divider()

        with st.expander("📈 Trade Value Movers", expanded=False):
            # ── B6. Trade Value Movers ─────────────────────────────────────────────────
            _section_header("📈", "Trade Value Movers",
                            "Outperforming = sell-high window open · Underperforming = buy-low target for opponents")

            _tv_rows = []
            for _p in my_team.roster:
                _fg_data = fg.get(_p.name, {})
                if not _fg_data:
                    continue
                _stats_b = (_p.stats or {}).get(0, {}).get("breakdown", {})
                if is_pitcher(_p):
                    _proj_k  = float(_fg_data.get("K",  0))
                    _actual_ip = float(_stats_b.get("inningsPitched", 0))
                    _actual_k  = float(_stats_b.get("strikeouts",     0))
                    if _proj_k > 5 and _actual_ip > 5:
                        _pace   = _actual_k / max(_actual_ip, 1) * 200   # ~200 IP season
                        _ratio  = _pace / max(_proj_k, 1)
                        _tv_rows.append({"Player":_p.name,"Pos":getattr(_p,"position","?"),
                                         "Stat":"K pace","Pace":round(_pace),"Proj":round(_proj_k),
                                         "Ratio":_ratio})
                else:
                    _proj_hr = float(_fg_data.get("HR", 0))
                    _actual_hr = float(_stats_b.get("homeRuns", 0))
                    _gp        = float(_stats_b.get("gamesPlayed", 0))
                    if _proj_hr > 3 and _gp > 10:
                        _pace  = _actual_hr / max(_gp, 1) * 162
                        _ratio = _pace / max(_proj_hr, 1)
                        _tv_rows.append({"Player":_p.name,"Pos":getattr(_p,"position","?"),
                                         "Stat":"HR pace","Pace":round(_pace),"Proj":round(_proj_hr),
                                         "Ratio":_ratio})

            _sell_high = sorted([r for r in _tv_rows if r["Ratio"] > 1.25],
                                key=lambda x: x["Ratio"], reverse=True)
            _buy_low   = sorted([r for r in _tv_rows if r["Ratio"] < 0.75],
                                key=lambda x: x["Ratio"])

            _tv1, _tv2 = st.columns(2)
            with _tv1:
                st.markdown(
                    "<div style='font-size:12px;font-weight:800;color:#DC2626;"
                    "letter-spacing:0.5px;text-transform:uppercase;margin-bottom:8px'>"
                    "🔴 Sell High — Outperforming Projections</div>",
                    unsafe_allow_html=True)
                if _sell_high:
                    for _r in _sell_high[:5]:
                        _pct = int((_r["Ratio"] - 1) * 100)
                        st.markdown(
                            f"<div style='background:rgba(239,68,68,0.07);border-left:3px solid #EF4444;"
                            f"border-radius:0 8px 8px 0;padding:7px 12px;margin-bottom:4px;font-size:13px'>"
                            f"<b>{_r['Player']}</b><span class='pos-badge'>{_r['Pos']}</span><br>"
                            f"<span style='color:#64748B;font-size:12px'>{_r['Stat']}: {_r['Pace']} "
                            f"vs proj {_r['Proj']} "
                            f"<b style='color:#DC2626'>(+{_pct}%)</b> — trade value is high</span>"
                            f"</div>",
                            unsafe_allow_html=True)
                else:
                    _empty_state("😐", "No clear sell-high candidates right now")
            with _tv2:
                st.markdown(
                    "<div style='font-size:12px;font-weight:800;color:#2563EB;"
                    "letter-spacing:0.5px;text-transform:uppercase;margin-bottom:8px'>"
                    "🟢 Buy Low — Underperforming Projections</div>",
                    unsafe_allow_html=True)
                if _buy_low:
                    for _r in _buy_low[:5]:
                        _pct = int((1 - _r["Ratio"]) * 100)
                        st.markdown(
                            f"<div style='background:rgba(37,99,235,0.07);border-left:3px solid #3B82F6;"
                            f"border-radius:0 8px 8px 0;padding:7px 12px;margin-bottom:4px;font-size:13px'>"
                            f"<b>{_r['Player']}</b><span class='pos-badge'>{_r['Pos']}</span><br>"
                            f"<span style='color:#64748B;font-size:12px'>{_r['Stat']}: {_r['Pace']} "
                            f"vs proj {_r['Proj']} "
                            f"<b style='color:#2563EB'>(-{_pct}%)</b> — opponents may trade cheap</span>"
                            f"</div>",
                            unsafe_allow_html=True)
                else:
                    _empty_state("🎯", "No clear buy-low targets right now")

            st.divider()

            # ── B7. Bench Optimization ────────────────────────────────────────────────
        _section_header("🪑", "Bench Optimization",
                        "Bench players currently outprojecting active starters at the same slot")

        _bench_ps  = [_p for _p in my_team.roster
                      if getattr(_p,"lineupSlot","") in ("BE","BN","Bench")]
        _active_ps = [_p for _p in my_team.roster
                      if getattr(_p,"lineupSlot","") not in ("BE","BN","Bench","IL","IL+","NA")]
        _swaps = []
        for _bp in _bench_ps:
            _bp_rv    = fg_roto_value(_bp)
            _bp_slots = set(getattr(_bp,"eligibleSlots",[]) or [getattr(_bp,"position","?")])
            _candidates = [
                _ap for _ap in _active_ps
                if set(getattr(_ap,"eligibleSlots",[]) or [getattr(_ap,"position","?")]) & _bp_slots
            ]
            if not _candidates:
                continue
            _worst_active = min(_candidates, key=fg_roto_value)
            _wa_rv = fg_roto_value(_worst_active)
            _gain  = _bp_rv - _wa_rv
            if _gain > 0.15:
                _clean_slots = ", ".join(
                    s for s in sorted(_bp_slots) if s not in ("BE","BN","Bench","IL","IL+","NA")
                ) or "UTIL"
                _swaps.append({
                    "Bench Player":  _bp.name,
                    "Bench RV":      round(_bp_rv, 2),
                    "Start Instead": _worst_active.name,
                    "Active RV":     round(_wa_rv, 2),
                    "RV Gain":       round(_gain, 2),
                    "Slot":          _clean_slots,
                })

        if _swaps:
            st.dataframe(
                pd.DataFrame(sorted(_swaps, key=lambda x: x["RV Gain"], reverse=True)),
                use_container_width=True, hide_index=True,
                column_config={
                    "Bench Player":  st.column_config.TextColumn("✅ Start This",   width="medium"),
                    "Bench RV":      roto_cfg("Their RV"),
                    "Start Instead": st.column_config.TextColumn("🪑 Bench This",  width="medium"),
                    "Active RV":     roto_cfg("Their RV"),
                    "RV Gain":       roto_cfg("Gain ↑"),
                    "Slot":          st.column_config.TextColumn("Slot",            width="small"),
                }
            )
            st.caption(
                "Activate **✅ Start This** and move **🪑 Bench This** to the bench — "
                "projected roto value improvement shown in **Gain ↑**."
            )
        else:
            _empty_state("✅", "Lineup is optimized — active players outproject all bench options",
                         "Check back after roster moves or injuries")

        st.divider()

        with st.expander("📊 Full Projected Standings", expanded=False):
            # ── B8. Full Projected Standings ─────────────────────────────────────────
            with st.expander("📊 Full Projected Standings (all teams)", expanded=False):
                _standings_rows = []
                for _i, (_tname, _tpts) in enumerate(_ranked_teams, 1):
                    _standings_rows.append({
                        "Rank":       f"#{_i}",
                        "Team":       _tname,
                        "Roto Pts":   _tpts,
                        "Strong Cats": ", ".join(
                            c for c in _ALL_CATS if _tr.get(_tname, {}).get(c, _n) <= 3
                        ) or "—",
                        "Weak Cats":  ", ".join(
                            c for c in _ALL_CATS if _tr.get(_tname, {}).get(c, _n) >= _n - 2
                        ) or "—",
                    })
                _std_df = pd.DataFrame(_standings_rows)

                def _my_team_row_style(row):
                    if row.get("Team", "") == my_team.team_name:
                        return ["background-color:rgba(21,101,192,0.10);font-weight:700"] * len(row)
                    return [""] * len(row)

                st.dataframe(
                    _std_df.style.apply(_my_team_row_style, axis=1),
                    use_container_width=True, hide_index=True,
                    column_config={
                        "Rank":        st.column_config.TextColumn("Rank",         width="small"),
                        "Team":        st.column_config.TextColumn("Team",         width="medium"),
                        "Roto Pts":    num_cfg("Roto Pts"),
                        "Strong Cats": st.column_config.TextColumn("Winning",      width="medium"),
                        "Weak Cats":   st.column_config.TextColumn("Needs Help",   width="medium"),
                    },
                )

    # ─────────────────────────────────────────────────────────────────────────────
    # TAB 1: LINEUP OPTIMIZER
    # ─────────────────────────────────────────────────────────────────────────────
with tab1:
    st.header("Lineup Optimizer")
    st.caption(f"Ranks your rostered players by **{fg_proj_label}** (FanGraphs) projected roto value — sum of category z-scores.")

    roster = my_team.roster
    if not roster:
        st.warning("No roster data available.")
    else:
        rows = []
        for p in roster:
            proj = fg_roto_value(p)
            ps = prev_stats.get(p.name, {})
            player_id = getattr(p, "playerId", None)
            photo_url = (f"https://a.espncdn.com/i/headshots/mlb/players/full/{player_id}.png"
                         if player_id else "")

            # Use actual 2025 ESPN stats when available; fall back to FanGraphs projections
            if ps:
                pitcher = is_pitcher(p)
                if pitcher:
                    stat_vals = {
                        "HR": _DASH, "R": _DASH, "RBI": _DASH, "SB": _DASH, "AVG": _DASH,
                        "W":    _fmt_stat(ps.get("W")),
                        "ERA":  _fmt_stat(ps.get("ERA"),  2),
                        "WHIP": _fmt_stat(ps.get("WHIP"), 2),
                        "K":    _fmt_stat(ps.get("K")),
                        "SV":   _fmt_stat(ps.get("SV")),
                    }
                else:
                    stat_vals = {
                        "HR":  _fmt_stat(ps.get("HR")),
                        "R":   _fmt_stat(ps.get("R")),
                        "RBI": _fmt_stat(ps.get("RBI")),
                        "SB":  _fmt_stat(ps.get("SB")),
                        "AVG": _fmt_stat(ps.get("AVG"), 3),
                        "W": _DASH, "ERA": _DASH, "WHIP": _DASH, "K": _DASH, "SV": _DASH,
                    }
            else:
                stat_vals = fg_stat_cols(p)

            g2025, g_ytd, g_proj = player_grades(p, prev_stats, fg)
            rows.append({
                "Photo": photo_url,
                "Player": p.name,
                "Position": pos_str(p),
                "Pro Team": p.proTeam if hasattr(p, "proTeam") else "—",
                f"Roto Value ({fg_proj_label})": proj,
                "Helps": roto_helps_str(p),
                "WAR": fg_war(p),
                "G '25": g2025,
                "G '26 YTD": g_ytd,
                "G '26 Proj": g_proj,
                **stat_vals,
                "🌡️ Heat": heat_label(heat_score(p, current_period)),
                "Status": getattr(p, "injuryStatus", "ACTIVE"),
            })

        proj_col = f"Roto Value ({fg_proj_label})"
        df = pd.DataFrame(rows).sort_values(proj_col, ascending=False)

        # Tag each row so we can split into hitters / pitchers
        pitcher_positions = {"SP", "RP", "P"}
        df["_is_pitcher"] = df["Position"].apply(
            lambda pos: bool(set(pos.split(", ")) & pitcher_positions)
        )
        hitters_df  = df[~df["_is_pitcher"]].drop(columns=["_is_pitcher"])
        pitchers_df = df[ df["_is_pitcher"]].drop(columns=["_is_pitcher"])

        has_prev = bool(prev_stats)
        stat_src_label = f"{prev_year} Actual" if has_prev else f"{cfg.get('year',2026)} Proj"

        def roster_section(tdf, stat_cols):
            display_cols = (["Photo", "Player", "Position", "Pro Team", proj_col, "Helps", "WAR"]
                            + GRADE_COLS + stat_cols + ["🌡️ Heat", "Status"])
            show_df = tdf[[c for c in display_cols if c in tdf.columns]]
            st.caption(f"📊 Stat columns show **{stat_src_label}** stats · Roto Value = sum of category z-scores · Grades: '25 / '26 YTD / '26 Proj")
            st.dataframe(
                apply_grade_colors(grey_na_stats(apply_badges(show_df))),
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Photo":    st.column_config.ImageColumn("", width="small"),
                    "Player":   st.column_config.TextColumn("Player", width="medium"),
                    "Position": st.column_config.TextColumn("Pos", width="small"),
                    "Pro Team": st.column_config.TextColumn("Team", width="small"),
                    proj_col:   roto_cfg("Roto Val"),
                    "Helps":    st.column_config.TextColumn("Helps", width="small",
                                    help="Categories where this player is above average"),
                    "WAR":      war_cfg(),
                    **GRADE_COL_CFG,
                    **STAT_COL_CFG,
                    "🌡️ Heat":  HEAT_CFG,
                    "Status":   st.column_config.TextColumn("Health", width="small"),
                }
            )

        st.subheader("⚾ Hitters")
        if hitters_df.empty:
            st.info("No hitters on roster.")
        else:
            roster_section(hitters_df, _BAT_COLS)

        st.subheader("🎯 Pitchers")
        if pitchers_df.empty:
            st.info("No pitchers on roster.")
        else:
            roster_section(pitchers_df, _PIT_COLS)

        # Simple slot-filling suggestion
        st.subheader("Suggested Lineup")
        slot_priority = ["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH", "SP", "RP"]
        clean_df = df.drop(columns=["_is_pitcher"], errors="ignore")
        available = clean_df[~clean_df["Status"].isin(["INJURY_RESERVE", "OUT"])].copy()
        used = set()
        suggestions = []

        for slot in slot_priority:
            candidates = available[
                available["Position"].str.contains(slot, na=False) &
                ~available["Player"].isin(used)
            ].head(1)
            if not candidates.empty:
                row = candidates.iloc[0].copy()
                row["Slot"] = slot
                suggestions.append(row)
                used.add(row["Player"])

        if suggestions:
            sug_df = apply_badges(
                pd.DataFrame(suggestions)[["Slot", "Player", "Position", "Pro Team", proj_col, "Status"]]
            )
            st.dataframe(
                sug_df, use_container_width=True, hide_index=True,
                column_config={
                    "Slot":     st.column_config.TextColumn("Slot", width="small"),
                    "Player":   st.column_config.TextColumn("Player", width="medium"),
                    "Position": st.column_config.TextColumn("Pos", width="small"),
                    "Pro Team": st.column_config.TextColumn("Team", width="small"),
                    proj_col:   roto_cfg("Roto Val"),
                    "Status":   st.column_config.TextColumn("Health", width="small"),
                }
            )
        else:
            st.info("Could not auto-generate lineup — check roster data.")

        # ── WAR Upgrade Chart ─────────────────────────────────────────────────
        st.divider()
        st.subheader("📈 WAR Upgrade Targets")
        st.caption("Free agents projected for higher WAR than someone on your roster.")

        import altair as alt

        my_war_map = {p.name: fg_war(p) for p in roster}
        min_my_war = min(my_war_map.values(), default=0.0)

        # Roster entries
        war_chart_rows = [
            {"Player": name, "WAR": war, "Group": "My Roster"}
            for name, war in my_war_map.items()
        ]
        # Free agents only, with WAR > my minimum
        with st.spinner("Loading free agents for WAR comparison…"):
            try:
                war_fa = league.free_agents(size=200)
            except Exception:
                war_fa = []
        for p in war_fa:
            w = fg_war(p)
            if w > min_my_war:
                war_chart_rows.append({"Player": p.name, "WAR": w, "Group": "Free Agent"})

        war_chart_df = (
            pd.DataFrame(war_chart_rows)
            .sort_values("WAR", ascending=False)
            .head(40)
        )

        if not war_chart_df.empty:
            chart = (
                alt.Chart(war_chart_df)
                .mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4)
                .encode(
                    y=alt.Y("Player:N", sort="-x", title=None,
                            axis=alt.Axis(labelFontSize=12, labelLimit=160)),
                    x=alt.X("WAR:Q", title="Projected WAR",
                            axis=alt.Axis(labelFontSize=11)),
                    color=alt.Color(
                        "Group:N",
                        scale=alt.Scale(
                            domain=["My Roster", "Free Agent"],
                            range=["#1565C0", "#F59E0B"],
                        ),
                        legend=alt.Legend(orient="top", title=None,
                                          labelFontSize=12),
                    ),
                    tooltip=[
                        alt.Tooltip("Player:N"),
                        alt.Tooltip("WAR:Q", format=".1f"),
                        alt.Tooltip("Group:N"),
                    ],
                )
                .properties(height=max(380, len(war_chart_df) * 22))
                .configure_view(strokeWidth=0)
                .configure_axis(grid=False)
            )
            st.altair_chart(chart, use_container_width=True)
        else:
            st.info("No upgrade targets found — your roster has strong WAR coverage!")

# ─────────────────────────────────────────────────────────────────────────────
# TAB 2: WAIVER WIRE
# ─────────────────────────────────────────────────────────────────────────────
with tab2:
    st.header("Waiver Wire Analyzer")
    st.caption("Top available free agents ranked by **roto value** (sum of FanGraphs category z-scores). Higher = more categories contributed.")

    col1, col2 = st.columns([1, 3])
    with col1:
        pos_filter = st.selectbox(
            "Filter by position",
            ["All", "C", "1B", "2B", "3B", "SS", "OF", "DH", "SP", "RP"],
        )
        top_n = st.slider("Show top N players", 10, 100, 30)

    with st.spinner("Loading free agents…"):
        try:
            if pos_filter == "All":
                fa = league.free_agents(size=top_n * 2)
            else:
                fa = league.free_agents(size=top_n * 2, position=pos_filter)

            fa_proj_col = f"Roto Value ({fg_proj_label})"
            fa_rows = []
            for p in fa:
                proj   = fg_roto_value(p)
                g2025, g_ytd, g_proj = player_grades(p, prev_stats, fg)
                fa_rows.append({
                    "Player": p.name,
                    "Position": pos_str(p),
                    "Pro Team": p.proTeam if hasattr(p, "proTeam") else "—",
                    fa_proj_col: proj,
                    "Helps": roto_helps_str(p),
                    "WAR": fg_war(p),
                    "G '25": g2025,
                    "G '26 YTD": g_ytd,
                    "G '26 Proj": g_proj,
                    **fg_stat_cols(p),
                    "🌡️ Heat": heat_label(heat_score(p, current_period)),
                    "Status": getattr(p, "injuryStatus", "ACTIVE"),
                })

            fa_df = (
                pd.DataFrame(fa_rows)
                .sort_values(fa_proj_col, ascending=False)
                .head(top_n)
            )

            if fa_df.empty:
                st.info("No free agents found for the selected filter.")
            else:
                st.dataframe(
                    apply_grade_colors(grey_na_stats(apply_badges(fa_df))),
                    use_container_width=True, hide_index=True,
                    column_config={
                        "Player":    st.column_config.TextColumn("Player", width="medium"),
                        "Position":  st.column_config.TextColumn("Pos", width="small"),
                        "Pro Team":  st.column_config.TextColumn("Team", width="small"),
                        fa_proj_col: roto_cfg("Roto Val"),
                        "Helps":     st.column_config.TextColumn("Helps", width="small",
                                         help="Categories where this player is above average"),
                        "WAR":       war_cfg(),
                        **GRADE_COL_CFG,
                        **STAT_COL_CFG,
                        "🌡️ Heat":   HEAT_CFG,
                        "Status":    st.column_config.TextColumn("Health", width="small"),
                    }
                )

                # ── Roto Upgrade Suggestions ──────────────────────────────────
                st.subheader("📈 Roto Upgrade Targets")
                st.caption("Free agents with higher **roto value** than your worst player at the same position — ranked by how much roto value you'd gain.")

                # Build per-slot map: worst roto player at each position
                my_roto_by_pos = {}
                for p in my_team.roster:
                    rv    = fg_roto_value(p)
                    slots = p.eligibleSlots if p.eligibleSlots else [p.position]
                    for slot in slots:
                        if slot not in my_roto_by_pos or rv < my_roto_by_pos[slot]["worst_rv"]:
                            my_roto_by_pos[slot] = {
                                "worst_rv":   rv,
                                "worst_name": p.name,
                            }

                upgrades = []
                for _, row in fa_df.iterrows():
                    for slot in row["Position"].split(", "):
                        slot = slot.strip()
                        if slot not in my_roto_by_pos:
                            continue
                        worst_rv   = my_roto_by_pos[slot]["worst_rv"]
                        worst_name = my_roto_by_pos[slot]["worst_name"]
                        gain       = row[fa_proj_col] - worst_rv
                        if gain > 0:
                            upgrades.append({
                                "Player":          row["Player"],
                                "Position":        row["Position"],
                                "Pro Team":        row["Pro Team"],
                                fa_proj_col:       row[fa_proj_col],
                                "Helps":           row["Helps"],
                                "Replaces Slot":   slot,
                                "Roto Gain":       round(gain, 2),
                                "Drop Candidate":  worst_name,
                                "Drop RV":         round(worst_rv, 2),
                                "Status":          row["Status"],
                            })
                            break

                if upgrades:
                    upg_df = apply_badges(
                        pd.DataFrame(upgrades).sort_values("Roto Gain", ascending=False)
                    )
                    st.dataframe(
                        upg_df, use_container_width=True, hide_index=True,
                        column_config={
                            "Player":          st.column_config.TextColumn("Player",         width="medium"),
                            "Position":        st.column_config.TextColumn("Pos",            width="small"),
                            "Pro Team":        st.column_config.TextColumn("Team",           width="small"),
                            fa_proj_col:       roto_cfg("Roto Val"),
                            "Helps":           st.column_config.TextColumn("Helps",          width="small"),
                            "Replaces Slot":   st.column_config.TextColumn("Slot",           width="small"),
                            "Roto Gain":       roto_cfg("Gain ↑"),
                            "Drop Candidate":  st.column_config.TextColumn("Drop Candidate", width="medium",
                                                   help="Weakest player on your roster at this position slot — "
                                                        "suggested drop to make room for this pickup"),
                            "Drop RV":         roto_cfg("Their RV"),
                            "Status":          st.column_config.TextColumn("Health",         width="small"),
                        }
                    )
                    st.caption(
                        "**Drop Candidate** = the player on your roster with the lowest roto value "
                        "at that position slot.  **Their RV** = their current projected roto value "
                        "— the lower it is, the easier the drop decision."
                    )
                else:
                    st.success("Your roster is already stronger than available free agents at every position!")

        except Exception as e:
            st.error(f"Could not load free agents: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# TAB 3: TEAM OVERVIEW
# ─────────────────────────────────────────────────────────────────────────────
with tab3:
    st.header("Team Overview")

    # Calculate points for/against from schedule
    def calc_points(team):
        pts_for, pts_against = 0.0, 0.0
        for match in team.schedule:
            if hasattr(match, 'home_team') and match.home_team == team:
                pts_for += match.home_final_score or 0
                pts_against += match.away_final_score or 0
            elif hasattr(match, 'away_team') and match.away_team == team:
                pts_for += match.away_final_score or 0
                pts_against += match.home_final_score or 0
        return pts_for, pts_against

    my_pts_for, my_pts_against = calc_points(my_team)

    col1, col2, col3 = st.columns(3)
    col1.metric("Record", f"{my_team.wins}-{my_team.losses}" + (f"-{my_team.ties}" if my_team.ties else ""))
    col2.metric("Roto Pts For", round(my_pts_for, 1))
    col3.metric("Roto Pts Against", round(my_pts_against, 1))

    # Overall standings
    st.subheader("League Standings")
    standings_rows = []
    for t in sorted(league.teams, key=lambda x: x.wins, reverse=True):
        pf, pa = calc_points(t)
        owner = t.owners[0] if t.owners else "—"
        standings_rows.append({
            "Team": t.team_name,
            "Owner": owner,
            "W": t.wins,
            "L": t.losses,
            "T": t.ties,
            "Roto Pts For": round(pf, 1),
            "Roto Pts Against": round(pa, 1),
        })
    st.dataframe(
        pd.DataFrame(standings_rows),
        use_container_width=True, hide_index=True,
        column_config={
            "Team":              st.column_config.TextColumn("Team", width="medium"),
            "Owner":             st.column_config.TextColumn("Owner", width="small"),
            "W":                 num_cfg("W"),
            "L":                 num_cfg("L"),
            "T":                 num_cfg("T"),
            "Roto Pts For":      pts_cfg("Roto Pts"),
            "Roto Pts Against":  pts_cfg("Roto Pts Against"),
        }
    )

    # ── Projected Roto Category Standings ─────────────────────────────────────
    st.divider()
    st.subheader("📊 Projected Category Standings")
    st.caption(f"Each team's projected season totals from **{fg_proj_label}** — ranked 1st to last per category. "
               "Shows where you're winning and losing the roto race.")

    _ROTO_ALL_CATS = ["HR", "R", "RBI", "SB", "AVG", "W", "SV", "K", "ERA", "WHIP"]
    _ROTO_LOWER_BETTER = {"ERA", "WHIP"}

    # Build per-team projected stat totals
    team_proj: dict = {}
    for t in league.teams:
        bat = {"HR": 0.0, "R": 0.0, "RBI": 0.0, "SB": 0.0,
               "_avg_num": 0.0, "_avg_den": 0.0}  # avg weighted by R (proxy AB)
        pit = {"W": 0.0, "SV": 0.0, "K": 0.0,
               "_era_runs": 0.0, "_whip_base": 0.0, "_ip": 0.0}
        for p in t.roster:
            entry = fg.get(p.name, {})
            if not entry:
                continue
            if is_pitcher(p):
                for cat in ("W", "SV", "K"):
                    pit[cat] += float(entry.get(cat) or 0)
                ip   = float(entry.get("IP")   or 0)
                era  = float(entry.get("ERA")  or 0)
                whip = float(entry.get("WHIP") or 0)
                pit["_ip"]        += ip
                pit["_era_runs"]  += era * ip / 9.0
                pit["_whip_base"] += whip * ip
            else:
                for cat in ("HR", "R", "RBI", "SB"):
                    bat[cat] += float(entry.get(cat) or 0)
                avg = float(entry.get("AVG") or 0)
                r   = float(entry.get("R")   or 1)   # use R as AB proxy
                bat["_avg_num"] += avg * r
                bat["_avg_den"] += r

        ip = pit["_ip"] if pit["_ip"] > 0 else 1.0
        team_proj[t.team_name] = {
            "HR":   round(bat["HR"],  0),
            "R":    round(bat["R"],   0),
            "RBI":  round(bat["RBI"], 0),
            "SB":   round(bat["SB"],  0),
            "AVG":  round(bat["_avg_num"] / bat["_avg_den"], 3) if bat["_avg_den"] > 0 else 0.0,
            "W":    round(pit["W"],  0),
            "SV":   round(pit["SV"], 0),
            "K":    round(pit["K"],  0),
            "ERA":  round(pit["_era_runs"] * 9.0 / ip, 2),
            "WHIP": round(pit["_whip_base"] / ip, 3),
        }

    # Rank teams in each category
    n_teams = len(league.teams)
    team_ranks: dict = {name: {} for name in team_proj}
    for cat in _ROTO_ALL_CATS:
        vals = [(name, team_proj[name][cat]) for name in team_proj]
        sorted_vals = sorted(vals, key=lambda x: x[1], reverse=(cat not in _ROTO_LOWER_BETTER))
        for rank_idx, (name, _) in enumerate(sorted_vals, 1):
            team_ranks[name][cat] = rank_idx

    # Total roto points = sum of category ranks
    for name in team_ranks:
        team_ranks[name]["Total Roto Pts"] = sum(team_ranks[name][c] for c in _ROTO_ALL_CATS)

    cat_rows = []
    for name, stats in team_proj.items():
        row = {"Team": name}
        for cat in _ROTO_ALL_CATS:
            row[cat] = stats[cat]
            row[f"#{cat}"] = team_ranks[name][cat]
        row["Total Roto Pts"] = team_ranks[name]["Total Roto Pts"]
        cat_rows.append(row)

    cat_df = pd.DataFrame(cat_rows).sort_values("Total Roto Pts", ascending=False)

    # Colour rank cells: 1st = green, last = red
    def rank_color(val):
        try:
            v = int(val)
        except Exception:
            return ""
        if v == 1:
            return "background-color:rgba(34,197,94,0.25);color:#15803D;font-weight:700"
        if v == 2:
            return "background-color:rgba(34,197,94,0.12);color:#166534"
        if v >= n_teams:
            return "background-color:rgba(239,68,68,0.25);color:#B91C1C;font-weight:700"
        if v >= n_teams - 1:
            return "background-color:rgba(239,68,68,0.12);color:#991B1B"
        return ""

    rank_cols = [f"#{c}" for c in _ROTO_ALL_CATS]
    styled_cat = cat_df.style.applymap(rank_color, subset=rank_cols)

    rank_col_cfg = {f"#{c}": st.column_config.NumberColumn(f"#{c}", format="%d", width="small") for c in _ROTO_ALL_CATS}
    stat_val_col_cfg = {
        "Team":            st.column_config.TextColumn("Team", width="medium"),
        "HR":              num_cfg("HR"),   "R":   num_cfg("R"),
        "RBI":             num_cfg("RBI"),  "SB":  num_cfg("SB"),
        "AVG":             num_cfg("AVG",   "%.3f"),
        "W":               num_cfg("W"),    "SV":  num_cfg("SV"),
        "K":               num_cfg("K"),
        "ERA":             num_cfg("ERA",   "%.2f"),
        "WHIP":            num_cfg("WHIP",  "%.3f"),
        "Total Roto Pts":  num_cfg("Roto Pts", "%.0f"),
    }
    st.dataframe(styled_cat, use_container_width=True, hide_index=True,
                 column_config={**stat_val_col_cfg, **rank_col_cfg})

    # Highlight my team's category position
    my_cats = team_ranks.get(my_team.team_name, {})
    if my_cats:
        strong = [c for c in _ROTO_ALL_CATS if my_cats.get(c, 99) <= 3]
        weak   = [c for c in _ROTO_ALL_CATS if my_cats.get(c, 0)  >= n_teams - 2]
        if strong:
            st.success(f"🏆 **{my_team.team_name}** is winning: {', '.join(strong)}")
        if weak:
            st.warning(f"⚠️ **{my_team.team_name}** needs help in: {', '.join(weak)}")

    # Current matchup from schedule
    st.subheader("Current Matchup")
    try:
        current_week = league.currentMatchupPeriod
        my_match = None
        for match in my_team.schedule:
            if hasattr(match, 'home_team') and match.home_team == my_team:
                my_match = match
                is_home = True
                break
            elif hasattr(match, 'away_team') and match.away_team == my_team:
                my_match = match
                is_home = False
                break

        if my_match:
            if is_home:
                my_score = my_match.home_team_live_score or my_match.home_final_score or 0
                opp_score = my_match.away_team_live_score or my_match.away_final_score or 0
                opp = my_match.away_team
            else:
                my_score = my_match.away_team_live_score or my_match.away_final_score or 0
                opp_score = my_match.home_team_live_score or my_match.home_final_score or 0
                opp = my_match.home_team

            opp_name = opp.team_name if hasattr(opp, 'team_name') else str(opp)
            c1, c2 = st.columns(2)
            c1.metric(my_team.team_name + " (You)", round(my_score, 1))
            c2.metric(opp_name, round(opp_score, 1))
        else:
            st.info("No current matchup found.")
    except Exception:
        st.info("Matchup data not available yet for this week.")

# ─────────────────────────────────────────────────────────────────────────────
# TAB 4: TRADE ANALYZER
# ─────────────────────────────────────────────────────────────────────────────
with tab4:
    st.header("Trade Analyzer")
    st.caption("Compare roto value (sum of category z-scores) for players you give vs. receive, plus a category-by-category breakdown.")

    # Build full rostered player list across all teams (excluding your own for "receive")
    all_rostered = {}
    for t in league.teams:
        for p in t.roster:
            all_rostered[p.name] = p

    my_player_names = [p.name for p in my_team.roster]
    other_player_names = sorted([n for n, p in all_rostered.items() if n not in my_player_names])

    col_give, col_receive = st.columns(2)
    with col_give:
        st.subheader("You Give")
        give_names = st.multiselect("Select players to trade away", my_player_names, key="give")
    with col_receive:
        st.subheader("You Receive")
        receive_names = st.multiselect("Select players to receive", other_player_names, key="receive")

    if give_names or receive_names:
        def player_row(p):
            proj  = fg_roto_value(p)
            pos   = pos_str(p)
            g2025, g_ytd, g_proj = player_grades(p, prev_stats, fg)
            return {"Player": p.name, "Position": pos, "Pro Team": p.proTeam,
                    f"Roto Value ({fg_proj_label})": proj,
                    "Helps": roto_helps_str(p),
                    "WAR": fg_war(p),
                    "G '25": g2025,
                    "G '26 YTD": g_ytd,
                    "G '26 Proj": g_proj,
                    "Key Stats": fg_stat_str(p)}

        give_players    = [p for p in my_team.roster if p.name in give_names]
        receive_players = [all_rostered[n] for n in receive_names if n in all_rostered]

        give_total    = sum(fg_roto_value(p) for p in give_players)
        receive_total = sum(fg_roto_value(p) for p in receive_players)

        trade_proj_col = f"Roto Value ({fg_proj_label})"
        trade_col_cfg = {
            "Player":       st.column_config.TextColumn("Player", width="medium"),
            "Position":     st.column_config.TextColumn("Pos", width="small"),
            "Pro Team":     st.column_config.TextColumn("Team", width="small"),
            trade_proj_col: roto_cfg("Roto Val"),
            "Helps":        st.column_config.TextColumn("Helps", width="small"),
            "WAR":          war_cfg(),
            **GRADE_COL_CFG,
            "Key Stats":    st.column_config.TextColumn("Key Stats", width="large"),
        }
        def _trade_df(players):
            df_t = pd.DataFrame([player_row(p) for p in players])
            return apply_grade_colors(df_t.style)

        c1, c2 = st.columns(2)
        with c1:
            if give_players:
                st.dataframe(_trade_df(give_players),
                             use_container_width=True, hide_index=True,
                             column_config=trade_col_cfg)
                st.metric("Roto Value Given", round(give_total, 2))
        with c2:
            if receive_players:
                st.dataframe(_trade_df(receive_players),
                             use_container_width=True, hide_index=True,
                             column_config=trade_col_cfg)
                st.metric("Roto Value Received", round(receive_total, 2))

        if give_names and receive_names:
            diff = receive_total - give_total
            st.divider()

            # ── Category-by-category impact ─────────────────────────────────
            st.subheader("📊 Category Impact")
            st.caption("How each roto category changes if you make this trade (FanGraphs projections).")

            all_cats = ["HR", "R", "RBI", "SB", "AVG", "W", "SV", "K", "ERA", "WHIP"]
            inv_cats = {"ERA", "WHIP"}

            def sum_cat(players, cat):
                total = 0.0
                count = 0
                for p in players:
                    entry = fg.get(p.name, {})
                    v = entry.get(cat)
                    if v is not None:
                        total += float(v)
                        count += 1
                if cat == "AVG" and count:
                    return round(total / count, 3)
                return round(total, 1 if cat not in ("AVG", "ERA", "WHIP") else 3)

            cat_impact_rows = []
            for cat in all_cats:
                give_val    = sum_cat(give_players, cat)
                receive_val = sum_cat(receive_players, cat)
                delta = receive_val - give_val
                better = (delta > 0) if cat not in inv_cats else (delta < 0)
                cat_impact_rows.append({
                    "Category": cat,
                    "You Give Up": give_val,
                    "You Receive": receive_val,
                    "Δ": round(delta, 3 if cat in ("AVG", "ERA", "WHIP") else 1),
                    "Better?": "✅ Yes" if better else ("➖ Even" if abs(delta) < 0.001 else "❌ No"),
                })
            st.dataframe(pd.DataFrame(cat_impact_rows), use_container_width=True,
                         hide_index=True, column_config={
                             "Category":    st.column_config.TextColumn("Category", width="small"),
                             "You Give Up": num_cfg("Give Up"),
                             "You Receive": num_cfg("Receive"),
                             "Δ":           num_cfg("Change"),
                             "Better?":     st.column_config.TextColumn("Better?", width="small"),
                         })

            cats_won  = [r["Category"] for r in cat_impact_rows if r["Better?"] == "✅ Yes"]
            cats_lost = [r["Category"] for r in cat_impact_rows if r["Better?"] == "❌ No"]
            st.divider()
            if diff > 0.5:
                st.success(f"✅ Overall roto value gain: **+{round(diff, 2)}** — you improve in {len(cats_won)} categor{'y' if len(cats_won)==1 else 'ies'}: {', '.join(cats_won) or '—'}")
            elif diff < -0.5:
                st.error(f"❌ Overall roto value loss: **{round(diff, 2)}** — you hurt yourself in: {', '.join(cats_lost) or '—'}")
            else:
                st.info(f"🤝 Roughly even trade (Δ roto val = {round(diff, 2)}). Check which categories matter most for your standings.")

    # ── Smart Trade Suggestions ───────────────────────────────────────────────
    st.divider()
    st.subheader("🤖 Smart Trade Suggestions")
    st.caption(
        "Finds mutually beneficial trades: players that upgrade YOUR weak spots, "
        "offered in exchange for YOUR surplus that upgrades THEIR weak spots."
    )

    STARTER_SLOTS = ["C", "1B", "2B", "3B", "SS", "OF", "SP", "RP", "DH", "P"]

    def best_at_slot(roster, slot):
        """Return the highest FG-projected player on a roster eligible for a given slot."""
        candidates = [
            p for p in roster
            if slot in (p.eligibleSlots or [p.position])
            and getattr(p, "injuryStatus", "ACTIVE") not in ("INJURY_RESERVE", "OUT")
        ]
        if not candidates:
            return None, 0.0
        best = max(candidates, key=fg_pts)
        return best, fg_pts(best)

    def second_best_at_slot(roster, slot):
        """Return the second-best player at a slot (measures surplus depth)."""
        candidates = sorted(
            [p for p in roster if slot in (p.eligibleSlots or [p.position])],
            key=fg_pts, reverse=True
        )
        if len(candidates) >= 2:
            return candidates[1], fg_pts(candidates[1])
        return None, 0.0

    # League-wide average best value per slot (for weakness detection)
    slot_league_avgs = {}
    for slot in STARTER_SLOTS:
        vals = [best_at_slot(t.roster, slot)[1] for t in league.teams]
        vals = [v for v in vals if v > 0]
        slot_league_avgs[slot] = sum(vals) / len(vals) if vals else 0

    # My weaknesses: slots where my best is below league avg
    my_weak_slots = {}
    for slot in STARTER_SLOTS:
        p, val = best_at_slot(my_team.roster, slot)
        avg = slot_league_avgs.get(slot, 0)
        if avg > 0 and val < avg * 0.9:
            my_weak_slots[slot] = {"player": p, "value": val, "avg": avg, "gap": avg - val}

    # My surplus: slots where I have strong depth (second-best is still above avg)
    my_surplus_slots = {}
    for slot in STARTER_SLOTS:
        p2, val2 = second_best_at_slot(my_team.roster, slot)
        avg = slot_league_avgs.get(slot, 0)
        if p2 and val2 > avg * 0.95:
            p1, val1 = best_at_slot(my_team.roster, slot)
            my_surplus_slots[slot] = {"player": p2, "value": val2, "best": p1, "best_val": val1}

    if not my_weak_slots:
        st.success("Your team has no glaring weaknesses compared to the league average. Well built!")
    elif not my_surplus_slots:
        st.warning("You have weak spots but no surplus depth to offer. Focus on waiver wire pickups instead.")
    else:
        suggestions = []

        for their_team in league.teams:
            if their_team.team_id == my_team.team_id:
                continue

            # Their weaknesses
            their_weak_slots = {}
            for slot in STARTER_SLOTS:
                p, val = best_at_slot(their_team.roster, slot)
                avg = slot_league_avgs.get(slot, 0)
                if avg > 0 and val < avg * 0.9:
                    their_weak_slots[slot] = {"player": p, "value": val, "avg": avg}

            # Can I give them something for their weak slot that they'd want?
            for give_slot, my_surplus in my_surplus_slots.items():
                if give_slot not in their_weak_slots:
                    continue
                give_player = my_surplus["player"]
                give_val = my_surplus["value"]
                their_gap = their_weak_slots[give_slot]["avg"] - their_weak_slots[give_slot]["value"]

                # Can they give me something for my weak slot?
                for receive_slot, my_weakness in my_weak_slots.items():
                    recv_p, recv_val = best_at_slot(their_team.roster, receive_slot)
                    if recv_p is None or recv_val <= my_weakness["value"]:
                        continue
                    if recv_p.name == give_player.name:
                        continue

                    # How much do I gain? How much do they gain?
                    my_gain = recv_val - my_weakness["value"]
                    their_gain = give_val - their_weak_slots[give_slot]["value"]
                    combined_benefit = my_gain + their_gain
                    fairness = abs(give_val - recv_val)

                    suggestions.append({
                        "Trade With": their_team.team_name,
                        "You Give": give_player.name,
                        "Give Pos": give_slot,
                        "Give Proj": round(give_val, 1),
                        "You Receive": recv_p.name,
                        "Receive Pos": receive_slot,
                        "Receive Proj": round(recv_val, 1),
                        "Your Upgrade": round(my_gain, 1),
                        "Their Upgrade": round(their_gain, 1),
                        "Combined Benefit": round(combined_benefit, 1),
                        "Value Diff": round(recv_val - give_val, 1),
                        "_fairness": fairness,
                    })

        if not suggestions:
            st.info("No mutually beneficial trades found right now. Check back as rosters change.")
        else:
            sug_df = (
                pd.DataFrame(suggestions)
                .sort_values(["Combined Benefit", "_fairness"], ascending=[False, True])
                .drop(columns=["_fairness"])
                .head(10)
                .reset_index(drop=True)
            )

            # Color the Value Diff column
            def diff_color(val):
                if val > 3:
                    return "color: #00cc66; font-weight: bold"
                if val < -3:
                    return "color: #ff6666"
                return "color: #ffffff"

            styled_sug = sug_df.style.applymap(diff_color, subset=["Value Diff"])
            st.dataframe(
                styled_sug, use_container_width=True, hide_index=True,
                column_config={
                    "Trade With":       st.column_config.TextColumn("Trade With", width="medium"),
                    "You Give":         st.column_config.TextColumn("You Give", width="medium"),
                    "Give Pos":         st.column_config.TextColumn("Give Pos", width="small"),
                    "Give Proj":        roto_cfg("Give Val"),
                    "You Receive":      st.column_config.TextColumn("You Receive", width="medium"),
                    "Receive Pos":      st.column_config.TextColumn("Rcv Pos", width="small"),
                    "Receive Proj":     roto_cfg("Rcv Val"),
                    "Your Upgrade":     roto_cfg("Your ↑"),
                    "Their Upgrade":    roto_cfg("Their ↑"),
                    "Combined Benefit": roto_cfg("Combined"),
                    "Value Diff":       roto_cfg("Val Diff"),
                }
            )

            st.caption(
                "**Your Upgrade** = roto value gained at your weak position. "
                "**Their Upgrade** = roto value they gain. "
                "**Value Diff** = positive means you win on overall roto value."
            )

            # Highlight the single best suggestion
            best = sug_df.iloc[0]
            st.success(
                f"🏆 Best suggestion: Trade **{best['You Give']}** to **{best['Trade With']}** "
                f"for **{best['You Receive']}**. "
                f"You gain +{best['Your Upgrade']} roto val at {best['Receive Pos']}, "
                f"they gain +{best['Their Upgrade']} at {best['Give Pos']}."
            )

# ─────────────────────────────────────────────────────────────────────────────
# TAB 5: START / SIT
# ─────────────────────────────────────────────────────────────────────────────
with tab5:
    st.header("Start / Sit")
    st.caption("Surfaces hot/cold players based on recent ESPN scoring trends. In a roto league, prioritise starting players trending upward in your weak categories.")

    if prev_stats and prior_weight > 0:
        PREV_SEASON_WEEKS = 26  # approx half-season weeks for per-week normalization
        st.info(f"📅 Season is young — blending {prev_year} per-week avg ({round(prior_weight*100)}%) with {cfg.get('year',2026)} recent form ({round(cur_weight*100)}%) for the Blended Score.")

    sit_rows = []
    for p in my_team.roster:
        season_pts = p.stats.get(0, {}).get("points", 0)
        proj_pts = fg_roto_value(p)

        # Sum actual points from the last 3 scoring periods
        recent_periods = [k for k in p.stats if isinstance(k, int) and k > 0 and k < current_period]
        recent_periods_sorted = sorted(recent_periods, reverse=True)[:3]
        recent_pts = sum(p.stats[k].get("points", 0) for k in recent_periods_sorted)
        weeks_counted = len(recent_periods_sorted)

        # Avg per week season vs recent
        total_weeks = max(current_period - 1, 1)
        season_avg = round(season_pts / total_weeks, 1) if total_weeks else 0
        recent_avg = round(recent_pts / weeks_counted, 1) if weeks_counted else 0
        trend = recent_avg - season_avg

        # Prior-year per-week avg
        prev_pts_total = prev_stats.get(p.name, {}).get("prev_pts", 0) or 0
        prev_per_wk = round(prev_pts_total / PREV_SEASON_WEEKS, 1) if prev_stats else 0

        # Blended score: mix prior-year avg and current recent avg
        if prev_stats and prior_weight > 0 and weeks_counted > 0:
            blended = round(prior_weight * prev_per_wk + cur_weight * recent_avg, 1)
        elif prev_stats and prior_weight > 0:
            blended = prev_per_wk
        else:
            blended = recent_avg

        pos = pos_str(p)
        status = getattr(p, "injuryStatus", "ACTIVE")

        g2025, g_ytd, g_proj = player_grades(p, prev_stats, fg)
        row = {
            "Player": p.name,
            "Position": pos,
            "Pro Team": p.proTeam,
            "WAR": fg_war(p),
            "G '25": g2025,
            "G '26 YTD": g_ytd,
            "G '26 Proj": g_proj,
            "🌡️ Heat": heat_label(heat_score(p, current_period)),
            "Blended Score": blended,
            "Recent Avg/Wk": recent_avg,
            "Season Avg/Wk": season_avg,
            "Trend": round(trend, 1),
            "Proj. Total": round(proj_pts, 1),
            "Status": status,
        }
        if prev_stats:
            row[f"{prev_year} /Wk"] = prev_per_wk
        sit_rows.append(row)

    sit_df = pd.DataFrame(sit_rows).sort_values("Blended Score", ascending=False)

    def trend_color(val):
        if val > 2:
            return "color: #00cc66; font-weight: bold"
        if val < -2:
            return "color: #ff4444; font-weight: bold"
        return "color: #aaaaaa"

    def status_bg(val):
        if val in ("INJURY_RESERVE", "OUT"):
            return "background-color: rgba(255,0,0,0.3)"
        if val in ("QUESTIONABLE", "DOUBTFUL"):
            return "background-color: rgba(255,200,0,0.3)"
        return ""

    sit_col_cfg = {
        "Player":         st.column_config.TextColumn("Player", width="medium"),
        "Position":       st.column_config.TextColumn("Pos", width="small"),
        "Pro Team":       st.column_config.TextColumn("Team", width="small"),
        "WAR":            war_cfg(),
        **GRADE_COL_CFG,
        "🌡️ Heat":        HEAT_CFG,
        "Blended Score":  pts_cfg("Blended Score ⭐"),
        "Recent Avg/Wk":  pts_cfg("Recent /Wk"),
        "Season Avg/Wk":  pts_cfg("Season /Wk"),
        f"{prev_year} /Wk": pts_cfg(f"{prev_year} /Wk"),
        "Trend":          pts_cfg("Trend"),
        "Proj. Total":    roto_cfg("Roto Val"),
        "Status":         st.column_config.TextColumn("Health", width="small"),
    }

    styled_sit = apply_grade_colors(
        apply_badges(sit_df).style
        .applymap(trend_color, subset=["Trend"])
    )
    st.dataframe(styled_sit, use_container_width=True, hide_index=True,
                 column_config=sit_col_cfg)

    hot  = sit_df[(sit_df["Trend"] > 2)  & (~sit_df["Status"].isin(["INJURY_RESERVE", "OUT"]))]
    cold = sit_df[sit_df["Trend"] < -2]

    hc1, hc2 = st.columns(2)
    with hc1:
        st.subheader("🔥 Hot — Start These")
        if not hot.empty:
            st.dataframe(
                apply_badges(hot[["Player", "Position", "Pro Team",
                                  "Season Avg/Wk", "Recent Avg/Wk", "Trend", "Status"]]),
                use_container_width=True, hide_index=True, column_config=sit_col_cfg
            )
        else:
            st.info("No standout hot players this week.")

    with hc2:
        st.subheader("🧊 Cold — Consider Sitting")
        if not cold.empty:
            st.dataframe(
                apply_badges(cold[["Player", "Position", "Pro Team",
                                   "Season Avg/Wk", "Recent Avg/Wk", "Trend", "Status"]]),
                use_container_width=True, hide_index=True, column_config=sit_col_cfg
            )
        else:
            st.info("No players are significantly underperforming their season average.")

# ─────────────────────────────────────────────────────────────────────────────
# TAB 6: STREAMING PITCHERS
# ─────────────────────────────────────────────────────────────────────────────
with tab6:
    st.header("Streaming Pitchers")
    st.caption("Top available SP and RP free agents ranked by **roto value** — ideal for week-to-week streaming. "
               "⚠️ In roto, a bad start can crater your ERA/WHIP for weeks — check the ERA/WHIP columns before adding.")

    stream_n = st.slider("Number of pitchers to show", 10, 60, 25, key="stream_n")

    with st.spinner("Loading available pitchers…"):
        try:
            sp_fa = league.free_agents(size=stream_n * 2, position="SP")
            rp_fa = league.free_agents(size=stream_n, position="RP")
            pitcher_fa = {p.name: p for p in sp_fa + rp_fa}.values()  # dedupe

            current_period = getattr(league, "currentMatchupPeriod", None) or 1

            stream_proj_col = f"Roto Value ({fg_proj_label})"
            p_rows = []
            for p in pitcher_fa:
                proj      = fg_roto_value(p)
                pct_owned = getattr(p, "percent_owned", 0)

                recent_periods = [k for k in p.stats if isinstance(k, int) and k > 0 and k < current_period]
                recent_sorted  = sorted(recent_periods, reverse=True)[:3]
                recent_pts     = sum(p.stats[k].get("points", 0) for k in recent_sorted)
                recent_avg     = round(recent_pts / len(recent_sorted), 1) if recent_sorted else 0

                fg_entry = fg.get(p.name, {})
                pos    = pos_str(p)
                status = getattr(p, "injuryStatus", "ACTIVE")

                g2025, g_ytd, g_proj = player_grades(p, prev_stats, fg)
                hurts = roto_hurts_str(p)
                p_rows.append({
                    "Player": p.name,
                    "Type": "SP" if "SP" in pos else "RP",
                    "Pro Team": p.proTeam,
                    "% Owned": round(pct_owned, 1),
                    stream_proj_col: proj,
                    "ERA/WHIP Risk": hurts if hurts else "✅ Safe",
                    "WAR": fg_war(p),
                    "G '25": g2025,
                    "G '26 YTD": g_ytd,
                    "G '26 Proj": g_proj,
                    "Recent Avg/Wk": recent_avg,
                    "🌡️ Heat": heat_label(heat_score(p, current_period)),
                    f"FG ERA": fg_entry.get("ERA", "—"),
                    f"FG WHIP": fg_entry.get("WHIP", "—"),
                    f"FG K": fg_entry.get("K", "—"),
                    f"FG W": fg_entry.get("W", "—"),
                    f"FG SV": fg_entry.get("SV", "—"),
                    f"FG IP": fg_entry.get("IP", "—"),
                    "Status": status,
                })

            p_df = (
                pd.DataFrame(p_rows)
                .sort_values([stream_proj_col, "Recent Avg/Wk"], ascending=False)
                .head(stream_n)
            )

            col_f1, col_f2 = st.columns(2)
            with col_f1:
                type_filter = st.radio("Pitcher type", ["All", "SP only", "RP only"], horizontal=True)
            with col_f2:
                hide_injured = st.checkbox("Hide injured/out", value=True)

            if type_filter == "SP only":
                p_df = p_df[p_df["Type"] == "SP"]
            elif type_filter == "RP only":
                p_df = p_df[p_df["Type"] == "RP"]
            if hide_injured:
                p_df = p_df[~p_df["Status"].isin(["INJURY_RESERVE", "OUT"])]

            stream_col_cfg = {
                "Player":            st.column_config.TextColumn("Player", width="medium"),
                "Type":              st.column_config.TextColumn("Type", width="small"),
                "Pro Team":          st.column_config.TextColumn("Team", width="small"),
                "% Owned":           pct_cfg("% Own"),
                stream_proj_col:     roto_cfg("Roto Val"),
                "ERA/WHIP Risk":     st.column_config.TextColumn("ERA/WHIP Risk", width="small",
                                         help="⚠️ = pitcher projects to hurt your ERA/WHIP in roto"),
                "WAR":               war_cfg(),
                **GRADE_COL_CFG,
                "Recent Avg/Wk":     pts_cfg("Recent /Wk"),
                "🌡️ Heat":           HEAT_CFG,
                "FG ERA":            num_cfg("ERA", "%.2f"),
                "FG WHIP":           num_cfg("WHIP", "%.2f"),
                "FG K":              num_cfg("K", "%.0f"),
                "FG W":              num_cfg("W", "%.0f"),
                "FG SV":             num_cfg("SV", "%.0f"),
                "FG IP":             num_cfg("IP", "%.0f"),
                "Status":            st.column_config.TextColumn("Health", width="small"),
            }
            st.dataframe(
                apply_grade_colors(apply_badges(p_df).style),
                use_container_width=True, hide_index=True,
                column_config=stream_col_cfg
            )

            # Top streaming pick
            top_streamers = p_df[p_df["% Owned"] < 50].head(3)
            if not top_streamers.empty:
                st.subheader("💡 Top Streaming Picks (< 50% owned)")
                st.dataframe(
                    apply_grade_colors(apply_badges(top_streamers).style),
                    use_container_width=True, hide_index=True,
                    column_config=stream_col_cfg
                )

        except Exception as e:
            st.error(f"Could not load pitchers: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# TAB 7: PLAYER NEWS
# ─────────────────────────────────────────────────────────────────────────────
with tab7:
    st.header("📰 Player News")
    st.caption("Latest MLB news from the last 24 hours · Sourced from ESPN · Auto-refreshes every 5 min")

    # ── Refresh controls ──────────────────────────────────────────────────────
    rcol, tcol = st.columns([1, 5])
    with rcol:
        if st.button("🔄 Refresh Now", key="news_refresh"):
            st.cache_data.clear()
            st.rerun()
    with tcol:
        st.caption(f"Page loaded at **{datetime.now().strftime('%I:%M %p')}**")

    # ── Build ESPN player-id lookup from roster (for photo fallback) ──────────
    pid_lookup: dict = {}   # {player_name: espn_athlete_id}
    for p in my_team.roster:
        pid = getattr(p, "playerId", None)
        if pid:
            pid_lookup[p.name] = pid

    # ── Fetch news feed (cached 5 min) ────────────────────────────────────────
    with st.spinner("Fetching latest news…"):
        all_news = fetch_news_feed()

    def _photo(item: dict) -> str:
        """Return ESPN headshot URL using athlete ID from the news item or pid_lookup."""
        aid = item.get("matched_id") or pid_lookup.get(item.get("matched_player", ""))
        return (f"https://a.espncdn.com/i/headshots/mlb/players/full/{aid}.png"
                if aid else "")

    # ── Section 1: My Roster ──────────────────────────────────────────────────
    roster_names = [p.name for p in my_team.roster]
    roster_news  = filter_news_for_players(all_news, roster_names)

    st.subheader(f"📋 My Roster  ·  {len(roster_news)} item{'s' if len(roster_news) != 1 else ''} in the last 24 h")
    if not roster_news:
        st.info("No news in the last 24 hours for your rostered players.")
    else:
        for item in roster_news:
            st.markdown(news_card_html(item, _photo(item)), unsafe_allow_html=True)

    st.markdown("<hr style='border-color:rgba(100,160,255,0.2);margin:24px 0'>",
                unsafe_allow_html=True)

    # ── Section 2: Free Agents ────────────────────────────────────────────────
    st.subheader("🔍 Free Agent News")
    with st.spinner("Loading free agents…"):
        try:
            news_fa_list = league.free_agents(size=150)
            fa_names = [p.name for p in news_fa_list]
            for p in news_fa_list:
                pid = getattr(p, "playerId", None)
                if pid:
                    pid_lookup[p.name] = pid
        except Exception as e:
            st.error(f"Could not load free agents: {e}")
            fa_names = []

    fa_news = filter_news_for_players(all_news, fa_names)
    st.caption(f"{len(fa_news)} item{'s' if len(fa_news) != 1 else ''} in the last 24 h")

    if not fa_news:
        st.info("No news in the last 24 hours for available free agents.")
    else:
        for item in fa_news:
            st.markdown(news_card_html(item, _photo(item)), unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# TAB 8: GAMES
# ─────────────────────────────────────────────────────────────────────────────
with tab8:
    st.header("MLB Scores & Schedules")

    today = datetime.now().date()

    # Build day labels and offsets
    day_offsets = [-2, -1, 0, 1, 2, 3]

    def day_label(offset: int) -> str:
        d = today + timedelta(days=offset)
        if offset == -2:
            return d.strftime("%-m/%-d")
        elif offset == -1:
            return "Yesterday"
        elif offset == 0:
            return "Today"
        elif offset == 1:
            return "Tomorrow"
        else:
            return d.strftime("%a %-m/%-d")

    game_tabs = st.tabs([day_label(o) for o in day_offsets])

    for tab_idx, day_offset in enumerate(day_offsets):
        with game_tabs[tab_idx]:
            game_date = today + timedelta(days=day_offset)
            date_str = game_date.strftime("%Y%m%d")
            is_today = (day_offset == 0)

            with st.spinner(f"Loading games for {game_date.strftime('%B %-d, %Y')}…"):
                events = fetch_mlb_scoreboard_live(date_str) if is_today else fetch_mlb_scoreboard(date_str)

            if is_today:
                st.caption(f"📅 {game_date.strftime('%A, %B %-d, %Y')} · Live scores refresh every 60 seconds")
            else:
                st.caption(f"📅 {game_date.strftime('%A, %B %-d, %Y')}")

            if not events:
                st.info(f"No games scheduled for {game_date.strftime('%B %-d, %Y')}.")
            else:
                # 2-column grid
                cols = st.columns(2, gap="medium")
                for i, event in enumerate(events):
                    with cols[i % 2]:
                        st.markdown(render_game_card(event), unsafe_allow_html=True)

            # Auto-refresh button for today
            if is_today and events:
                if st.button("🔄 Refresh Live Scores", key="refresh_games_today"):
                    fetch_mlb_scoreboard_live.clear()
                    st.rerun()

# ─────────────────────────────────────────────────────────────────────────────
# TAB 9: ROTO TOOLS
# ─────────────────────────────────────────────────────────────────────────────
with tab9:
    st.header("🎯 Roto Tools")
    st.caption("High-leverage roto-specific analysis — eleven tools in one tab.")

    roto_tool = st.selectbox(
        "Select tool",
        [
            "📅 Two-Start Pitchers",
            "📊 Category Gap Tracker",
            "🧮 ERA/WHIP Runway",
            "📈 Pace Tracker",
            "🔒 Closer Monitor",
            "⚡ Starts Maximizer",
            "🎯 Punt Advisor",
            "📉 Buy Low / Sell High",
            "🚨 Emergency Replacements",
            "⚔️ Matchup Breakdown",
            "📊 Standings Trend",
        ],
        label_visibility="collapsed",
    )

    st.divider()

    # ── Helper: build team projected stats (delegates to module-level helper) ──
    def _build_team_proj():
        return _build_team_proj_shared()

    # ════════════════════════════════════════════════════════════════════════════
    if roto_tool == "📅 Two-Start Pitchers":
    # ════════════════════════════════════════════════════════════════════════════
        st.subheader("📅 Two-Start Pitchers This Week")
        st.caption("SPs with 2 scheduled starts in the current Mon–Sun window. "
                   "Note: probable starters are only confirmed by ESPN a few days out — "
                   "games later in the week may show TBD.")

        today_d = datetime.now().date()
        monday  = today_d - timedelta(days=today_d.weekday())
        week_str = monday.strftime("%Y%m%d")
        week_end = (monday + timedelta(days=6)).strftime("%b %-d")
        st.caption(f"Week: **{monday.strftime('%b %-d')} – {week_end}**")

        with st.spinner("Scanning ESPN schedule for two-start pitchers…"):
            two_starters = fetch_weekly_starts(week_str)

        if st.button("🔄 Refresh Schedule", key="refresh_two_start"):
            fetch_weekly_starts.clear()
            st.rerun()

        if not two_starters:
            st.info("No two-start pitchers found yet — ESPN may not have posted probable starters for this week. Check back Monday.")
        else:
            # Split: my roster vs free agents
            my_pitcher_names = {p.name for p in my_team.roster if is_pitcher(p)}

            ts_rows = []
            for name, info in sorted(two_starters.items(),
                                     key=lambda x: fg_roto_value_by_name(x[0]), reverse=True):
                entry = fg.get(name, {})
                ts_rows.append({
                    "Player":    name,
                    "Team":      info["team"],
                    "Starts":    info["starts"],
                    "Start Dates": "  ·  ".join(
                        f"{d} {o}" for d, o in zip(info["dates"], info.get("opp", []))
                    ),
                    "Roto Val":  round(fg.get(name, {}).get("WAR") and fg_roto_value_by_name(name) or 0, 2),
                    "Proj ERA":  entry.get("ERA", "—"),
                    "Proj WHIP": entry.get("WHIP", "—"),
                    "Proj K":    entry.get("K", "—"),
                    "Proj W":    entry.get("W", "—"),
                    "On Roster": "✅ Yours" if name in my_pitcher_names else "🆓 FA",
                })

            ts_df = pd.DataFrame(ts_rows)
            mine_df = ts_df[ts_df["On Roster"] == "✅ Yours"]
            fa_df_ts = ts_df[ts_df["On Roster"] == "🆓 FA"]

            if not mine_df.empty:
                st.subheader("✅ Your Two-Start Pitchers — Start Them!")
                st.dataframe(mine_df.drop(columns=["On Roster"]),
                             use_container_width=True, hide_index=True,
                             column_config={
                                 "Player":      st.column_config.TextColumn("Player", width="medium"),
                                 "Team":        st.column_config.TextColumn("Team", width="small"),
                                 "Starts":      num_cfg("Starts"),
                                 "Start Dates": st.column_config.TextColumn("Schedule", width="large"),
                                 "Roto Val":    roto_cfg("Roto Val"),
                                 "Proj ERA":    num_cfg("ERA", "%.2f"),
                                 "Proj WHIP":   num_cfg("WHIP", "%.2f"),
                                 "Proj K":      num_cfg("K", "%.0f"),
                                 "Proj W":      num_cfg("W", "%.0f"),
                             })
            else:
                st.warning("None of your pitchers have two starts this week — consider streaming one.")

            if not fa_df_ts.empty:
                st.subheader("🆓 Available Two-Start Free Agents")
                st.caption("Ranked by projected roto value. Add the best available before your opponent does.")
                st.dataframe(fa_df_ts.drop(columns=["On Roster"]).sort_values("Roto Val", ascending=False),
                             use_container_width=True, hide_index=True,
                             column_config={
                                 "Player":      st.column_config.TextColumn("Player", width="medium"),
                                 "Team":        st.column_config.TextColumn("Team", width="small"),
                                 "Starts":      num_cfg("Starts"),
                                 "Start Dates": st.column_config.TextColumn("Schedule", width="large"),
                                 "Roto Val":    roto_cfg("Roto Val"),
                                 "Proj ERA":    num_cfg("ERA", "%.2f"),
                                 "Proj WHIP":   num_cfg("WHIP", "%.2f"),
                                 "Proj K":      num_cfg("K", "%.0f"),
                                 "Proj W":      num_cfg("W", "%.0f"),
                             })

    # ════════════════════════════════════════════════════════════════════════════
    elif roto_tool == "📊 Category Gap Tracker":
    # ════════════════════════════════════════════════════════════════════════════
        st.subheader("📊 Category Gap Tracker")
        st.caption("How far are you from moving up — or being caught — in each roto category?")

        team_proj, team_ranks, _all_cats, _lower_better, n_teams = _build_team_proj()
        my_name = my_team.team_name

        if my_name not in team_proj:
            st.warning("Could not find your team in the projected standings.")
        else:
            gap_rows = []
            for cat in _all_cats:
                my_val  = team_proj[my_name][cat]
                my_rank = team_ranks[my_name][cat]

                # Sort all teams by this cat to find neighbors
                inv = cat in _lower_better
                sorted_teams = sorted(team_proj.items(), key=lambda x: x[1][cat], reverse=not inv)
                rank_vals = [v[cat] for _, v in sorted_teams]

                # Gap to rank above (move up)
                if my_rank > 1:
                    val_above = rank_vals[my_rank - 2]   # rank_vals is 0-indexed; rank above = my_rank-2
                    gap_up = abs(val_above - my_val)
                    if cat in ("AVG", "ERA", "WHIP"):
                        gap_up_str = f"{'+' if not inv else '-'}{gap_up:.3f}"
                    else:
                        gap_up_str = f"{'+' if not inv else '-'}{gap_up:.0f}"
                else:
                    gap_up_str = "—  (1st place)"

                # Gap to rank below (being caught)
                if my_rank < n_teams:
                    val_below = rank_vals[my_rank]       # rank below = my_rank (0-indexed)
                    gap_dn = abs(my_val - val_below)
                    if cat in ("AVG", "ERA", "WHIP"):
                        gap_dn_str = f"{gap_dn:.3f}"
                    else:
                        gap_dn_str = f"{gap_dn:.0f}"
                else:
                    gap_dn_str = "—  (last place)"

                # Urgency: how close is the rank above?
                close_to_up = (my_rank > 1) and (
                    (gap_up := abs(rank_vals[my_rank - 2] - my_val)) /
                    max(abs(my_val), 0.001) < 0.08
                )

                gap_rows.append({
                    "Category": cat,
                    "Your Proj": (f"{my_val:.3f}" if cat in ("AVG","ERA","WHIP") else f"{my_val:.0f}"),
                    "Rank": f"#{my_rank} of {n_teams}",
                    "Need to Move Up": gap_up_str,
                    "Lead Over #Below": gap_dn_str,
                    "Priority": "🔥 Close!" if close_to_up else ("🟢 Winning" if my_rank <= 3 else ("🔴 Danger" if my_rank >= n_teams - 1 else "")),
                })

            gap_df = pd.DataFrame(gap_rows)
            st.dataframe(gap_df, use_container_width=True, hide_index=True,
                         column_config={
                             "Category":        st.column_config.TextColumn("Category", width="small"),
                             "Your Proj":       st.column_config.TextColumn("Your Proj", width="small"),
                             "Rank":            st.column_config.TextColumn("Rank", width="small"),
                             "Need to Move Up": st.column_config.TextColumn("Need to Move Up ↑", width="medium",
                                                    help="How much you need to add to pass the team ranked above you"),
                             "Lead Over #Below":st.column_config.TextColumn("Lead Over Next ↓", width="medium",
                                                    help="How much cushion you have before being passed by the team below"),
                             "Priority":        st.column_config.TextColumn("", width="small"),
                         })

            # Actionable summary
            close_cats  = [r["Category"] for r in gap_rows if "Close" in r["Priority"]]
            danger_cats = [r["Category"] for r in gap_rows if "Danger" in r["Priority"]]
            winning_cats= [r["Category"] for r in gap_rows if "Winning" in r["Priority"]]
            if close_cats:
                st.success(f"🔥 You're close to moving up in: **{', '.join(close_cats)}** — target these in your next waiver/trade move.")
            if danger_cats:
                st.error(f"🔴 You're at risk of losing ground in: **{', '.join(danger_cats)}** — protect these categories.")
            if winning_cats:
                st.info(f"🟢 Comfortably winning: **{', '.join(winning_cats)}**")

    # ════════════════════════════════════════════════════════════════════════════
    elif roto_tool == "🧮 ERA/WHIP Runway":
    # ════════════════════════════════════════════════════════════════════════════
        st.subheader("🧮 ERA/WHIP Runway Calculator")
        st.caption("How many bad innings can you absorb before your ERA or WHIP drops a rank? "
                   "Based on FanGraphs projected staff totals.")

        # Build my staff projected totals
        my_ip = 0.0;  my_era_runs = 0.0;  my_whip_base = 0.0
        staff_rows = []
        for p in my_team.roster:
            if not is_pitcher(p):
                continue
            entry = fg.get(p.name, {})
            ip    = float(entry.get("IP")   or 0)
            era   = float(entry.get("ERA")  or 0)
            whip  = float(entry.get("WHIP") or 0)
            my_ip        += ip
            my_era_runs  += era * ip / 9.0
            my_whip_base += whip * ip
            staff_rows.append({"Pitcher": p.name, "IP": ip, "ERA": era, "WHIP": whip})

        if my_ip == 0:
            st.warning("No pitching projections found for your staff.")
        else:
            my_era  = round(my_era_runs * 9.0 / my_ip, 2)
            my_whip = round(my_whip_base / my_ip, 3)

            c1, c2, c3 = st.columns(3)
            c1.metric("Staff Proj ERA",  f"{my_era:.2f}")
            c2.metric("Staff Proj WHIP", f"{my_whip:.3f}")
            c3.metric("Proj IP (full season)", f"{my_ip:.0f}")

            st.dataframe(pd.DataFrame(staff_rows).sort_values("IP", ascending=False),
                         use_container_width=True, hide_index=True,
                         column_config={
                             "Pitcher": st.column_config.TextColumn("Pitcher", width="medium"),
                             "IP":   num_cfg("Proj IP", "%.0f"),
                             "ERA":  num_cfg("Proj ERA",  "%.2f"),
                             "WHIP": num_cfg("Proj WHIP", "%.2f"),
                         })

            st.divider()
            st.subheader("🎚️ Streaming Impact Simulator")
            st.caption("Every available FA starter, ranked by ERA/WHIP impact on your team. "
                       "Green = safe to add, red = will hurt your ratios.")

            # Get rank context once
            team_proj2, team_ranks2, _, _, n2 = _build_team_proj()
            current_era_rank  = team_ranks2.get(my_team.team_name, {}).get("ERA",  n2)
            current_whip_rank = team_ranks2.get(my_team.team_name, {}).get("WHIP", n2)
            all_era_vals  = sorted([(t, v["ERA"])  for t, v in team_proj2.items()], key=lambda x: x[1])
            all_whip_vals = sorted([(t, v["WHIP"]) for t, v in team_proj2.items()], key=lambda x: x[1])

            with st.spinner("Loading available starters…"):
                try:
                    stream_fa = league.free_agents(size=60, position="SP")
                except Exception:
                    stream_fa = []

            if not stream_fa:
                st.info("No free agent starters found.")
            else:
                sim_rows = []
                for p in stream_fa:
                    entry = fg.get(p.name, {})
                    if not entry:
                        continue
                    p_era  = float(entry.get("ERA")  or 0)
                    p_whip = float(entry.get("WHIP") or 0)
                    p_ip   = float(entry.get("IP")   or 0)
                    if p_era == 0 or p_ip == 0:
                        continue

                    # Full-season projected impact
                    new_era_r = my_era_runs  + p_era  * p_ip / 9.0
                    new_whip_b= my_whip_base + p_whip * p_ip
                    new_tot_ip= my_ip + p_ip
                    new_era   = round(new_era_r  * 9.0 / new_tot_ip, 2)
                    new_whip  = round(new_whip_b / new_tot_ip, 3)
                    d_era     = round(new_era  - my_era,  2)
                    d_whip    = round(new_whip - my_whip, 3)

                    new_era_rank  = sum(1 for _, v in all_era_vals  if v <= new_era)  + 1
                    new_whip_rank = sum(1 for _, v in all_whip_vals if v <= new_whip) + 1
                    era_rank_chg  = current_era_rank  - new_era_rank   # positive = moved up
                    whip_rank_chg = current_whip_rank - new_whip_rank

                    if d_era <= 0 and d_whip <= 0:
                        verdict = "✅ Helps both"
                    elif d_era <= 0 or d_whip <= 0:
                        verdict = "➕ Helps one"
                    elif d_era <= 0.10 and d_whip <= 0.015:
                        verdict = "➖ Neutral"
                    else:
                        verdict = "⛔ Hurts"

                    sim_rows.append({
                        "Player":      p.name,
                        "Team":        p.proTeam if hasattr(p, "proTeam") else "—",
                        "% Own":       round(getattr(p, "percent_owned", 0) or 0, 1),
                        "Proj ERA":    p_era,
                        "Proj WHIP":   p_whip,
                        "Proj K":      entry.get("K", 0),
                        "Proj W":      entry.get("W", 0),
                        "ERA Δ":       f"{d_era:+.2f}",
                        "WHIP Δ":      f"{d_whip:+.3f}",
                        "ERA Rank":    f"#{current_era_rank}→#{min(new_era_rank,n2)}" if era_rank_chg != 0 else f"#{current_era_rank} (no chg)",
                        "WHIP Rank":   f"#{current_whip_rank}→#{min(new_whip_rank,n2)}" if whip_rank_chg != 0 else f"#{current_whip_rank} (no chg)",
                        "Verdict":     verdict,
                        "_era_d":      d_era,
                        "_whip_d":     d_whip,
                        "Status":      getattr(p, "injuryStatus", "ACTIVE"),
                    })

                if not sim_rows:
                    st.info("No FanGraphs projections found for available starters.")
                else:
                    sim_df = (
                        pd.DataFrame(sim_rows)
                        .sort_values(["_era_d", "_whip_d"])   # best ERA impact first
                        .drop(columns=["_era_d", "_whip_d"])
                    )
                    sim_df = apply_badges(sim_df)

                    def _verdict_style(val):
                        if "Helps both" in str(val):
                            return "background-color:rgba(34,197,94,0.20);color:#15803D;font-weight:700"
                        if "Helps one"  in str(val):
                            return "background-color:rgba(34,197,94,0.10);color:#166534"
                        if "Neutral"    in str(val):
                            return "color:#64748B"
                        if "Hurts"      in str(val):
                            return "background-color:rgba(239,68,68,0.18);color:#B91C1C;font-weight:700"
                        return ""

                    def _delta_style(val):
                        try:
                            v = float(str(val).replace("+",""))
                            if v < -0.01: return "color:#15803D;font-weight:600"
                            if v >  0.05: return "color:#B91C1C;font-weight:600"
                        except Exception:
                            pass
                        return "color:#64748B"

                    styled_sim = (
                        sim_df.style
                        .applymap(_verdict_style, subset=["Verdict"])
                        .applymap(_delta_style,   subset=["ERA Δ", "WHIP Δ"])
                    )
                    st.dataframe(
                        styled_sim, use_container_width=True, hide_index=True,
                        column_config={
                            "Player":    st.column_config.TextColumn("Player",    width="medium"),
                            "Team":      st.column_config.TextColumn("Team",      width="small"),
                            "% Own":     pct_cfg("% Own"),
                            "Proj ERA":  num_cfg("ERA",  "%.2f"),
                            "Proj WHIP": num_cfg("WHIP", "%.2f"),
                            "Proj K":    num_cfg("K",    "%.0f"),
                            "Proj W":    num_cfg("W",    "%.0f"),
                            "ERA Δ":     st.column_config.TextColumn("ERA Δ",    width="small"),
                            "WHIP Δ":    st.column_config.TextColumn("WHIP Δ",   width="small"),
                            "ERA Rank":  st.column_config.TextColumn("ERA Rank",  width="medium"),
                            "WHIP Rank": st.column_config.TextColumn("WHIP Rank", width="medium"),
                            "Verdict":   st.column_config.TextColumn("Verdict",   width="medium"),
                            "Status":    st.column_config.TextColumn("Health",    width="small"),
                        }
                    )

                    helps = sim_df[sim_df["Verdict"].str.contains("Helps both", na=False)]
                    hurts = sim_df[sim_df["Verdict"].str.contains("Hurts",      na=False)]
                    if not helps.empty:
                        st.success(f"✅ **{len(helps)} pitchers** will improve your ERA & WHIP: "
                                   f"{', '.join(helps['Player'].head(5).tolist())}")
                    if not hurts.empty:
                        st.warning(f"⛔ **{len(hurts)} pitchers** will hurt your ratios — avoid streaming them.")

    # ════════════════════════════════════════════════════════════════════════════
    elif roto_tool == "📈 Pace Tracker":
    # ════════════════════════════════════════════════════════════════════════════
        st.subheader("📈 Pace Tracker")
        st.caption("Are your players on pace to hit their FanGraphs projections? "
                   "Flags over-performers (sell high?) and under-performers (buy low / drop?).")

        # Estimate season progress from current scoring period
        _TOTAL_WEEKS = 25
        season_pct = min(max(round((current_period - 1) / _TOTAL_WEEKS, 3), 0.01), 1.0)
        weeks_left  = max(_TOTAL_WEEKS - (current_period - 1), 1)
        st.info(f"📅 Week **{current_period}** of ~{_TOTAL_WEEKS} · Season is **{round(season_pct*100, 0):.0f}%** complete · **{weeks_left}** weeks remaining")

        pace_rows = []
        for p in my_team.roster:
            # 2026 YTD stats from current league player object
            ytd: dict = {}
            try:
                ytd = p.stats.get(0, {}).get("breakdown", {}) or {}
            except Exception:
                pass

            entry     = fg.get(p.name, {}) or {}
            pitcher   = is_pitcher(p)
            cats = [("W","W"), ("SV","SV"), ("K","K"), ("ERA","ERA"), ("WHIP","WHIP")] if pitcher else \
                   [("HR","HR"), ("R","R"),  ("RBI","RBI"), ("SB","SB"), ("AVG","AVG")]

            for stat_key, label in cats:
                proj_full = entry.get(stat_key)
                ytd_val   = ytd.get(stat_key)
                if proj_full is None or ytd_val is None:
                    continue
                try:
                    proj_full = float(proj_full)
                    ytd_val   = float(ytd_val)
                except Exception:
                    continue
                if proj_full == 0:
                    continue

                # For rate stats, compare directly; for counting, extrapolate
                if stat_key in ("AVG", "ERA", "WHIP"):
                    pace_val = ytd_val                              # current rate
                    proj_remaining = proj_full                      # projection stays same
                    pct_diff = (pace_val - proj_full) / proj_full
                else:
                    pace_full = ytd_val / season_pct               # extrapolate to full season
                    proj_remaining = proj_full * (1 - season_pct)  # still to earn
                    pct_diff = (pace_full - proj_full) / proj_full
                    pace_val = pace_full

                flag = ""
                if pct_diff > 0.25:
                    flag = "🔥 Way ahead"
                elif pct_diff > 0.12:
                    flag = "📈 Ahead"
                elif pct_diff < -0.25:
                    flag = "🚨 Way behind"
                elif pct_diff < -0.12:
                    flag = "📉 Behind"

                fmt3 = stat_key in ("AVG", "ERA", "WHIP")
                pace_rows.append({
                    "Player":      p.name,
                    "Pos":         pos_str(p),
                    "Stat":        label,
                    "YTD":         round(ytd_val,  3 if fmt3 else 0),
                    "On Pace For": round(pace_val,  3 if fmt3 else 0),
                    "FG Proj":     round(proj_full, 3 if fmt3 else 0),
                    "% Diff":      round(pct_diff * 100, 1),
                    "Trend":       flag,
                })

        if not pace_rows:
            st.info("No 2026 season stats available yet — check back once the season is underway.")
        else:
            pace_df = pd.DataFrame(pace_rows)

            # Filter controls
            fc1, fc2 = st.columns(2)
            with fc1:
                show_filter = st.selectbox("Show", ["All", "🔥 Way ahead only", "🚨 Way behind only",
                                                     "Notable (>12% off)"], key="pace_filter")
            with fc2:
                cat_filter = st.selectbox("Category", ["All"] + ["HR","R","RBI","SB","AVG","W","SV","K","ERA","WHIP"],
                                          key="pace_cat")
            if show_filter == "🔥 Way ahead only":
                pace_df = pace_df[pace_df["Trend"] == "🔥 Way ahead"]
            elif show_filter == "🚨 Way behind only":
                pace_df = pace_df[pace_df["Trend"] == "🚨 Way behind"]
            elif show_filter == "Notable (>12% off)":
                pace_df = pace_df[pace_df["Trend"] != ""]
            if cat_filter != "All":
                pace_df = pace_df[pace_df["Stat"] == cat_filter]

            def _pace_color(val):
                if isinstance(val, str):
                    if "Way ahead" in val:  return "color:#15803D;font-weight:700"
                    if "Ahead"     in val:  return "color:#166534"
                    if "Way behind"in val:  return "color:#B91C1C;font-weight:700"
                    if "Behind"    in val:  return "color:#C2410C"
                if isinstance(val, float):
                    if val > 25:  return "color:#15803D;font-weight:700"
                    if val > 12:  return "color:#166534"
                    if val < -25: return "color:#B91C1C;font-weight:700"
                    if val < -12: return "color:#C2410C"
                return ""

            styled_pace = pace_df.style.applymap(_pace_color, subset=["Trend", "% Diff"])
            st.dataframe(styled_pace, use_container_width=True, hide_index=True,
                         column_config={
                             "Player":      st.column_config.TextColumn("Player", width="medium"),
                             "Pos":         st.column_config.TextColumn("Pos", width="small"),
                             "Stat":        st.column_config.TextColumn("Stat", width="small"),
                             "YTD":         num_cfg("YTD"),
                             "On Pace For": num_cfg("On Pace For"),
                             "FG Proj":     num_cfg("FG Proj"),
                             "% Diff":      num_cfg("% Diff", "%.1f"),
                             "Trend":       st.column_config.TextColumn("Trend", width="medium"),
                         })

            # Sell-high and buy-low callouts
            sell_high = pace_df[pace_df["Trend"] == "🔥 Way ahead"]["Player"].unique().tolist()
            buy_low   = pace_df[pace_df["Trend"] == "🚨 Way behind"]["Player"].unique().tolist()
            if sell_high:
                st.success(f"🔥 **Sell-high candidates** (outpacing projection significantly): {', '.join(sell_high)}")
            if buy_low:
                st.warning(f"🚨 **Buy-low / re-evaluate** (lagging projection significantly): {', '.join(buy_low)}")

    # ════════════════════════════════════════════════════════════════════════════
    elif roto_tool == "🔒 Closer Monitor":
    # ════════════════════════════════════════════════════════════════════════════
        st.subheader("🔒 Closer Monitor")
        st.caption("Track save situations across your roster and the waiver wire. "
                   "SV is the most volatile roto category — one closer losing their job can cost you a full rank.")

        def _sv_tier(proj_sv):
            if proj_sv >= 30: return "🟢 Secure"
            if proj_sv >= 20: return "🟡 Likely Starter"
            if proj_sv >= 10: return "🟠 Committee / Shaky"
            return "🔴 Fringe"

        # ── My Closers ────────────────────────────────────────────────────────
        st.subheader("🗂️ Your Roster — Save Situations")
        my_rp_rows = []
        for p in my_team.roster:
            if not is_pitcher(p):
                continue
            entry     = fg.get(p.name, {}) or {}
            proj_sv   = float(entry.get("SV") or 0)
            proj_era  = float(entry.get("ERA") or 0)
            proj_whip = float(entry.get("WHIP") or 0)
            proj_k    = float(entry.get("K") or 0)
            proj_ip   = float(entry.get("IP") or 0)
            ps        = prev_stats.get(p.name, {})
            actual_sv_2025 = ps.get("SV", 0) or 0
            my_rp_rows.append({
                "Pitcher":       p.name,
                "Type":          pos_str(p),
                "Team":          p.proTeam if hasattr(p, "proTeam") else "—",
                "Proj SV":       round(proj_sv,  0),
                "Proj ERA":      round(proj_era,  2),
                "Proj WHIP":     round(proj_whip, 3),
                "Proj K":        round(proj_k,    0),
                "Proj IP":       round(proj_ip,   0),
                "2025 SV":       actual_sv_2025,
                "Job Security":  _sv_tier(proj_sv),
                "Status":        getattr(p, "injuryStatus", "ACTIVE"),
            })

        if my_rp_rows:
            my_rp_df = apply_badges(
                pd.DataFrame(my_rp_rows).sort_values("Proj SV", ascending=False)
            )
            def _tier_style(val):
                if "Secure"   in str(val): return "color:#15803D;font-weight:700"
                if "Likely"   in str(val): return "color:#166534"
                if "Committee"in str(val): return "color:#92400E;font-weight:700"
                if "Fringe"   in str(val): return "color:#B91C1C"
                return ""
            st.dataframe(
                my_rp_df.style.applymap(_tier_style, subset=["Job Security"]),
                use_container_width=True, hide_index=True,
                column_config={
                    "Pitcher":      st.column_config.TextColumn("Pitcher",      width="medium"),
                    "Type":         st.column_config.TextColumn("Type",         width="small"),
                    "Team":         st.column_config.TextColumn("Team",         width="small"),
                    "Proj SV":      num_cfg("Proj SV",  "%.0f"),
                    "Proj ERA":     num_cfg("Proj ERA",  "%.2f"),
                    "Proj WHIP":    num_cfg("Proj WHIP", "%.2f"),
                    "Proj K":       num_cfg("Proj K",    "%.0f"),
                    "Proj IP":      num_cfg("Proj IP",   "%.0f"),
                    "2025 SV":      num_cfg("'25 SV",    "%.0f"),
                    "Job Security": st.column_config.TextColumn("Security",     width="medium"),
                    "Status":       st.column_config.TextColumn("Health",       width="small"),
                }
            )
            shaky = [r["Pitcher"] for r in my_rp_rows
                     if "Committee" in r["Job Security"] or "Fringe" in r["Job Security"]]
            if shaky:
                st.warning(f"⚠️ Shaky closer situations on your roster: **{', '.join(shaky)}** — "
                           "monitor news closely and have a handcuff ready.")
        else:
            st.info("No pitchers found on your roster.")

        st.divider()

        # ── Available Closers on Waivers ──────────────────────────────────────
        st.subheader("🆓 Available Closers & High-SV Arms on Waivers")
        st.caption("Free agents projected for 10+ saves — sorted by projected SV. "
                   "Prioritise teams with the strongest bullpen usage.")

        with st.spinner("Loading available relievers…"):
            try:
                rp_fa = league.free_agents(size=120, position="RP")
            except Exception:
                rp_fa = []

        closer_fa_rows = []
        for p in rp_fa:
            entry     = fg.get(p.name, {}) or {}
            proj_sv   = float(entry.get("SV") or 0)
            if proj_sv < 5:
                continue
            proj_era  = float(entry.get("ERA") or 0)
            proj_whip = float(entry.get("WHIP") or 0)
            proj_k    = float(entry.get("K") or 0)
            ps        = prev_stats.get(p.name, {})
            actual_sv = ps.get("SV", 0) or 0
            g2025, g_ytd, g_proj = player_grades(p, prev_stats, fg)
            closer_fa_rows.append({
                "Pitcher":      p.name,
                "Team":         p.proTeam if hasattr(p, "proTeam") else "—",
                "% Own":        round(getattr(p, "percent_owned", 0) or 0, 1),
                "Proj SV":      round(proj_sv,  0),
                "Proj ERA":     round(proj_era,  2),
                "Proj WHIP":    round(proj_whip, 3),
                "Proj K":       round(proj_k,    0),
                "2025 SV":      actual_sv,
                "Security":     _sv_tier(proj_sv),
                "G '25":        g2025,
                "G '26 Proj":   g_proj,
                "Status":       getattr(p, "injuryStatus", "ACTIVE"),
            })

        if not closer_fa_rows:
            st.info("No closers available on waivers — your league may have them all rostered.")
        else:
            cfa_df = apply_badges(
                pd.DataFrame(closer_fa_rows).sort_values("Proj SV", ascending=False)
            )
            st.dataframe(
                cfa_df.style.applymap(_tier_style, subset=["Security"]),
                use_container_width=True, hide_index=True,
                column_config={
                    "Pitcher":    st.column_config.TextColumn("Pitcher",  width="medium"),
                    "Team":       st.column_config.TextColumn("Team",     width="small"),
                    "% Own":      pct_cfg("% Own"),
                    "Proj SV":    num_cfg("Proj SV",  "%.0f"),
                    "Proj ERA":   num_cfg("Proj ERA",  "%.2f"),
                    "Proj WHIP":  num_cfg("Proj WHIP", "%.2f"),
                    "Proj K":     num_cfg("Proj K",    "%.0f"),
                    "2025 SV":    num_cfg("'25 SV",    "%.0f"),
                    "Security":   st.column_config.TextColumn("Security", width="medium"),
                    "G '25":      GRADE_COL_CFG["G '25"],
                    "G '26 Proj": GRADE_COL_CFG["G '26 Proj"],
                    "Status":     st.column_config.TextColumn("Health",   width="small"),
                }
            )
            secure_fa = [r["Pitcher"] for r in closer_fa_rows if "Secure" in r["Security"]]
            if secure_fa:
                st.success(f"🟢 **Secure closers on the wire**: {', '.join(secure_fa[:5])} — if any are available, add them immediately.")

        # ── Closer News ───────────────────────────────────────────────────────
        st.divider()
        st.subheader("📰 Latest Closer News")
        st.caption("Recent ESPN news mentioning saves, closers, or bullpen roles.")
        all_news_c = fetch_news_feed()
        closer_keywords = {"save", "closer", "closing", "ninth", "bullpen", "hold", "blown"}
        closer_news = [
            item for item in all_news_c
            if any(kw in (item.get("headline","") + " " + item.get("description","")).lower()
                   for kw in closer_keywords)
        ][:10]
        if closer_news:
            for item in closer_news:
                ath  = item["athletes"][0]["name"] if item.get("athletes") else ""
                pub  = item["published"].strftime("%-I:%M %p") if item.get("published") else ""
                link = item.get("link","")
                link_html = f" <a href='{link}' target='_blank' style='color:#1565C0'>Read →</a>" if link else ""
                st.markdown(
                    f"<div style='padding:8px 12px;margin-bottom:6px;border-left:3px solid #1565C0;"
                    f"border-radius:4px;background:rgba(21,101,192,0.05)'>"
                    f"<span style='font-weight:700;color:#0F3460'>{ath}</span>"
                    f"<span style='color:#94A3B8;font-size:11px;margin-left:8px'>{pub}</span><br>"
                    f"<span style='color:#1E293B'>{item['headline']}</span>{link_html}"
                    f"</div>",
                    unsafe_allow_html=True
                )
        else:
            st.info("No closer-related news in the last 24 hours.")

    # ════════════════════════════════════════════════════════════════════════════
    elif roto_tool == "⚡ Starts Maximizer":
    # ════════════════════════════════════════════════════════════════════════════
        st.subheader("⚡ Starts Maximizer")
        st.caption("Every game your active players don't play is a roto counting stat you can't get back. "
                   "See who's playing the rest of this week and how many games each player has left.")

        today_d  = datetime.now().date()
        monday   = today_d - timedelta(days=today_d.weekday())
        sunday   = monday + timedelta(days=6)
        days_rem = [(today_d + timedelta(days=i)) for i in range((sunday - today_d).days + 1)]

        # Fetch remaining-week schedule
        with st.spinner("Loading this week's schedule…"):
            team_days: dict = {}   # {team_abbr: [day_labels]}
            for d in days_rem:
                events = fetch_mlb_scoreboard(d.strftime("%Y%m%d"))
                for event in events:
                    for comp in event.get("competitions", [{}]):
                        for td in comp.get("competitors", []):
                            abbr = td.get("team", {}).get("abbreviation", "")
                            if abbr:
                                team_days.setdefault(abbr, []).append(d.strftime("%a"))

        st.caption(f"Week: **{monday.strftime('%b %-d')} – {sunday.strftime('%b %-d')}**  ·  "
                   f"Days remaining (incl. today): **{len(days_rem)}**")

        # ── Hitter Games Remaining ────────────────────────────────────────────
        st.subheader("🏏 Hitter Games Remaining This Week")
        hitter_rows = []
        for p in my_team.roster:
            if is_pitcher(p):
                continue
            team_abbr  = (p.proTeam or "").upper()
            days_list  = team_days.get(team_abbr, [])
            games_left = len(days_list)
            schedule   = "  ".join(days_list) if days_list else "Off"
            status     = getattr(p, "injuryStatus", "ACTIVE")
            hitter_rows.append({
                "Player":       p.name,
                "Position":     pos_str(p),
                "Team":         team_abbr,
                "Games Left":   games_left,
                "Schedule":     schedule,
                "Roto Val":     fg_roto_value(p),
                "Helps":        roto_helps_str(p),
                "Status":       status,
            })

        if hitter_rows:
            h_df = apply_badges(
                pd.DataFrame(hitter_rows).sort_values(["Games Left", "Roto Val"], ascending=[False, False])
            )
            def _games_color(val):
                try:
                    v = int(val)
                    if v >= 5: return "color:#15803D;font-weight:700"
                    if v >= 3: return "color:#166534"
                    if v == 0: return "color:#B91C1C;font-weight:700"
                    return ""
                except Exception:
                    return ""
            st.dataframe(
                h_df.style.applymap(_games_color, subset=["Games Left"]),
                use_container_width=True, hide_index=True,
                column_config={
                    "Player":     st.column_config.TextColumn("Player",    width="medium"),
                    "Position":   st.column_config.TextColumn("Pos",       width="small"),
                    "Team":       st.column_config.TextColumn("Team",      width="small"),
                    "Games Left": num_cfg("Games Left", "%.0f"),
                    "Schedule":   st.column_config.TextColumn("Days",      width="medium"),
                    "Roto Val":   roto_cfg("Roto Val"),
                    "Helps":      st.column_config.TextColumn("Helps",     width="small"),
                    "Status":     st.column_config.TextColumn("Health",    width="small"),
                }
            )
            cold_hitters = [r["Player"] for r in hitter_rows if r["Games Left"] == 0]
            rich_hitters = [r["Player"] for r in hitter_rows if r["Games Left"] >= 5]
            if cold_hitters:
                st.warning(f"⚠️ Off this week: **{', '.join(cold_hitters)}** — consider streaming a replacement hitter.")
            if rich_hitters:
                st.success(f"✅ Heavy schedule: **{', '.join(rich_hitters[:5])}** — make sure they're all active.")
        else:
            st.info("No hitters found.")

        st.divider()

        # ── SP Starts This Week ───────────────────────────────────────────────
        st.subheader("🎯 Pitcher Starts This Week")
        sp_rows = []
        for p in my_team.roster:
            if not is_pitcher(p):
                continue
            team_abbr = (p.proTeam or "").upper()
            days_list = team_days.get(team_abbr, [])
            # Pitchers don't play every game their team does; check probables from two-start data
            two_s     = fetch_weekly_starts(monday.strftime("%Y%m%d"))
            confirmed = two_s.get(p.name, {})
            starts_confirmed = confirmed.get("starts", 0)
            start_dates      = "  ·  ".join(confirmed.get("dates", [])) if confirmed else "TBD"
            entry = fg.get(p.name, {}) or {}
            sp_rows.append({
                "Pitcher":      p.name,
                "Type":         pos_str(p),
                "Team":         team_abbr,
                "Confirmed Starts": starts_confirmed,
                "Start Dates":  start_dates,
                "Proj ERA":     entry.get("ERA", "—"),
                "Proj K/start": round(float(entry.get("K") or 0) / max(float(entry.get("GS") or 30), 1), 1),
                "Status":       getattr(p, "injuryStatus", "ACTIVE"),
            })

        if sp_rows:
            sp_df = apply_badges(pd.DataFrame(sp_rows).sort_values("Confirmed Starts", ascending=False))
            def _starts_color(val):
                try:
                    v = int(val)
                    if v >= 2: return "color:#15803D;font-weight:700"
                    if v == 1: return "color:#166534"
                    return "color:#94A3B8"
                except Exception:
                    return ""
            st.dataframe(
                sp_df.style.applymap(_starts_color, subset=["Confirmed Starts"]),
                use_container_width=True, hide_index=True,
                column_config={
                    "Pitcher":          st.column_config.TextColumn("Pitcher",      width="medium"),
                    "Type":             st.column_config.TextColumn("Type",         width="small"),
                    "Team":             st.column_config.TextColumn("Team",         width="small"),
                    "Confirmed Starts": num_cfg("Starts",   "%.0f"),
                    "Start Dates":      st.column_config.TextColumn("Schedule",     width="large"),
                    "Proj ERA":         num_cfg("ERA",       "%.2f"),
                    "Proj K/start":     num_cfg("K/Start",   "%.1f"),
                    "Status":           st.column_config.TextColumn("Health",       width="small"),
                }
            )
            two_starters_mine = [r["Pitcher"] for r in sp_rows if r["Confirmed Starts"] >= 2]
            no_starts = [r["Pitcher"] for r in sp_rows if r["Confirmed Starts"] == 0
                         and "SP" in r["Type"] and r["Status"] not in ("INJURY_RESERVE", "OUT")]
            if two_starters_mine:
                st.success(f"✅ Two-start pitchers to lock in: **{', '.join(two_starters_mine)}**")
            if no_starts:
                st.info(f"ℹ️ No confirmed starts yet for: {', '.join(no_starts)} — check back as the week progresses.")

    # ════════════════════════════════════════════════════════════════════════════
    elif roto_tool == "🎯 Punt Advisor":
    # ════════════════════════════════════════════════════════════════════════════
        st.subheader("🎯 Punt Advisor")
        st.caption("Deliberately sacrificing a weak category frees you to dominate the other 9. "
                   "This tool shows your optimal punt strategy based on your current roster.")

        team_proj, team_ranks, all_cats, lower_better, n_teams = _build_team_proj()
        my_name  = my_team.team_name
        my_ranks = team_ranks.get(my_name, {})

        if not my_ranks:
            st.warning("Could not find your team in projected standings.")
        else:
            # Roto pts for each category: 1st = n_teams pts, last = 1 pt
            def rp(rank): return max(n_teams + 1 - int(rank), 0)

            current_pts   = sum(rp(my_ranks.get(c, n_teams)) for c in all_cats)
            max_pts       = len(all_cats) * n_teams
            current_place = sorted(
                [sum(rp(team_ranks.get(t, {}).get(c, n_teams)) for c in all_cats) for t in team_ranks],
                reverse=True
            ).index(current_pts) + 1

            col_a, col_b, col_c = st.columns(3)
            col_a.metric("Current Roto Pts", current_pts)
            col_b.metric("Max Possible",     max_pts)
            col_c.metric("Projected Finish", f"#{current_place} of {n_teams}")

            st.divider()

            # ── Single-Category Punt Analysis ─────────────────────────────────
            st.subheader("Single-Category Punt Options")
            st.caption("Ranks each category by how little you lose by punting it — your weakest cats are the cheapest to punt.")

            single_rows = []
            for cat in all_cats:
                my_rank  = my_ranks.get(cat, n_teams)
                pts_lost = rp(my_rank)                      # pts you'd lose by ignoring this cat
                remaining_cats = [c for c in all_cats if c != cat]
                remaining_pts  = sum(rp(my_ranks.get(c, n_teams)) for c in remaining_cats)
                max_remaining  = len(remaining_cats) * n_teams
                pct_remain     = round(remaining_pts / max_remaining * 100, 1)

                # How many ranks above current finish could you get?
                all_team_remaining = {
                    t: sum(rp(team_ranks.get(t, {}).get(c, n_teams)) for c in remaining_cats)
                    for t in team_ranks
                }
                my_remaining_rank = sorted(
                    all_team_remaining.values(), reverse=True
                ).index(remaining_pts) + 1

                single_rows.append({
                    "Punt Cat":        cat,
                    "Your Rank":       f"#{my_rank} of {n_teams}",
                    "Pts Lost":        pts_lost,
                    "Score (other 9)": remaining_pts,
                    "% of Max":        pct_remain,
                    "Proj Finish (9 cats)": f"#{my_remaining_rank}",
                    "Rank Change":     current_place - my_remaining_rank,   # positive = move up
                    "Recommendation":  (
                        "✅ Punt this" if my_rank >= n_teams - 2
                        else "🟡 Consider" if my_rank >= n_teams - 4
                        else "🔴 Don't punt"
                    ),
                })

            single_df = pd.DataFrame(single_rows).sort_values("Pts Lost")

            def _punt_rec_style(val):
                if "✅" in str(val): return "color:#15803D;font-weight:700"
                if "🟡" in str(val): return "color:#92400E;font-weight:600"
                if "🔴" in str(val): return "color:#B91C1C"
                return ""
            def _rank_chg_style(val):
                try:
                    v = int(val)
                    if v > 0: return "color:#15803D;font-weight:700"
                    if v < 0: return "color:#B91C1C"
                except Exception:
                    pass
                return ""

            st.dataframe(
                single_df.style
                .applymap(_punt_rec_style, subset=["Recommendation"])
                .applymap(_rank_chg_style, subset=["Rank Change"]),
                use_container_width=True, hide_index=True,
                column_config={
                    "Punt Cat":             st.column_config.TextColumn("If You Punt",      width="small"),
                    "Your Rank":            st.column_config.TextColumn("Your Rank",         width="small"),
                    "Pts Lost":             num_cfg("Pts Lost",      "%.0f"),
                    "Score (other 9)":      num_cfg("Score (9 cats)","%.0f"),
                    "% of Max":             num_cfg("% of Max",      "%.1f"),
                    "Proj Finish (9 cats)": st.column_config.TextColumn("Proj Finish", width="small"),
                    "Rank Change":          num_cfg("Rank Chg ↑",    "%.0f"),
                    "Recommendation":       st.column_config.TextColumn("Verdict",          width="medium"),
                }
            )

            best_punt = single_df.sort_values("Rank Change", ascending=False).iloc[0]
            if int(best_punt["Rank Change"]) > 0:
                st.success(
                    f"🎯 **Best punt**: drop **{best_punt['Punt Cat']}** "
                    f"(you're {best_punt['Your Rank']}) → projects you from "
                    f"**#{current_place}** to **{best_punt['Proj Finish (9 cats)']}**. "
                    f"Target waiver pickups that help your other categories instead."
                )

            st.divider()

            # ── Two-Category Punt Analysis ────────────────────────────────────
            st.subheader("Two-Category Punt Options")
            st.caption("Punting two weak categories lets you go all-in on the other 8.")

            from itertools import combinations
            two_rows = []
            for cat_a, cat_b in combinations(all_cats, 2):
                remaining8 = [c for c in all_cats if c not in (cat_a, cat_b)]
                rem_pts    = sum(rp(my_ranks.get(c, n_teams)) for c in remaining8)
                max_rem8   = len(remaining8) * n_teams
                pct8       = round(rem_pts / max_rem8 * 100, 1)
                all_team_8 = {
                    t: sum(rp(team_ranks.get(t, {}).get(c, n_teams)) for c in remaining8)
                    for t in team_ranks
                }
                my_rank_8 = sorted(all_team_8.values(), reverse=True).index(rem_pts) + 1
                pts_lost   = rp(my_ranks.get(cat_a, n_teams)) + rp(my_ranks.get(cat_b, n_teams))
                two_rows.append({
                    "Punt":            f"{cat_a} + {cat_b}",
                    "Pts Lost":        pts_lost,
                    "Score (8 cats)":  rem_pts,
                    "% of Max":        pct8,
                    "Proj Finish":     f"#{my_rank_8}",
                    "Rank Change":     current_place - my_rank_8,
                })

            two_df = (
                pd.DataFrame(two_rows)
                .sort_values("Rank Change", ascending=False)
                .head(10)
            )
            st.dataframe(
                two_df.style.applymap(_rank_chg_style, subset=["Rank Change"]),
                use_container_width=True, hide_index=True,
                column_config={
                    "Punt":           st.column_config.TextColumn("If You Punt Both", width="medium"),
                    "Pts Lost":       num_cfg("Pts Lost",      "%.0f"),
                    "Score (8 cats)": num_cfg("Score (8 cats)","%.0f"),
                    "% of Max":       num_cfg("% of Max",      "%.1f"),
                    "Proj Finish":    st.column_config.TextColumn("Proj Finish", width="small"),
                    "Rank Change":    num_cfg("Rank Chg ↑",    "%.0f"),
                }
            )
            best2 = two_df.iloc[0]
            if int(best2["Rank Change"]) > 0:
                st.success(
                    f"🎯 **Best 2-cat punt**: **{best2['Punt']}** → "
                    f"projects you from **#{current_place}** to **{best2['Proj Finish']}**."
                )

    # ════════════════════════════════════════════════════════════════════════════
    elif roto_tool == "📉 Buy Low / Sell High":
    # ════════════════════════════════════════════════════════════════════════════
        st.subheader("📉 Buy Low / Sell High")
        st.caption(
            "Compares each rostered player's current season pace to their FanGraphs projection. "
            "🔴 **Sell High** = significantly outperforming projections (regression risk). "
            "🟢 **Buy Low** = significantly underperforming (bounce-back candidate). "
            "Requires at least 30 AB (hitters) or 10 IP (pitchers) of YTD data."
        )

        bat_rows, pit_rows = [], []

        for t in league.teams:
            for p in t.roster:
                entry = fg.get(p.name, {})
                if not entry:
                    continue
                try:
                    ytd = (p.stats or {}).get(0, {}).get("breakdown", {}) or {}
                except Exception:
                    ytd = {}
                on_mine = (t.team_name == my_team.team_name)

                if is_pitcher(p):
                    ip_ytd  = float(ytd.get("IP",   0) or 0)
                    ip_proj = float(entry.get("IP",  0) or 0)
                    if ip_ytd < 10 or ip_proj < 1:
                        continue

                    era_ytd   = float(ytd.get("ERA",  0) or 0)
                    whip_ytd  = float(ytd.get("WHIP", 0) or 0)
                    k_ytd     = float(ytd.get("K", ytd.get("SO", 0)) or 0)
                    era_proj  = float(entry.get("ERA",  0) or 0)
                    whip_proj = float(entry.get("WHIP", 0) or 0)
                    k_proj    = float(entry.get("K",    0) or 0)
                    k9_ytd    = k_ytd  / ip_ytd  * 9 if ip_ytd  > 0 else 0
                    k9_proj   = k_proj / ip_proj * 9 if ip_proj > 0 else 0

                    # ratio > 1 means performing better than projected
                    ratios = []
                    if era_proj  > 0 and era_ytd  > 0: ratios.append(era_proj  / era_ytd)
                    if whip_proj > 0 and whip_ytd > 0: ratios.append(whip_proj / whip_ytd)
                    if k9_proj   > 0 and k9_ytd   > 0: ratios.append(k9_ytd   / k9_proj)
                    if not ratios:
                        continue
                    ratio = sum(ratios) / len(ratios)

                    if   ratio > 1.30: signal = "🔴 Sell High"
                    elif ratio < 0.70: signal = "🟢 Buy Low"
                    else:              continue   # on-track — skip to keep table focused

                    pit_rows.append({
                        "Player":      p.name,
                        "Mine":        "✅" if on_mine else "",
                        "Fantasy Tm":  t.team_name[:14],
                        "IP (YTD)":    round(ip_ytd,   1),
                        "ERA (YTD)":   round(era_ytd,  2),
                        "ERA (Proj)":  round(era_proj, 2),
                        "WHIP (YTD)":  round(whip_ytd,  3),
                        "WHIP (Proj)": round(whip_proj, 3),
                        "K/9 (YTD)":   round(k9_ytd,  1),
                        "K/9 (Proj)":  round(k9_proj, 1),
                        "Signal":      signal,
                        "_ratio":      ratio,
                    })

                else:
                    ab_ytd   = float(ytd.get("AB",  0) or 0)
                    if ab_ytd < 30:
                        continue
                    avg_ytd       = float(ytd.get("AVG", 0) or 0)
                    hr_ytd        = float(ytd.get("HR",  0) or 0)
                    avg_proj      = float(entry.get("AVG", 0) or 0)
                    hr_proj       = float(entry.get("HR",  0) or 0)
                    ab_proj_fg    = float(entry.get("AB",  0) or 0)
                    hr_pa_ytd     = hr_ytd  / ab_ytd    if ab_ytd    > 0 else 0
                    hr_pa_proj    = hr_proj / ab_proj_fg if ab_proj_fg > 0 else 0

                    ratios = []
                    if avg_proj  > 0: ratios.append(avg_ytd    / avg_proj)
                    if hr_pa_proj > 0: ratios.append(hr_pa_ytd / hr_pa_proj)
                    if not ratios:
                        continue
                    ratio = sum(ratios) / len(ratios)

                    if   ratio > 1.30: signal = "🔴 Sell High"
                    elif ratio < 0.70: signal = "🟢 Buy Low"
                    else:              continue

                    bat_rows.append({
                        "Player":     p.name,
                        "Mine":       "✅" if on_mine else "",
                        "Fantasy Tm": t.team_name[:14],
                        "AB (YTD)":   int(ab_ytd),
                        "AVG (YTD)":  round(avg_ytd,  3),
                        "AVG (Proj)": round(avg_proj, 3),
                        "HR (YTD)":   int(hr_ytd),
                        "HR (Proj)":  round(hr_proj, 1),
                        "Signal":     signal,
                        "_ratio":     ratio,
                    })

        def _signal_style(val):
            s = str(val)
            if "Sell" in s: return "background-color:rgba(239,68,68,0.15);color:#B91C1C;font-weight:700"
            if "Buy"  in s: return "background-color:rgba(34,197,94,0.15);color:#15803D;font-weight:700"
            return ""

        if not bat_rows and not pit_rows:
            st.info("Not enough YTD data yet — check back once the season is underway (need 30 AB / 10 IP).")
        else:
            if bat_rows:
                st.markdown("#### 🏏 Hitters")
                bat_df = (
                    pd.DataFrame(bat_rows)
                    .drop(columns=["_ratio"])
                    .sort_values("Signal", key=lambda s: s.str.contains("Sell").astype(int), ascending=False)
                )
                st.dataframe(
                    bat_df.style.applymap(_signal_style, subset=["Signal"]),
                    use_container_width=True, hide_index=True,
                    column_config={
                        "Mine":       st.column_config.TextColumn("Mine",       width="small"),
                        "AB (YTD)":   num_cfg("AB"),
                        "AVG (YTD)":  num_cfg("AVG YTD",  "%.3f"),
                        "AVG (Proj)": num_cfg("AVG Proj",  "%.3f"),
                        "HR (YTD)":   num_cfg("HR YTD"),
                        "HR (Proj)":  num_cfg("HR Proj",   "%.1f"),
                        "Signal":     st.column_config.TextColumn("Signal",     width="medium"),
                    },
                )

            if pit_rows:
                st.markdown("#### ⚾ Pitchers")
                pit_df = (
                    pd.DataFrame(pit_rows)
                    .drop(columns=["_ratio"])
                    .sort_values("Signal", key=lambda s: s.str.contains("Sell").astype(int), ascending=False)
                )
                st.dataframe(
                    pit_df.style.applymap(_signal_style, subset=["Signal"]),
                    use_container_width=True, hide_index=True,
                    column_config={
                        "Mine":        st.column_config.TextColumn("Mine",        width="small"),
                        "IP (YTD)":    num_cfg("IP"),
                        "ERA (YTD)":   num_cfg("ERA YTD",   "%.2f"),
                        "ERA (Proj)":  num_cfg("ERA Proj",  "%.2f"),
                        "WHIP (YTD)":  num_cfg("WHIP YTD",  "%.3f"),
                        "WHIP (Proj)": num_cfg("WHIP Proj", "%.3f"),
                        "K/9 (YTD)":   num_cfg("K/9 YTD",  "%.1f"),
                        "K/9 (Proj)":  num_cfg("K/9 Proj",  "%.1f"),
                        "Signal":      st.column_config.TextColumn("Signal",      width="medium"),
                    },
                )

    # ════════════════════════════════════════════════════════════════════════════
    elif roto_tool == "🚨 Emergency Replacements":
    # ════════════════════════════════════════════════════════════════════════════
        st.subheader("🚨 Emergency Replacement Tool")
        st.caption(
            "When a player hits the IL, this instantly surfaces the best available free agents at that position, "
            "ranked by roto value so you can act fast."
        )

        il_players = [
            p for p in my_team.roster
            if getattr(p, "injuryStatus", "ACTIVE") in ("INJURY_RESERVE", "OUT", "DOUBTFUL")
        ]

        if not il_players:
            st.success("✅ No injured or IL players on your roster right now — everyone looks healthy!")
        else:
            with st.spinner("Loading free agents…"):
                try:
                    fa_pool = league.free_agents(size=200)
                except Exception:
                    fa_pool = []

            for il_p in il_players:
                il_status  = getattr(il_p, "injuryStatus", "OUT")
                il_pos_str = pos_str(il_p)
                my_roto    = fg_roto_value(il_p)

                st.markdown(f"### {badge(il_status)} **{il_p.name}** — {il_pos_str}")
                st.caption(
                    f"Your player's projected roto value: **{my_roto:+.2f}** &nbsp;|&nbsp; {fg_stat_str(il_p)}"
                )

                # Eligible slots for position matching
                il_slots = {
                    s.upper() for s in (il_p.eligibleSlots or [])
                    if s.upper() not in _NON_POSITIONS and not s.upper().startswith("IL")
                }

                fa_match = [
                    fa for fa in fa_pool
                    if any(s.upper() in il_slots for s in (fa.eligibleSlots or []))
                    and getattr(fa, "injuryStatus", "ACTIVE") not in ("INJURY_RESERVE", "OUT")
                ]
                fa_match.sort(key=fg_roto_value, reverse=True)
                fa_top = fa_match[:12]

                if not fa_top:
                    st.info(f"No free agents found matching {il_pos_str}.")
                else:
                    em_rows = []
                    for fa in fa_top:
                        em_rows.append({
                            "Player":    fa.name,
                            "Position":  pos_str(fa),
                            "Pro Team":  fa.proTeam,
                            "Roto Val":  fg_roto_value(fa),
                            "Δ vs IL'd": round(fg_roto_value(fa) - my_roto, 2),
                            "Helps":     roto_helps_str(fa),
                            "% Owned":   round(getattr(fa, "percent_owned", 0) or 0, 1),
                            "Status":    getattr(fa, "injuryStatus", "ACTIVE"),
                        })

                    em_df = apply_badges(pd.DataFrame(em_rows), "Status")

                    def _delta_em_style(val):
                        try:
                            v = float(val)
                            if v > 0:  return "color:#15803D;font-weight:700"
                            if v < 0:  return "color:#B91C1C"
                        except Exception:
                            pass
                        return ""

                    st.dataframe(
                        em_df.style.applymap(_delta_em_style, subset=["Δ vs IL'd"]),
                        use_container_width=True, hide_index=True,
                        column_config={
                            "Roto Val":  roto_cfg(),
                            "Δ vs IL'd": num_cfg("Δ Roto",  "%.2f"),
                            "% Owned":   pct_cfg(),
                            "Helps":     st.column_config.TextColumn("Helps",  width="small"),
                            "Status":    st.column_config.TextColumn("Health", width="small"),
                        },
                    )

                st.divider()

    # ════════════════════════════════════════════════════════════════════════════
    elif roto_tool == "⚔️ Matchup Breakdown":
    # ════════════════════════════════════════════════════════════════════════════
        st.subheader("⚔️ Weekly Category Matchup")
        st.caption(
            "Category-by-category comparison between your team and this week's opponent, "
            f"based on full-season **{fg_proj_label}** projections. Shows where you're winning and where you need help."
        )

        # Find current opponent from schedule
        opp_team = None
        for match in my_team.schedule:
            ht = getattr(match, "home_team", None)
            at = getattr(match, "away_team", None)
            if ht == my_team:
                opp_team = at
                break
            elif at == my_team:
                opp_team = ht
                break

        if opp_team is None:
            st.info("No current matchup found.")
        else:
            opp_name = getattr(opp_team, "team_name", str(opp_team))
            st.markdown(
                f"**{my_team.team_name}** vs **{opp_name}** "
                f"— Week {getattr(league, 'currentMatchupPeriod', '?')}"
            )

            team_proj, team_ranks, all_cats, lower_better, n_teams = _build_team_proj()
            my_proj  = team_proj.get(my_team.team_name, {})
            opp_proj = team_proj.get(opp_name, {})

            if not my_proj or not opp_proj:
                st.warning("Could not build projected stats for one or both teams. Make sure FanGraphs projections loaded.")
            else:
                match_rows = []
                my_wins_count = 0
                for cat in all_cats:
                    mv  = float(my_proj.get(cat, 0))
                    ov  = float(opp_proj.get(cat, 0))
                    inv = cat in lower_better
                    if mv == ov:
                        result = "➖ Tie"
                    elif (mv < ov if inv else mv > ov):
                        result = "✅ You Win"
                        my_wins_count += 1
                    else:
                        result = "❌ You Lose"
                    fmt_spec = ".3f" if cat in ("AVG", "ERA", "WHIP") else ".0f"
                    match_rows.append({
                        "Category":         cat,
                        "lower_is_better":  inv,
                        "You":              f"{mv:{fmt_spec}}",
                        "Opponent":         f"{ov:{fmt_spec}}",
                        "Result":           result,
                    })

                my_losses_count = sum(1 for r in match_rows if "Lose" in r["Result"])
                ties_count      = sum(1 for r in match_rows if "Tie"  in r["Result"])

                w_col, l_col, t_col = st.columns(3)
                w_col.metric("Projected Wins",   f"{my_wins_count} / 10")
                l_col.metric("Projected Losses", f"{my_losses_count} / 10")
                t_col.metric("Ties",             f"{ties_count}")

                def _matchup_result_style(val):
                    s = str(val)
                    if "You Win"  in s: return "background-color:rgba(34,197,94,0.18);color:#15803D;font-weight:700"
                    if "You Lose" in s: return "background-color:rgba(239,68,68,0.18);color:#B91C1C;font-weight:700"
                    return "color:#64748B"

                match_df = pd.DataFrame([
                    {"Category": r["Category"], "You": r["You"],
                     "Opponent": r["Opponent"],  "Result": r["Result"]}
                    for r in match_rows
                ])
                st.dataframe(
                    match_df.style.applymap(_matchup_result_style, subset=["Result"]),
                    use_container_width=True, hide_index=True,
                    column_config={
                        "Category": st.column_config.TextColumn("Category", width="small"),
                        "You":      st.column_config.TextColumn(my_team.team_name[:18], width="small"),
                        "Opponent": st.column_config.TextColumn(opp_name[:18],          width="small"),
                        "Result":   st.column_config.TextColumn("Result",               width="medium"),
                    },
                )

                win_cats  = [r["Category"] for r in match_rows if "Win"  in r["Result"]]
                lose_cats = [r["Category"] for r in match_rows if "Lose" in r["Result"]]
                if win_cats:
                    st.success(f"✅ Projected to win: **{', '.join(win_cats)}**")
                if lose_cats:
                    st.warning(f"⚠️ Need to close the gap in: **{', '.join(lose_cats)}**")

                # ── FA Recommendations for Losing Categories ──────────────────
                if lose_cats:
                    st.divider()
                    st.subheader("🆓 Free Agents That Can Flip This Matchup")
                    st.caption(
                        f"Ranked by how much they help in your **losing categories** "
                        f"({', '.join(lose_cats)}). "
                        "Drop suggestion = the weakest positional match on your roster."
                    )

                    _BAT_CAT_SET = {"HR", "R", "RBI", "SB", "AVG"}
                    _PIT_CAT_SET = {"W", "SV", "K", "ERA", "WHIP"}
                    lose_bat = [c for c in lose_cats if c in _BAT_CAT_SET]
                    lose_pit = [c for c in lose_cats if c in _PIT_CAT_SET]

                    with st.spinner("Scanning free agents…"):
                        try:
                            _fa_matchup = league.free_agents(size=200)
                        except Exception:
                            _fa_matchup = []

                    # Score every FA by their z-sum in the losing categories only
                    _fa_candidates = []
                    for _fa in _fa_matchup:
                        if getattr(_fa, "injuryStatus", "ACTIVE") in ("INJURY_RESERVE", "OUT"):
                            continue
                        _fa_cats   = fg_roto_cats(_fa)
                        _lose_rel  = lose_bat if not is_pitcher(_fa) else lose_pit
                        if not _lose_rel:
                            continue
                        _help      = sum(_fa_cats.get(c, 0) for c in _lose_rel)
                        _helped    = [c for c in _lose_rel if _fa_cats.get(c, 0) > 0.10]
                        if _help <= 0 or not _helped:
                            continue
                        _fa_candidates.append((_fa, _help, _helped))

                    _fa_candidates.sort(key=lambda x: x[1], reverse=True)

                    if not _fa_candidates:
                        st.info("No free agents found who meaningfully help in your losing categories.")
                    else:
                        # Roster sorted worst → best for drop suggestions
                        _roster_by_value = sorted(
                            my_team.roster,
                            key=fg_roto_value,
                        )

                        _fa_rows = []
                        for _fa, _help, _helped in _fa_candidates[:15]:
                            _fa_slots = {
                                s.upper() for s in (_fa.eligibleSlots or [])
                                if s.upper() not in _NON_POSITIONS
                                and not s.upper().startswith("IL")
                            }
                            # Best drop: worst roto player at a matching position
                            _drop = next(
                                (
                                    p for p in _roster_by_value
                                    if {
                                        s.upper() for s in (p.eligibleSlots or [])
                                        if s.upper() not in _NON_POSITIONS
                                        and not s.upper().startswith("IL")
                                    } & _fa_slots
                                    and getattr(p, "injuryStatus", "ACTIVE")
                                    not in ("INJURY_RESERVE",)
                                ),
                                None,
                            )
                            _drop_val = fg_roto_value(_drop) if _drop else 0.0
                            _net      = round(fg_roto_value(_fa) - _drop_val, 2)
                            _fa_rows.append({
                                "Add (FA)":      _fa.name,
                                "Position":      pos_str(_fa),
                                "FA Roto Val":   fg_roto_value(_fa),
                                "Helps With":    " ".join(f"+{c}" for c in _helped),
                                "% Owned":       round(getattr(_fa, "percent_owned", 0) or 0, 1),
                                "Drop":          _drop.name if _drop else "—",
                                "Drop Roto Val": round(_drop_val, 2) if _drop else None,
                                "Net Gain":      _net,
                            })

                        def _net_gain_style(val):
                            try:
                                v = float(val)
                                if v > 0.50: return "color:#15803D;font-weight:700"
                                if v < 0:    return "color:#B91C1C"
                            except Exception:
                                pass
                            return "color:#92400E"

                        def _helps_style(val):
                            return "color:#1565C0;font-weight:600" if str(val) != "—" else ""

                        _fa_df = pd.DataFrame(_fa_rows)
                        st.dataframe(
                            _fa_df.style
                            .applymap(_net_gain_style, subset=["Net Gain"])
                            .applymap(_helps_style,    subset=["Helps With"]),
                            use_container_width=True, hide_index=True,
                            column_config={
                                "Add (FA)":      st.column_config.TextColumn("Add (FA)",     width="medium"),
                                "Position":      st.column_config.TextColumn("Pos",          width="small"),
                                "FA Roto Val":   roto_cfg("FA Roto Val"),
                                "Helps With":    st.column_config.TextColumn("Helps With",   width="medium"),
                                "% Owned":       pct_cfg("% Own"),
                                "Drop":          st.column_config.TextColumn("Drop",         width="medium"),
                                "Drop Roto Val": num_cfg("Drop Val",      "%.2f"),
                                "Net Gain":      num_cfg("Net Roto Gain", "%.2f"),
                            },
                        )

                        # Top callout
                        _best = _fa_rows[0]
                        _drop_txt = (
                            f", dropping **{_best['Drop']}** ({_best['Drop Roto Val']:+.2f})"
                            if _best["Drop"] != "—" else ""
                        )
                        if _best["Net Gain"] > 0:
                            st.success(
                                f"🎯 **Best add**: **{_best['Add (FA)']}** "
                                f"(helps **{_best['Helps With']}**){_drop_txt} — "
                                f"net roto gain of **+{_best['Net Gain']:.2f}**."
                            )
                        else:
                            st.info(
                                f"💡 **{_best['Add (FA)']}** helps with **{_best['Helps With']}** "
                                "but is a lateral move overall — worth it if you need that specific category."
                            )

                        # Secondary callout: any roster player who is net-negative and expendable
                        _neg_roster = [
                            p for p in my_team.roster
                            if fg_roto_value(p) < -0.5
                            and getattr(p, "injuryStatus", "ACTIVE") not in ("INJURY_RESERVE",)
                        ]
                        if _neg_roster:
                            _neg_names = ", ".join(
                                f"**{p.name}** ({fg_roto_value(p):+.2f})"
                                for p in sorted(_neg_roster, key=fg_roto_value)[:3]
                            )
                            st.warning(
                                f"🗑️ **Easy drops**: {_neg_names} — these players have negative roto value "
                                "and are actively hurting your team. Consider replacing them first."
                            )

    # ════════════════════════════════════════════════════════════════════════════
    elif roto_tool == "📊 Standings Trend":
    # ════════════════════════════════════════════════════════════════════════════
        st.subheader("📊 Historical Standings Trend")
        st.caption(
            "Week-by-week cumulative roto points for every team. "
            "Are you climbing, falling, or holding steady in the standings?"
        )

        # Build per-week scores for every team from their schedule
        week_scores: dict = {}
        for t in league.teams:
            wkly = []
            for match in t.schedule:
                try:
                    ht  = getattr(match, "home_team", None)
                    at  = getattr(match, "away_team", None)
                    if   ht == t: pts = float(getattr(match, "home_final_score", 0) or 0)
                    elif at == t: pts = float(getattr(match, "away_final_score", 0) or 0)
                    else:         continue
                    # Stop accumulating once we hit an unplayed week (score = 0 after week 1)
                    if pts == 0 and wkly:
                        break
                    wkly.append(pts)
                except Exception:
                    continue
            if wkly:
                week_scores[t.team_name] = wkly

        if not week_scores:
            st.info(
                "No historical matchup data available yet — "
                "check back once a few weeks have been completed."
            )
        else:
            max_wk = max(len(v) for v in week_scores.values())

            # Build cumulative totals, padded to the same length
            cum_data: dict = {}
            for name, wkly in week_scores.items():
                running = 0.0
                cumulative = []
                for pts in wkly:
                    running += pts
                    cumulative.append(running)
                while len(cumulative) < max_wk:
                    cumulative.append(cumulative[-1] if cumulative else 0.0)
                cum_data[name] = cumulative

            trend_df = pd.DataFrame(
                cum_data,
                index=[f"Wk {i + 1}" for i in range(max_wk)],
            )

            # Highlight my team by listing it first in the column order
            my_col    = my_team.team_name
            other_cols = [c for c in trend_df.columns if c != my_col]
            ordered   = [my_col] + other_cols if my_col in trend_df.columns else list(trend_df.columns)
            st.line_chart(trend_df[ordered], height=420)

            # Summary metrics
            latest      = {name: vals[-1] for name, vals in cum_data.items()}
            ranked      = sorted(latest.items(), key=lambda x: x[1], reverse=True)
            my_pts      = latest.get(my_col, 0)
            my_rank     = next((i + 1 for i, (n, _) in enumerate(ranked) if n == my_col), None)
            leader_name, leader_pts = ranked[0]

            r_col, p_col, l_col = st.columns(3)
            if my_rank:
                r_col.metric("Your Current Rank", f"#{my_rank} of {len(ranked)}")
            p_col.metric("Your Total Roto Pts", round(my_pts, 1))
            l_col.metric(
                "League Leader",
                f"{leader_name[:14]}",
                delta=f"{round(leader_pts, 1)} pts",
            )

            # Full standings table
            st.divider()
            st.markdown("**Season standings to date:**")
            rank_rows = [
                {
                    "Rank":           f"#{i + 1}",
                    "Team":           name,
                    "Total Roto Pts": round(pts, 1),
                    "Wk Avg":         round(pts / max_wk, 1),
                    "Trend (last 3)": (
                        "📈" if (len(week_scores.get(name, [])) >= 3
                                 and week_scores[name][-1] >= week_scores[name][-3])
                        else "📉" if len(week_scores.get(name, [])) >= 3
                        else "—"
                    ),
                }
                for i, (name, pts) in enumerate(ranked)
            ]
            rank_df = pd.DataFrame(rank_rows)

            def _my_row_style(row):
                if row.get("Team", "") == my_col:
                    return ["background-color:rgba(21,101,192,0.10);font-weight:700"] * len(row)
                return [""] * len(row)

            st.dataframe(
                rank_df.style.apply(_my_row_style, axis=1),
                use_container_width=True, hide_index=True,
                column_config={
                    "Rank":           st.column_config.TextColumn("Rank",           width="small"),
                    "Team":           st.column_config.TextColumn("Team",           width="medium"),
                    "Total Roto Pts": pts_cfg("Total Roto Pts"),
                    "Wk Avg":         pts_cfg("Wk Avg"),
                    "Trend (last 3)": st.column_config.TextColumn("Trend", width="small"),
                },
            )
