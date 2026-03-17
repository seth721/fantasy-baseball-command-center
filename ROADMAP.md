# Fantasy Baseball Command Center — Roadmap

A rotisserie fantasy baseball management tool built for serious players who want
data-driven decisions without switching between five different websites.

---

## ✅ Currently Built

### 🏢 Front Office (Daily Dashboard)
- **Weather Forecast Cards** — Visual outlook for weekly matchup and season standing
- **Vin Scully Daily Quote** — Rotates every day
- **This Day in MLB History** — Date-based historical facts
- **Baseball Spirit Animal of the Day** — Daily MiLB animal-named team feature
- **Matchup Pulse** — Live category-by-category W/L/T breakdown
- **Roster Alerts** — Injuries, IL players, and players needing attention
- **Best FA Adds Right Now** — Targeted at your losing categories with drop suggestions
- **Two-Start FA Pitchers** — Free agent SPs with two confirmed starts this week
- **Your Starters Today** — Which of your pitchers are on the mound today
- **Hot & Cold Tracker** — Players over/underperforming projections by 20%+
- **Season Standing Snapshot** — Where you rank across all roto categories
- **Category Report Card** — Visual rank tiles with progress bars for all 10 categories
- **Your Action Plan** — Prioritized big/medium/small moves to improve standing

### 📋 Lineup Optimizer (Tab 1)
- Full roster table with roto value, WAR, letter grades, and heat index
- Three letter grades per player: 2025 season, 2026 YTD, 2026 projected
- Category contribution indicators (Helps / Hurts)

### 🔍 Waiver Wire (Tab 2)
- Full free agent pool with roto value and projections
- **Roto Upgrade Targets** — FAs ranked by how much roto value you'd gain
- Drop candidate suggestion for each upgrade target

### 📊 Team Overview (Tab 3)
- Roto points for/against
- Projected Category Standings — full league comparison across all 10 cats

### 🔄 Trade Analyzer (Tab 4)
- Side-by-side roto value comparison
- Per-category impact table showing exactly what you gain/lose
- Smart trade suggestions

### 🪑 Start / Sit (Tab 5)
- Projected roto value comparison for lineup decisions

### 🌊 Streaming Pitchers (Tab 6)
- Available SPs ranked by roto value
- ERA/WHIP risk flags

### 📰 Player News (Tab 7)
- ESPN injury and transaction news

### ⚾ Games (Tab 8)
- Live MLB scores and schedules

### 🎯 Roto Tools (Tab 9)
- **Two-Start Pitcher Tracker** — Which SPs have two starts this week
- **Category Gap Tracker** — How far you are from moving up or being caught
- **ERA/WHIP Runway** — FA SP impact simulator on your team ERA/WHIP
- **Pace Tracker** — Who is on pace vs their projections
- **Closer Monitor** — Job security tiers for all closers
- **Starts Maximizer** — Weekly pitcher starts and hitter schedule tracker
- **Punt Advisor** — Single and two-category punt analysis
- **Buy Low / Sell High** — Over/underperformers vs projections
- **Emergency Replacements** — Best available FAs when a player hits the IL
- **Matchup Breakdown** — Category-by-category analysis with FA suggestions
- **Standings Trend** — Historical roto points chart over the season

### 🎨 Design & UX
- Custom blue gradient theme throughout
- Pill-style tab navigation
- Unified section headers with left accent bars
- Weather emoji forecast cards
- Category report card tiles with progress bars
- Hot/cold player streak cards with accent bars and position badges
- Page fade-in animation
- Empty state cards
- Terms & Conditions with full data attribution
- Footer disclaimer on every page

---

## 🚧 In Progress / Known Issues
- Player headshots dependent on ESPN CDN availability
- Two-start pitcher data limited to ESPN's probable starter window (a few days out)
- Pace Tracker requires sufficient games played for meaningful data early in season

---

## 🗺️ Planned Features

### 🔐 User Authentication System *(High Priority)*
Full username/password login so multiple users can access a shared deployment.
Each user's ESPN credentials stored securely to their own account.
Would enable a true multi-user SaaS product without each person needing to
deploy their own copy.
- Self-registration and login flow
- Per-user credential storage (encrypted)
- Session persistence across visits
- Password reset via email

### 📱 Mobile Optimization
The app is currently optimized for desktop. A mobile-friendly layout would
make it much more useful on game day when you're checking your phone.

### 🔔 Push Notifications / Email Alerts
Daily morning email summary of your Front Office briefing — injury alerts,
two-start pitchers this week, and your top recommended FA add. No need to
open the app to get the most important info.

### 📈 FAAB Budget Tracker
For leagues using Free Agent Acquisition Budget bidding — track remaining
budget, get bid recommendations based on a player's roto value, and see
how your budget compares to the rest of the league.

### 🏟️ Ballpark & Weather Impact
Factor in hitter-friendly vs pitcher-friendly ballparks and game-day weather
(wind speed/direction, temperature) into streaming recommendations.

### 📊 Dynasty / Keeper Mode
Long-term player valuation for dynasty and keeper leagues — prospect rankings,
age curves, and multi-year projections beyond the current season.

### 🤝 League-Wide Trade Market
See all trade offers currently being discussed across your league, not just
your own. Identify league-wide market inefficiencies.

### 🧠 AI-Powered Trade Negotiation Assistant
Natural language trade analysis — describe a trade in plain English and get
a plain English breakdown of whether to accept, counter, or decline.

---

## 📬 Feedback & Contributions
Found a bug or have a feature request? Open an issue or drop a comment.
This is an independent project built for the fantasy baseball community.

---

*Built with Python, Streamlit, ESPN Fantasy API, and FanGraphs projections.*
*Not affiliated with ESPN, MLB, FanGraphs, or the MLBPA.*
*For entertainment and reference purposes only.*
