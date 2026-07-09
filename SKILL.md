---
name: gold-market-dashboard
description: Research and refresh a self-contained Thai gold market HTML dashboard (XAU/USD spot, Thai gold bar 96.5% and jewelry prices, USD/THB, volatility, technical levels, a 7-day direction outlook, and full analysis — Fed policy, geopolitics, central-bank buying, institutional forecasts, market sentiment, and news), and maintain the auto-updating GitHub Pages version at waowah/gold-news. Use this skill whenever the user asks to update, refresh, build, or fix a gold price dashboard, mentions "gold dashboard", "ราคาทอง", "ทองคำแท่ง 96.5%", Thai gold prices, the gold-news repo, or wants a daily/recurring snapshot of the gold market — even if they don't say "dashboard" explicitly (e.g. "check today's gold price and update my tracker", "what's happening with gold today"). Also use it when asked to set up or change the automatic daily update.
compatibility: Requires web search access for the analysis refresh. The numbers auto-update via GitHub Actions; the analysis narrative refreshes via a daily 08:00 Cowork scheduled task.
---

You maintain a Thai gold market dashboard in the GitHub repo **waowah/gold-news**
that publishes to GitHub Pages. It has TWO refresh engines (hybrid):

1. **GitHub Actions (autonomous, tokenless)** — runs twice daily and refreshes the
   NUMBERS (Thai gold 96.5%, XAU/USD, USD/THB, volatility, 7-day odds, technicals).
   Works even when the user's computer is off.
2. **Cowork scheduled task at 08:00 Asia/Bangkok** — YOU do live web research and
   refresh the ANALYSIS narrative (Key Highlights, Fed policy, geopolitics,
   central-bank buying, institutional forecasts, sentiment, news), then push.
   Runs when the Claude/Cowork app is open.

Design rules that must always hold:
- **White theme.** Background `#f7f8fa`, cards `#ffffff`, borders `#e2e8f0`,
  text `#0f172a`/`#475569`/`#64748b`. Semantic colors darkened for contrast on
  white: gold `#b45309`, green `#15803d`, red `#b91c1c`, yellow `#a16207`,
  blue `#1d4ed8`, purple `#6d28d9`. Simple, high-contrast, easy to read. Never a
  dark theme.
- **Consistent fonts.** Body/label tiers ~12/13/14/15/16px; hero numbers 32–34px;
  header title 26px, subtitle 15px.
- **Dashboard text is Thai.** Your reasoning/searches/confirmations are English.
- **Never fabricate numbers.** If a source is down, keep the last saved value and
  flag freshness in the footer. If today's Thai price isn't announced yet
  (before ~09:00 Bangkok), use the most recent confirmed close and say so.

## Repository layout (waowah/gold-news)

```
scraper.py                    fetch + analytics + render (defensive, self-contained)
template.html                 white-theme layout, {{TOKEN}} placeholders, all 7 sections
data.json                     persisted state: prices, history, computed analytics, AND
                              the "analysis" block (narrative you refresh each morning)
index.html                    generated output (published page) — never hand-edit
requirements.txt              requests
.github/workflows/update.yml  numbers schedule: 01:00 & 08:30 UTC (08:00 & 15:30 BKK)
```

Published at `https://waowah.github.io/gold-news/` (Settings → Pages → main / root).

## THE SEVEN SECTIONS (must all stay present)

1. **ประเด็นสำคัญ / Key Highlights** — up to 6 cards (icon, headline, sub).
2. **ราคาปัจจุบัน / Prices** — Thai bar 96.5% sell/buy/spread + change, jewelry
   sell/tax-base, XAU/USD + change, USD/THB + change.
3. **วิเคราะห์เทคนิค / Technical** — XAU/USD support/resistance, London AM/PM & NY fixes.
4. **ความผันผวนและทิศทางทองคำไทย / Thai trends** — SD 95% CI (2σ) + 5-month trend
   bars; 7-day direction odds with signal pills.
5. **มุมมองสถาบัน / Institutional view** — bank price targets, market sentiment bar,
   central-bank buying summary.
6. **ปัจจัยความเสี่ยง / Risk factors** — geopolitics card, Fed card, and a "this week"
   catalysts list.
7. **ข่าวล่าสุด / Latest news** — dated headline list with colored tags.

Sections 1, 5, 6, 7 (and the highlight/Fed/geopolitics text) come from the
`analysis` block in data.json. Sections 2, 3, 4 are computed by the scraper.

## DAILY ROUTINE

**Numbers (GitHub Actions, no action needed):** cron `0 1 * * *` (08:00 BKK) and
`30 8 * * *` (15:30 BKK) + manual `workflow_dispatch`. Each run: `python scraper.py`
→ commit `index.html`+`data.json` if changed → push via built-in `GITHUB_TOKEN`
(`permissions: contents: write`; no PAT in the repo). The 08:00 run captures the
overnight spot/FX; the 15:30 run captures the finalised GTA Thai price.

**Analysis (Cowork scheduled task, 08:00 Asia/Bangkok):** when it fires, YOU:
1. Web-search credible sources (Reuters, Bloomberg, AP, World Gold Council, Fed
   releases; Thai: goldtraders.or.th, intergold.co.th, sanook money) for: the
   dominant safe-haven/geopolitical driver, Fed policy + latest US data (CPI, jobs,
   FOMC), central-bank buying (PBOC especially), institutional price targets, market
   sentiment, and 5–6 fresh headlines.
2. Update the `analysis` block in data.json (highlights, geopolitics, fed,
   central_banks, sentiment, forecasts, catalysts, news, as_of).
3. Run `python scraper.py` to re-render (it keeps the numbers, injects your narrative).
4. Commit + push. GitHub Pages rebuilds in ~1 minute.

> The scraper NEVER overwrites the `analysis` block — it only reads it. So the
> tokenless Actions runs keep your narrative intact between morning refreshes.

## ANALYTICS & SCRAPING LOGIC

**Scraping (Thai gold 96.5%) — layered fallbacks in `fetch_thai_gold()`:**
1. `https://api.chnwt.dev/thai-gold-api/latest` — JSON wrapper. Can return EMPTY
   fields early in the day — always null-check before use.
2. `https://classic.goldtraders.or.th/default.aspx` — server-rendered association
   page. The main `goldtraders.or.th` is now client-rendered Next.js (returns a
   "Loading" shell), so scrape the `classic.` host. Parse the four `NN,NNN.NN`
   numbers in order: bar sell, bar buy, jewelry sell, jewelry tax-base; grab
   `ครั้งที่ N` and the `ประจำวันที่ … เวลา …` stamp.
3. Else keep previous values, mark `source_thai = stale`.

**Spot & FX:** XAU/USD `https://api.gold-api.com/price/XAU`; USD/THB
`https://open.er-api.com/v6/latest/USD` → `rates.THB`. Both fall back to last saved.

**Fresh-data guard:** the scraper only rolls `*_prev` and appends history when it
actually fetched new data (`got_live`). Offline/failed runs re-render without
zeroing the day-over-day deltas or advancing the timestamp — important so a missed
fetch never corrupts the change figures.

**Volatility (95% CI):** population SD over the last 5 CLOSED monthly Thai bar SELL
prices; `SD% = SD/current×100`; interval = mean ± 2σ; bands <3 Low / 3–5 Moderate /
5–8 Elevated / >8 High.

**7-day odds (`direction_odds`):** start 33/34/33, adjust on THB direction, spot
daily momentum, spot vs 5-day average, weekly momentum; normalise to 100; ≤5 pills.

After any edit run `python scraper.py` and confirm: no leftover `{{TOKEN}}`, deltas
signed correctly, odds sum to 100, all 7 sections render.

## CONFIRM (English only)

Report: date/time (Bangkok); Thai bar 96.5% buy/sell/spread; jewelry; XAU/USD +
change; USD/THB; SD% + level + 95% CI; 7-day odds + key driver; the day's top
analysis takeaways (Fed, geopolitics, central banks, forecasts); source freshness;
and, if pushed, the commit + that Pages will rebuild. Note any stale/fallback feed.
Sources used.
