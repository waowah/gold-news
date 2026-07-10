#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gold News dashboard builder.

Runs daily in GitHub Actions:
  1. Fetch XAU/USD spot, USD/THB, and Thai gold 96.5% prices from live sources.
  2. Fall back gracefully (previous data.json values) when a source is down.
  3. Recompute analytics: daily changes, 5-month volatility (95% CI, 2 sigma),
     and a rule-based 7-day direction outlook.
  4. Render a self-contained white-theme index.html.
  5. Persist state back to data.json.

The script is intentionally defensive: any single source failing never crashes
the run — it just keeps the last known good value and flags it in the footer.
"""

import json
import os
import re
import sys
import datetime as dt
from math import sqrt
from zoneinfo import ZoneInfo

try:
    import requests
except ImportError:  # allow offline render from existing data.json
    requests = None

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE, "data.json")
OUT_FILE = os.path.join(BASE, "index.html")
BKK = ZoneInfo("Asia/Bangkok")

TH_MONTHS = ["", "ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
             "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
UA = {"User-Agent": "Mozilla/5.0 (gold-news dashboard bot)"}


# ---------------------------------------------------------------- fetch layer
def get_json(url, timeout=20):
    if requests is None:
        return None
    try:
        r = requests.get(url, headers=UA, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"[warn] json fetch failed {url}: {e}", file=sys.stderr)
        return None


def get_text(url, timeout=25):
    if requests is None:
        return None
    try:
        r = requests.get(url, headers=UA, timeout=timeout)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or "utf-8"
        return r.text
    except Exception as e:
        print(f"[warn] text fetch failed {url}: {e}", file=sys.stderr)
        return None


def fetch_spot():
    """XAU/USD spot price in USD/oz, with a staleness guard + fallback source.

    gold-api.com occasionally serves a cached price whose `updatedAt` is a day or
    more old — that would silently freeze the dashboard. So we only trust it when
    its timestamp is within ~30h of now; otherwise we fall back to goldprice.org."""
    d = get_json("https://api.gold-api.com/price/XAU")
    if d and d.get("price"):
        fresh = True
        ts = d.get("updatedAt")
        if ts:
            try:
                upd = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
                age_h = (dt.datetime.now(dt.timezone.utc) - upd).total_seconds() / 3600
                fresh = age_h <= 30
            except Exception:
                fresh = True
        if fresh:
            return round(float(d["price"]), 2), "gold-api.com"
        print("[warn] gold-api price is stale; trying fallback", file=sys.stderr)

    # fallback: goldprice.org live rates
    g = get_json("https://data-asg.goldprice.org/dbXRates/USD")
    try:
        px = float(g["items"][0]["xauPrice"])
        if px > 0:
            return round(px, 2), "goldprice.org"
    except Exception:
        pass
    return None, None


def fetch_usdthb():
    d = get_json("https://open.er-api.com/v6/latest/USD")
    if d and d.get("rates", {}).get("THB"):
        return round(float(d["rates"]["THB"]), 4), "er-api.com"
    return None, None


def _num(s):
    return float(re.sub(r"[^\d.]", "", s)) if s else None


def fetch_thai_gold():
    """Return dict(bar_sell, bar_buy, jewelry_sell, jewelry_buy, round, time_th)
    or None. Tries the community JSON API first, then the classic association
    site (server-rendered), which is the canonical source."""

    # 1) community JSON API (scrapes goldtraders.or.th)
    d = get_json("https://api.chnwt.dev/thai-gold-api/latest")
    if d and d.get("status") == "success":
        p = d["response"]["price"]
        bar, jew = p.get("gold_bar", {}), p.get("gold", {})
        bs, bb = _num(bar.get("sell")), _num(bar.get("buy"))
        js, jb = _num(jew.get("sell")), _num(jew.get("buy"))
        if bs and bb:
            return {"bar_sell": bs, "bar_buy": bb,
                    "jewelry_sell": js, "jewelry_buy": jb,
                    "time_th": (d["response"].get("update_date", "") + " " +
                                d["response"].get("update_time", "")).strip(),
                    "round": "", "source": "chnwt-api"}

    # 2) classic association site (ASP.NET, server-rendered)
    html = get_text("https://classic.goldtraders.or.th/default.aspx")
    if html:
        # collapse tags to isolate the price block, then pull numbers in order.
        # Order on the page: bar sell, bar buy, jewelry sell, jewelry tax-base.
        def label_val(label):
            m = re.search(label + r".{0,400?}?([\d,]{5,9}\.\d{2})", html, re.S)
            return _num(m.group(1)) if m else None

        nums = re.findall(r"(\d{2,3},\d{3}\.\d{2})", html)
        vals = [_num(x) for x in nums]
        rnd = ""
        rm = re.search(r"ครั้งที่\s*(\d+)", html)
        if rm:
            rnd = rm.group(1)
        tm = re.search(r"ประจำวันที่\s*([\d/]+\s*เวลา\s*[\d:]+\s*น\.)", html)
        time_th = tm.group(1) if tm else ""
        if len(vals) >= 4:
            return {"bar_sell": vals[0], "bar_buy": vals[1],
                    "jewelry_sell": vals[2], "jewelry_buy": vals[3],
                    "time_th": time_th, "round": rnd, "source": "goldtraders-classic"}
    return None


# ---------------------------------------------------------------- analytics
def stdev_ci(monthly):
    """95% confidence interval (2 sigma, population SD) over the last 5 CLOSED
    monthly Thai gold-bar sell prices."""
    closed = [m["price"] for m in monthly if not m.get("current")][-5:]
    if len(closed) < 2:
        closed = [m["price"] for m in monthly][-5:]
    n = len(closed)
    mean = sum(closed) / n
    sd = sqrt(sum((p - mean) ** 2 for p in closed) / n)
    current = next((m["price"] for m in monthly if m.get("current")),
                   monthly[-1]["price"])
    sd_pct = round(sd / current * 100, 1)
    lo, hi = mean - 2 * sd, mean + 2 * sd
    if sd_pct < 3:
        level = "ต่ำ (Low)"
    elif sd_pct < 5:
        level = "ปานกลาง (Moderate)"
    elif sd_pct < 8:
        level = "ค่อนข้างสูง (Elevated)"
    else:
        level = "สูง (High)"
    vs = round(sd_pct - 3.0, 1)  # vs Thai gold ~3% historical norm
    return {"sd_pct": sd_pct, "mean": round(mean), "lo": round(lo),
            "hi": round(hi), "level": level, "vs_norm": vs, "closed": closed}


def direction_odds(spot_hist, usd_thb, usd_thb_prev, xau, xau_prev):
    """Rule-based 7-day outlook. Starts neutral, adjusts on the signals the
    scraper can measure reliably, then normalises to 100%."""
    up, side, down = 33.0, 34.0, 33.0
    signals = []

    def shift(bucket, amt, other_a, other_b):
        nonlocal up, side, down
        if bucket == "up":
            up += amt
        else:
            down += amt
        # subtract equally from the two other buckets
        for b in (other_a, other_b):
            if b == "up":
                up -= amt / 2
            elif b == "side":
                side -= amt / 2
            else:
                down -= amt / 2

    # THB direction: weaker baht -> higher local gold (bullish for THB gold)
    if usd_thb and usd_thb_prev:
        if usd_thb > usd_thb_prev * 1.001:
            shift("up", 8, "side", "down"); signals.append(("บาทอ่อนค่า หนุนทองบาท", "green"))
        elif usd_thb < usd_thb_prev * 0.999:
            shift("down", 8, "side", "up"); signals.append(("บาทแข็งค่า กดทองบาท", "red"))

    # spot daily momentum
    if xau and xau_prev:
        if xau > xau_prev:
            shift("up", 6, "side", "down"); signals.append(("ทองโลกขึ้นรายวัน", "green"))
        elif xau < xau_prev:
            shift("down", 6, "side", "up"); signals.append(("ทองโลกลงรายวัน", "red"))

    # spot vs its own recent average (once we have enough history)
    closes = [h["xau"] for h in spot_hist if h.get("xau")]
    if len(closes) >= 5:
        sma = sum(closes[-5:]) / 5
        if xau and xau > sma:
            shift("up", 5, "side", "down"); signals.append(("ยืนเหนือค่าเฉลี่ย 5 วัน", "green"))
        elif xau and xau < sma:
            shift("down", 5, "side", "up"); signals.append(("หลุดค่าเฉลี่ย 5 วัน", "red"))

    # weekly momentum (~5 sessions back)
    if len(closes) >= 5 and xau:
        wk = closes[-5]
        if xau > wk * 1.005:
            shift("up", 5, "side", "down"); signals.append(("โมเมนตัมรายสัปดาห์บวก", "green"))
        elif xau < wk * 0.995:
            shift("down", 5, "side", "up"); signals.append(("โมเมนตัมรายสัปดาห์ลบ", "red"))

    vals = [max(0.0, v) for v in (up, side, down)]
    tot = sum(vals) or 1
    up, side, down = (round(v / tot * 100) for v in vals)
    diff = 100 - (up + side + down)
    # fix rounding drift on the largest bucket
    idx = [up, side, down].index(max(up, side, down))
    if idx == 0:
        up += diff
    elif idx == 1:
        side += diff
    else:
        down += diff

    if up > down and up >= side:
        summary = "สัญญาณ 7 วันเอียงขึ้น — ปัจจัยหลักคือทิศทางค่าเงินบาทและโมเมนตัมทองโลก"
    elif down > up and down >= side:
        summary = "สัญญาณ 7 วันเอียงลง — แรงกดดันจากค่าเงินบาท/ทองโลกอ่อนตัว"
    else:
        summary = "สัญญาณ 7 วันทรงตัว — ยังไม่มีปัจจัยชี้ทิศทางชัดเจน รอจังหวะ"
    return {"up": up, "side": side, "down": down,
            "summary": summary, "signals": signals[:5]}


def tech_levels(xau, spot_hist):
    closes = [h["xau"] for h in spot_hist if h.get("xau")] or [xau]
    hi, lo = max(closes + [xau]), min(closes + [xau])
    r1 = int(round((xau + 25) / 25) * 25)
    r2 = int(round((hi + 50) / 25) * 25)
    s1 = int(round((xau - 25) / 25) * 25)
    s2 = int(round((lo - 25) / 25) * 25)
    return {"r2": max(r2, r1 + 25), "r1": r1, "s1": s1, "s2": min(s2, s1 - 25),
            "range_lo": int(lo), "range_hi": int(hi)}


# ---------------------------------------------------------------- render
def fmt(n):
    return f"{int(round(n)):,}"


def sign_str(delta, suffix=""):
    if delta > 0:
        return f"+{fmt(abs(delta))}{suffix}", "green"
    if delta < 0:
        return f"-{fmt(abs(delta))}{suffix}", "red"
    return f"0{suffix}", "flat"


def render(state, tmpl):
    tg, sp = state["thai_gold"], state["spot"]
    vol, od = state["volatility"], state["odds"]
    tech = state["tech"]
    meta = state["meta"]

    bar_delta = tg["bar_sell"] - tg.get("bar_sell_prev", tg["bar_sell"])
    bar_txt, bar_cls = sign_str(bar_delta)
    xau_delta = round(sp["xau_usd"] - sp.get("xau_usd_prev", sp["xau_usd"]), 2)
    xau_pct = (xau_delta / sp["xau_usd"] * 100) if sp["xau_usd"] else 0
    xau_txt = ("+" if xau_delta >= 0 else "-") + f"${abs(xau_delta):,.2f} ({xau_delta/ (sp['xau_usd'] or 1)*100:+.2f}%)"
    xau_cls = "green" if xau_delta >= 0 else "red"
    thb_delta = round(sp["usd_thb"] - sp.get("usd_thb_prev", sp["usd_thb"]), 2)
    thb_txt = f"{sp['usd_thb']:.2f}"
    thb_sub = ("บาทอ่อนค่า" if thb_delta > 0 else "บาทแข็งค่า" if thb_delta < 0 else "ทรงตัว") + f" ({thb_delta:+.2f})"
    thb_cls = "green" if thb_delta > 0 else "red" if thb_delta < 0 else "flat"
    spread = tg["bar_sell"] - tg["bar_buy"]

    # monthly trend bars
    months = state["monthly_bar_sell"]
    maxp = max(m["price"] for m in months)
    bars = ""
    for m in months:
        h = int(m["price"] / maxp * 74) + 6
        star = " ★" if m.get("current") else ""
        cur = " tb-cur" if m.get("current") else ""
        bars += (f'<div class="tb"><div class="tb-v">{fmt(m["price"])}</div>'
                 f'<div class="tb-bar{cur}" style="height:{h}px"></div>'
                 f'<div class="tb-l">{m["label"]}{star}</div></div>')

    # odds bars
    def obar(w, color):
        return f'width:{w}%;background:{color}'
    C = {"green": "#15803d", "red": "#b91c1c", "gray": "#94a3b8"}

    pills = ""
    pmap = {"green": ("#15803d", "#dcfce7"), "red": ("#b91c1c", "#fee2e2"),
            "yellow": ("#a16207", "#fef9c3"), "blue": ("#1d4ed8", "#dbeafe")}
    for label, color in od["signals"]:
        fg, bg = pmap.get(color, pmap["blue"])
        pills += f'<span class="pill" style="color:{fg};background:{bg}">{label}</span>'
    if not pills:
        pills = '<span class="pill" style="color:#475569;background:#f1f5f9">รอสัญญาณเพิ่มเติม</span>'

    vs_txt = (f'+{abs(vol["vs_norm"])}pp สูงกว่าปกติ' if vol["vs_norm"] > 0
              else f'{vol["vs_norm"]}pp ต่ำกว่าปกติ' if vol["vs_norm"] < 0
              else 'เท่ากับค่าปกติ')

    # ---- analysis / narrative sections (from data.json["analysis"]) ----
    an = state.get("analysis", {})
    SOFT = {"green": "#dcfce7", "red": "#fee2e2", "yellow": "#fef9c3",
            "blue": "#dbeafe", "purple": "#ede9fe", "gold": "#fef3c7"}
    FG = {"green": "#15803d", "red": "#b91c1c", "yellow": "#a16207",
          "blue": "#1d4ed8", "purple": "#6d28d9", "gold": "#b45309"}

    highlights_html = ""
    for h in an.get("highlights", []):
        highlights_html += (
            f'<div class="hl"><div class="hl-ic">{h.get("icon","•")}</div>'
            f'<div><div class="hl-tag">{h.get("tag","")}</div>'
            f'<div class="hl-sub">{h.get("sub","")}</div></div></div>')
    if not highlights_html:
        highlights_html = '<div class="hl"><div class="hl-sub">รอข้อมูลบทวิเคราะห์</div></div>'

    forecasts_html = ""
    for f in an.get("forecasts", []):
        forecasts_html += (
            f'<div class="fc"><div><div class="fc-house">{f.get("house","")}</div>'
            f'<div class="fc-h">{f.get("horizon","")}</div></div>'
            f'<div class="fc-t">{f.get("target","")}</div></div>')

    catalysts_html = ""
    for c in an.get("catalysts", []):
        color = c.get("color", "yellow")
        catalysts_html += (
            f'<div class="li"><span class="li-badge" '
            f'style="color:{FG.get(color,FG["yellow"])};background:{SOFT.get(color,SOFT["yellow"])}">'
            f'{c.get("tag","")}</span><div class="li-txt">{c.get("text","")}</div></div>')

    news_html = ""
    for nw in an.get("news", []):
        color = nw.get("color", "blue")
        news_html += (
            f'<div class="li"><span class="li-badge" '
            f'style="color:{FG.get(color,FG["blue"])};background:{SOFT.get(color,SOFT["blue"])}">'
            f'{nw.get("tag","")}</span><div><div class="li-txt">{nw.get("text","")}</div>'
            f'<div class="li-date">{nw.get("date","")}</div></div></div>')

    sent = an.get("sentiment", {"bull": 60, "neutral": 25, "bear": 15})
    geo = an.get("geopolitics", {})
    fed = an.get("fed", {})

    src_note = "ข้อมูลสด" if meta.get("source_thai") not in ("seed", "stale") else \
               ("ค่าล่าสุดที่บันทึกไว้ (แหล่งข้อมูลไม่ตอบสนอง)" if meta.get("source_thai") == "stale"
                else "ค่าเริ่มต้น (seed)")

    repl = {
        "{{UPDATED}}": meta["updated_th"],
        "{{GTA_TIME}}": meta.get("gta_time_th", "-"),
        "{{BAR_SELL}}": fmt(tg["bar_sell"]),
        "{{BAR_BUY}}": fmt(tg["bar_buy"]),
        "{{BAR_DELTA}}": bar_txt,
        "{{BAR_DELTA_CLS}}": bar_cls,
        "{{SPREAD}}": fmt(spread),
        "{{JEW_SELL}}": fmt(tg["jewelry_sell"]),
        "{{JEW_BUY}}": fmt(tg["jewelry_buy"]),
        "{{XAU}}": f'{sp["xau_usd"]:,.2f}',
        "{{XAU_DELTA}}": xau_txt,
        "{{XAU_CLS}}": xau_cls,
        "{{THB}}": thb_txt,
        "{{THB_SUB}}": thb_sub,
        "{{THB_CLS}}": thb_cls,
        "{{LDN_AM}}": f'{sp.get("london_am",0):,.2f}',
        "{{LDN_PM}}": f'{sp.get("london_pm",0):,.2f}',
        "{{NY}}": f'{sp.get("newyork",0):,.2f}',
        "{{SD_PCT}}": f'±{vol["sd_pct"]}%',
        "{{SD_LEVEL}}": vol["level"],
        "{{SD_MEAN}}": fmt(vol["mean"]),
        "{{SD_LO}}": fmt(vol["lo"]),
        "{{SD_HI}}": fmt(vol["hi"]),
        "{{SD_VS}}": vs_txt,
        "{{TREND_BARS}}": bars,
        "{{ODDS_UP}}": str(od["up"]),
        "{{ODDS_SIDE}}": str(od["side"]),
        "{{ODDS_DOWN}}": str(od["down"]),
        "{{ODDS_UP_BAR}}": obar(od["up"], C["green"]),
        "{{ODDS_SIDE_BAR}}": obar(od["side"], C["gray"]),
        "{{ODDS_DOWN_BAR}}": obar(od["down"], C["red"]),
        "{{ODDS_SUMMARY}}": od["summary"],
        "{{PILLS}}": pills,
        "{{R2}}": fmt(tech["r2"]),
        "{{R1}}": fmt(tech["r1"]),
        "{{S1}}": fmt(tech["s1"]),
        "{{S2}}": fmt(tech["s2"]),
        "{{FOOTER}}": meta["updated_th"],
        "{{SRC_NOTE}}": src_note,
        "{{SRC_SPOT}}": meta.get("source_spot", "-"),
        "{{SRC_THAI}}": meta.get("source_thai", "-"),
        "{{ANALYSIS_ASOF}}": an.get("as_of", meta.get("updated_th", "")),
        "{{ANALYSIS_UPDATED}}": (meta.get("analysis_updated_th")
                                 or an.get("as_of") or "ยังไม่ได้รีเฟรช"),
        "{{HIGHLIGHTS}}": highlights_html,
        "{{FORECASTS}}": forecasts_html or '<div class="fc-h">รอข้อมูลเป้าราคา</div>',
        "{{CATALYSTS}}": catalysts_html or '<div class="li-txt">รอข้อมูลปัจจัย</div>',
        "{{NEWS}}": news_html or '<div class="li-txt">รอข่าวล่าสุด</div>',
        "{{SENT_BULL}}": str(sent.get("bull", 60)),
        "{{SENT_NEU}}": str(sent.get("neutral", 25)),
        "{{SENT_BEAR}}": str(sent.get("bear", 15)),
        "{{CB_TEXT}}": an.get("central_banks", ""),
        "{{GEO_TITLE}}": geo.get("title", "สถานการณ์ภูมิรัฐศาสตร์"),
        "{{GEO_TEXT}}": geo.get("text", ""),
        "{{FED_TITLE}}": fed.get("title", "นโยบาย Fed"),
        "{{FED_TEXT}}": fed.get("text", ""),
    }
    html = tmpl
    for k, v in repl.items():
        html = html.replace(k, str(v))
    return html


# ---------------------------------------------------------------- main
def load_state():
    with open(DATA_FILE, encoding="utf-8") as f:
        return json.load(f)


def main():
    state = load_state()
    now = dt.datetime.now(BKK)
    today = now.date().isoformat()

    tg, sp = state["thai_gold"], state["spot"]
    new_day = state["meta"].get("updated_date") != today

    # --- fetch spot / FX (only overwrite when we actually get fresh data) ---
    xau, src_spot = fetch_spot()
    thb, src_thb = fetch_usdthb()
    live_spot = xau is not None
    live_thb = thb is not None

    if live_spot:
        if new_day:
            sp["xau_usd_prev"] = sp["xau_usd"]
        sp["xau_usd"] = xau
    if live_thb:
        if new_day:
            sp["usd_thb_prev"] = sp["usd_thb"]
        sp["usd_thb"] = thb
    xau, thb = sp["xau_usd"], sp["usd_thb"]  # effective values for analytics

    # --- fetch Thai gold ---
    thai = fetch_thai_gold()
    if thai:
        src_thai = thai["source"]
        # roll previous close once per calendar day, only on fresh data
        if new_day:
            tg["bar_sell_prev"] = tg["bar_sell"]
            tg["bar_buy_prev"] = tg["bar_buy"]
        tg["bar_sell"], tg["bar_buy"] = thai["bar_sell"], thai["bar_buy"]
        if thai.get("jewelry_sell"):
            tg["jewelry_sell"] = thai["jewelry_sell"]
        if thai.get("jewelry_buy"):
            tg["jewelry_buy"] = thai["jewelry_buy"]
        state["meta"]["gta_round"] = thai.get("round", "")
        state["meta"]["gta_time_th"] = thai.get("time_th", "") or state["meta"].get("gta_time_th", "")
    else:
        src_thai = "stale" if state["meta"].get("source_thai") not in ("seed",) else "seed"

    got_live = live_spot or live_thb or (thai is not None)

    # --- update history + monthly series only when we have fresh data ---
    if got_live:
        hist = state.get("spot_history", [])
        row = {"date": today, "xau": xau, "thb": thb, "bar_sell": tg["bar_sell"]}
        if hist and hist[-1]["date"] == today:
            hist[-1] = row
        else:
            hist.append(row)
        state["spot_history"] = hist[-40:]

        months = state["monthly_bar_sell"]
        cur_lbl = TH_MONTHS[now.month]
        cur = next((m for m in months if m.get("current")), None)
        if cur and cur["label"] == cur_lbl:
            cur["price"] = tg["bar_sell"]
        else:
            for m in months:
                m.pop("current", None)
            months.append({"label": cur_lbl, "year": now.year + 543,
                           "price": tg["bar_sell"], "current": True})
            months[:] = months[-6:]

    hist = state.get("spot_history", [])
    months = state["monthly_bar_sell"]

    # --- analytics (recomputed every run) ---
    state["volatility"] = stdev_ci(months)
    state["odds"] = direction_odds(hist, thb, sp.get("usd_thb_prev"),
                                   xau, sp.get("xau_usd_prev"))
    state["tech"] = tech_levels(xau, hist)

    # --- meta ---
    be_year = now.year + 543
    state["meta"]["updated_iso"] = now.isoformat()
    if got_live:
        state["meta"]["updated_date"] = today
        state["meta"]["updated_th"] = (f'{now.day} {TH_MONTHS[now.month]} {be_year} '
                                       f'เวลา {now:%H:%M} น.')
        state["meta"]["source_spot"] = src_spot or "cache"
        state["meta"]["source_thai"] = src_thai
    # when offline, preserve the existing timestamps/source flags unchanged

    # --- render + persist ---
    with open(os.path.join(BASE, "template.html"), encoding="utf-8") as f:
        tmpl = f.read()
    html = render(state, tmpl)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    print(f"[ok] rendered {OUT_FILE}")
    print(f"     spot={xau} ({src_spot})  thb={thb}  thai={src_thai}  "
          f"bar_sell={tg['bar_sell']}  odds={state['odds']['up']}/"
          f"{state['odds']['side']}/{state['odds']['down']}  "
          f"SD%={state['volatility']['sd_pct']}")


if __name__ == "__main__":
    main()
