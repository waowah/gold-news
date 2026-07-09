# gold-news

Self-updating Thai gold market dashboard. A GitHub Actions job runs twice a day,
pulls live prices, recomputes the analytics, regenerates `index.html`, and commits
it back — so the page at GitHub Pages is always current with no manual work.

**Live page:** enable GitHub Pages (Settings → Pages → Source: `main` / root),
then it publishes at `https://waowah.github.io/gold-news/`.

## What it shows
- Thai gold bar 96.5% buy/sell + day-over-day change and spread
- Thai jewelry 96.5% sell + tax base
- XAU/USD spot and USD/THB with daily change
- Volatility: 95% confidence interval (2σ) over the last 5 closed monthly closes
- 7-day direction outlook (rule-based) with signal pills
- XAU/USD support/resistance and London/New York reference fixes

## Data sources
| Data | Source | Fallback |
|------|--------|----------|
| Thai gold 96.5% | `api.chnwt.dev` (scrapes สมาคมค้าทองคำ) | `classic.goldtraders.or.th` HTML → last saved value |
| XAU/USD spot | `api.gold-api.com` | last saved value |
| USD/THB | `open.er-api.com` | last saved value |

Any source being down never breaks a run: the scraper keeps the last known good
value and flags its freshness in the footer.

## Files
- `scraper.py` — fetch + analytics + render (defensive, self-contained)
- `template.html` — white-theme layout with `{{TOKEN}}` placeholders
- `data.json` — persisted state (prices, history, computed analytics)
- `index.html` — generated output (published page)
- `.github/workflows/update.yml` — daily schedule (01:15 & 08:30 UTC)

## Run locally
```bash
pip install -r requirements.txt
python scraper.py
```

<!-- pages redeploy 202607090949 -->
