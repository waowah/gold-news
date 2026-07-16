#!/usr/bin/env python3
"""
Daily gold-market ANALYSIS refresh, fully automated (no desktop app required).

Two-step Claude API call:
  1. Research step: Claude + native web_search tool gathers current
     drivers (Fed policy/data, geopolitics, central-bank buying,
     institutional price targets, sentiment, headlines) and writes a
     plain-language brief with citations.
  2. Structuring step: a second call (no tools) uses JSON-schema
     structured outputs (output_config.format) to turn that brief into
     the exact "analysis" block shape the dashboard renders. Structured
     outputs are incompatible with citations, which is why this is a
     separate call rather than one combined request.

The script only ever touches data.json's "analysis" key (+ a
meta.analysis_updated_th timestamp). All scraper-owned numeric fields
(thai_gold, spot, monthly_bar_sell, spot_history, volatility, odds,
tech) are read but never modified here -- scraper.py owns those and is
run afterwards to re-render index.html around whatever is already in
data.json.

Required env var: ANTHROPIC_API_KEY
"""
import json
import os
import sys
import subprocess
from datetime import datetime
from zoneinfo import ZoneInfo

import anthropic

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_JSON = os.path.join(REPO_ROOT, "data.json")

RESEARCH_MODEL = "claude-sonnet-5"
STRUCTURE_MODEL = "claude-sonnet-5"

VALID_COLORS = ["green", "red", "yellow", "blue", "purple", "gold"]

ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "as_of": {"type": "string", "description": "Thai-language date string, e.g. '16 ก.ค. 2569'"},
        "highlights": {
            "type": "array",
            "minItems": 4,
            "maxItems": 6,
            "items": {
                "type": "object",
                "properties": {
                    "icon": {"type": "string", "description": "A single emoji"},
                    "color": {"type": "string", "enum": VALID_COLORS},
                    "tag": {"type": "string", "description": "Thai headline, 1 sentence"},
                    "sub": {"type": "string", "description": "Thai supporting detail, 1 sentence"},
                },
                "required": ["icon", "color", "tag", "sub"],
                "additionalProperties": False,
            },
        },
        "geopolitics": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Thai title, 1 sentence"},
                "text": {"type": "string", "description": "Thai narrative paragraph, 3-6 sentences"},
            },
            "required": ["title", "text"],
            "additionalProperties": False,
        },
        "fed": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Thai title, 1 sentence"},
                "text": {"type": "string", "description": "Thai narrative paragraph, 3-6 sentences, may use <b> tags around key figures"},
            },
            "required": ["title", "text"],
            "additionalProperties": False,
        },
        "central_banks": {
            "type": "string",
            "description": "Thai narrative paragraph on central-bank gold buying (PBOC etc.), may use <b> tags around key figures",
        },
        "sentiment": {
            "type": "object",
            "properties": {
                "bull": {"type": "integer"},
                "neutral": {"type": "integer"},
                "bear": {"type": "integer"},
            },
            "required": ["bull", "neutral", "bear"],
            "additionalProperties": False,
            "description": "Three integers that should sum to 100",
        },
        "forecasts": {
            "type": "array",
            "minItems": 5,
            "maxItems": 9,
            "items": {
                "type": "object",
                "properties": {
                    "house": {"type": "string", "description": "Bank/research house name"},
                    "target": {"type": "string", "description": "Price target, e.g. '$4,500'"},
                    "horizon": {"type": "string", "description": "Thai text: timeframe + context/date of the call"},
                },
                "required": ["house", "target", "horizon"],
                "additionalProperties": False,
            },
        },
        "catalysts": {
            "type": "array",
            "minItems": 3,
            "maxItems": 5,
            "items": {
                "type": "object",
                "properties": {
                    "color": {"type": "string", "enum": VALID_COLORS},
                    "tag": {"type": "string", "description": "Short Thai category label, e.g. 'Fed'"},
                    "text": {"type": "string", "description": "Thai sentence describing the upcoming catalyst"},
                },
                "required": ["color", "tag", "text"],
                "additionalProperties": False,
            },
        },
        "news": {
            "type": "array",
            "minItems": 4,
            "maxItems": 6,
            "items": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "Thai date string, e.g. '15 ก.ค. 2569'"},
                    "color": {"type": "string", "enum": VALID_COLORS},
                    "tag": {"type": "string", "description": "Short Thai category label"},
                    "text": {"type": "string", "description": "Thai headline sentence"},
                },
                "required": ["date", "color", "tag", "text"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["as_of", "highlights", "geopolitics", "fed", "central_banks", "sentiment", "forecasts", "catalysts", "news"],
    "additionalProperties": False,
}


def now_bangkok():
    return datetime.now(ZoneInfo("Asia/Bangkok"))


def thai_date_str(dt):
    thai_months = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
                   "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
    return f"{dt.day} {thai_months[dt.month - 1]} {dt.year + 543}"


def load_current_numbers():
    """Read the scraper-owned numeric fields so the research/structuring
    prompts can reference today's actual price levels for context."""
    with open(DATA_JSON, "r", encoding="utf-8") as f:
        d = json.load(f)
    return {
        "thai_gold": d.get("thai_gold", {}),
        "spot": d.get("spot", {}),
        "meta": d.get("meta", {}),
    }


def run_research(client, today_str, numbers):
    prompt = f"""Today is {today_str} (Asia/Bangkok). Current reference prices from our own \
dashboard (may be a few hours old): XAU/USD spot {numbers['spot'].get('xau_usd')}, \
USD/THB {numbers['spot'].get('usd_thb')}, Thai gold bar 96.5% sell {numbers['thai_gold'].get('bar_sell')} / \
buy {numbers['thai_gold'].get('bar_buy')} THB.

Research today's gold market for a Thai retail-investor dashboard. Search credible sources \
(Reuters, Bloomberg, AP, CNBC, World Gold Council, Federal Reserve releases, and Thai sources \
such as goldtraders.or.th, intergold.co.th, sanook money) and gather:

1. The dominant safe-haven / geopolitical driver right now.
2. Fed policy stance and the latest relevant US economic data (CPI, PPI, jobs, FOMC statements, \
   any Fed official speeches), and how gold reacted.
3. Central-bank gold buying, especially PBOC (China) -- most recent monthly figures if available.
4. Institutional price targets/forecasts for gold from major banks (JPMorgan, Goldman Sachs, \
   HSBC, Bank of America, Morgan Stanley, UBS, Deutsche Bank, Metals Focus, etc.), noting the \
   date and direction of any recent revisions.
5. Overall market sentiment (bullish/neutral/bearish) and ETF flow trends.
6. 5-6 fresh, dated headlines from the last few days.

Write a thorough plain-language research brief in English covering all six points above. Be \
specific: include exact figures, percentages, dates, and named sources/institutions wherever you \
find them. Do not fabricate numbers -- if something is unclear or unavailable, say so rather than \
guessing. This brief will be used as the sole source material for another process that writes a \
Thai-language dashboard, so make sure every number that should appear on the dashboard is stated \
clearly and unambiguously in your brief."""

    response = client.messages.create(
        model=RESEARCH_MODEL,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 15}],
    )

    brief_parts = [block.text for block in response.content if block.type == "text"]
    brief = "\n\n".join(brief_parts).strip()
    if not brief:
        raise RuntimeError("Research step returned no text content")
    return brief


def run_structuring(client, today_str, brief):
    system = """You turn an English gold-market research brief into the Thai-language "analysis" \
block for a gold price dashboard. Write in natural, professional Thai financial-news style \
(the kind used by Thai gold trading sites and financial news outlets). Use <b>...</b> sparingly \
around key figures inside the "fed" and "central_banks" text fields only, matching the existing \
dashboard's style. Never invent numbers that are not in the brief -- if the brief lacks a figure, \
write around it in more general terms rather than making one up. The three "sentiment" fields \
(bull, neutral, bear) must be integers that sum to exactly 100."""

    user = f"""Today's date (Thai format) is: {today_str}

Research brief:
---
{brief}
---

Produce the analysis block as JSON matching the required schema. Use "as_of" = "{today_str}". \
Pick appropriate emoji icons and colors (green/red/yellow/blue/purple/gold) per item, following \
the convention that green = positive/bullish for gold, red = risk/negative or hawkish Fed news, \
yellow = institutional/forecast news, blue = Fed/monetary policy, purple = central-bank buying, \
gold = general gold-price moves."""

    response = client.messages.create(
        model=STRUCTURE_MODEL,
        max_tokens=4096,
        messages=[{"role": "user", "content": user}],
        system=system,
        output_config={"format": {"type": "json_schema", "schema": ANALYSIS_SCHEMA}},
    )

    text = response.content[0].text
    return json.loads(text)


def validate_and_normalize(analysis):
    required_top = ["as_of", "highlights", "geopolitics", "fed", "central_banks",
                     "sentiment", "forecasts", "catalysts", "news"]
    missing = [k for k in required_top if k not in analysis]
    if missing:
        raise ValueError(f"Structured output missing keys: {missing}")

    if not analysis["highlights"] or not analysis["forecasts"] or not analysis["news"]:
        raise ValueError("Structured output has empty highlights/forecasts/news list")

    sent = analysis["sentiment"]
    total = sent.get("bull", 0) + sent.get("neutral", 0) + sent.get("bear", 0)
    if total != 100:
        # Normalize by adjusting "neutral" to absorb the rounding difference,
        # rather than failing the whole run over a +/-1-2pp mismatch.
        diff = 100 - total
        sent["neutral"] = sent.get("neutral", 0) + diff
        if sent["neutral"] < 0:
            raise ValueError(f"Sentiment values can't be normalized to 100: {sent}")

    return analysis


def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY is not set", file=sys.stderr)
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    dt = now_bangkok()
    today_str = thai_date_str(dt)
    print(f"[generate_analysis] Running for {today_str} ({dt.isoformat()})")

    numbers = load_current_numbers()

    print("[generate_analysis] Step 1/2: researching with web search...")
    brief = run_research(client, today_str, numbers)
    print(f"[generate_analysis] Research brief: {len(brief)} chars")

    print("[generate_analysis] Step 2/2: structuring into analysis JSON...")
    analysis = run_structuring(client, today_str, brief)
    analysis = validate_and_normalize(analysis)

    with open(DATA_JSON, "r", encoding="utf-8") as f:
        d = json.load(f)

    d["analysis"] = analysis
    d.setdefault("meta", {})["analysis_updated_th"] = f"{today_str} เวลา {dt.strftime('%H:%M')} น."

    with open(DATA_JSON, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print("[generate_analysis] data.json analysis block updated. Re-rendering with scraper.py...")
    result = subprocess.run([sys.executable, os.path.join(REPO_ROOT, "scraper.py")],
                             cwd=REPO_ROOT, capture_output=True, text=True)
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        sys.exit(1)

    print("[generate_analysis] Done.")


if __name__ == "__main__":
    main()
