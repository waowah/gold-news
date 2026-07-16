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
- `scripts/generate_analysis.py` — researches gold-market news via the Claude API
  (web search + structured outputs) and writes the `analysis` block in `data.json`
- `template.html` — white-theme layout with `{{TOKEN}}` placeholders
- `data.json` — persisted state: prices, history, computed analytics, and the
  narrative `analysis` block (highlights, Fed, geopolitics, central banks,
  forecasts, sentiment, catalysts, news)
- `index.html` — generated output (published page)
- `.github/workflows/update.yml` — numbers refresh, several times daily
- `.github/workflows/analysis.yml` — analysis refresh, once daily (needs the
  `ANTHROPIC_API_KEY` repo secret — see below)

## Analysis automation

`analysis.yml` runs `scripts/generate_analysis.py` once a day (09:35 Bangkok /
02:35 UTC, plus manual `workflow_dispatch`). It makes two Claude API calls:

1. **Research** — Claude with the native `web_search` tool gathers the day's
   safe-haven/geopolitical driver, Fed policy and data, central-bank buying,
   institutional price targets, sentiment, and fresh headlines.
2. **Structuring** — a second call with JSON-schema structured outputs turns
   that research into the exact `analysis` shape the dashboard renders (two
   calls are required because structured outputs and citations are mutually
   exclusive on the API).

It only ever touches the `analysis` key in `data.json` — every scraper-owned
numeric field is left untouched — then re-runs `scraper.py` to re-render
`index.html` around whatever numbers are already saved.

**Setup:** add a repo secret named `ANTHROPIC_API_KEY`
(Settings → Secrets and variables → Actions → New repository secret) with an
Anthropic API key that has access to `claude-sonnet-5`. Without this secret,
the workflow fails cleanly (no partial/bad commits) and last day's analysis
stays on the page. Each run costs a small amount of API usage (a handful of
web searches plus two model calls).

## Run locally
```bash
pip install -r requirements.txt
python scraper.py
```

<!-- pages redeploy 202607090949 -->
