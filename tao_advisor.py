#!/usr/bin/env python3
"""
tao_advisor.py — Daily portfolio analysis: rule-based alerts + AI recommendations.

Runs continuously, fires once per day at ADVISOR_RUN_HOUR (UTC, default 8am).
Sends analysis to Telegram (or prints to console if no token set).

Usage:
  python3 tao_advisor.py
  python3 tao_advisor.py --now   # run immediately, don't wait for scheduled hour
"""

import argparse
import json
import os
import time
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY  = os.getenv("ANTHROPIC_API_KEY", "none")
COST_BASIS_USD     = float(os.getenv("COST_BASIS_USD", "0") or "0")
BOT_TOKEN          = os.getenv("TELEGRAM_BOT_TOKEN", "none")
CHAT_ID            = os.getenv("TELEGRAM_CHAT_ID", "none")
CG_KEY             = os.getenv("COINGECKO_API_KEY", "none")
ADVISOR_RUN_HOUR   = int(os.getenv("ADVISOR_RUN_HOUR", "8"))

SNAP_FILE = "/tmp/tao_latest.json"

# Target allocations: netuid -> (name, target fraction)
TARGET_ALLOC = {
    0:  ("Root → TAO.com", 0.500),
    64: ("Chutes",          0.165),
    62: ("Ridges",          0.110),
    4:  ("Targon",          0.095),
    75: ("Hippius",         0.070),
    68: ("Nova",            0.035),
    55: ("Ko/Precog",       0.025),
}

DRIFT_THRESHOLD   = 0.05   # alert if a subnet drifts 5+ percentage points from target
PROFIT_THRESHOLD  = 0.50   # alert if portfolio is up 50%+ from cost basis
DCA_THRESHOLD     = 0.10   # alert if TAO is 10%+ below cost basis


# ── Helpers ───────────────────────────────────────────────────────────────────

def log(msg):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{ts}] {msg}", flush=True)


def send_telegram(msg):
    if BOT_TOKEN == "none" or CHAT_ID == "none":
        log(f"[ADVISOR OUTPUT]\n{msg}")
        return
    # Telegram has a 4096 char limit — truncate if needed
    if len(msg) > 4000:
        msg = msg[:3990] + "\n...[truncated]"
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=10,
        )
        r.raise_for_status()
    except Exception as e:
        log(f"ERROR sending Telegram message: {e}")


def get_tao_price():
    headers = {}
    if CG_KEY and CG_KEY != "none":
        headers["x-cg-demo-api-key"] = CG_KEY
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": "bittensor", "vs_currencies": "usd"},
            headers=headers,
            timeout=10,
        )
        r.raise_for_status()
        return r.json()["bittensor"]["usd"]
    except Exception as e:
        log(f"ERROR fetching TAO price: {e}")
        return None


def load_snapshot():
    try:
        with open(SNAP_FILE) as f:
            return json.load(f)
    except FileNotFoundError:
        log(f"No snapshot found at {SNAP_FILE} — run tao_monitor.py first")
        return None
    except Exception as e:
        log(f"ERROR loading snapshot: {e}")
        return None


# ── Rule-based analysis ───────────────────────────────────────────────────────

def rule_based_analysis(snap, tao_usd):
    """Returns a list of alert strings for notable conditions."""
    alerts = []

    if not snap or not snap.get("positions"):
        return alerts

    total_usd = snap.get("total_value_usd") or 0

    # Allocation drift
    if total_usd > 0:
        for pos in snap["positions"]:
            netuid = pos.get("netuid")
            if netuid not in TARGET_ALLOC or "error" in pos:
                continue
            name, target_pct = TARGET_ALLOC[netuid]
            val = pos.get("value_usd") or 0
            actual_pct = val / total_usd
            drift = actual_pct - target_pct
            if abs(drift) >= DRIFT_THRESHOLD:
                direction = "overweight" if drift > 0 else "underweight"
                alerts.append(
                    f"⚖️ <b>Allocation drift — {name}</b>\n"
                    f"Target {target_pct*100:.0f}% → now {actual_pct*100:.0f}% "
                    f"({direction} by {abs(drift)*100:.0f}pp). Consider rebalancing."
                )

    # DCA opportunity
    if COST_BASIS_USD > 0 and tao_usd:
        drop = (COST_BASIS_USD - tao_usd) / COST_BASIS_USD
        if drop >= DCA_THRESHOLD:
            alerts.append(
                f"📉 <b>DCA opportunity</b>\n"
                f"TAO is {drop*100:.0f}% below your entry price "
                f"(${COST_BASIS_USD:.2f} → ${tao_usd:.2f}). "
                f"Worth considering adding to your position."
            )

    # Significant profit
    if COST_BASIS_USD > 0 and total_usd > 0:
        gain = (total_usd - COST_BASIS_USD) / COST_BASIS_USD
        if gain >= PROFIT_THRESHOLD:
            alerts.append(
                f"💰 <b>Significant profit — review your position</b>\n"
                f"Portfolio up {gain*100:.0f}% from your cost basis "
                f"(${COST_BASIS_USD:.2f} → ${total_usd:.2f}). "
                f"Consider whether to take partial profit or hold."
            )

    return alerts


# ── AI analysis ───────────────────────────────────────────────────────────────

def ai_analysis(snap, tao_usd):
    """Calls Claude API for a written portfolio analysis. Returns string or None."""
    if ANTHROPIC_API_KEY == "none":
        log("ANTHROPIC_API_KEY not set — skipping AI analysis")
        return None

    if not snap:
        return None

    try:
        import anthropic
    except ImportError:
        log("anthropic package not installed — run: pip3 install anthropic")
        return None

    # Build position summary
    positions_text = ""
    for pos in snap.get("positions", []):
        netuid = pos.get("netuid")
        name = pos.get("name", f"SN{netuid}")
        if "error" in pos:
            positions_text += f"- SN{netuid} {name}: ERROR fetching position\n"
        elif netuid == 0:
            positions_text += (
                f"- SN{netuid} {name}: {pos.get('stake_tao', 0):.4f} TAO staked, "
                f"value ${pos.get('value_usd', 0):.2f}\n"
            )
        else:
            positions_text += (
                f"- SN{netuid} {name}: {pos.get('stake_alpha', 0):.4f} alpha tokens, "
                f"subnet price {pos.get('price_tao', 0):.6f} TAO/alpha, "
                f"approx value ${pos.get('value_usd', 0):.2f}\n"
            )

    target_text = "\n".join(
        f"- SN{nid} {name}: target {pct*100:.0f}%"
        for nid, (name, pct) in TARGET_ALLOC.items()
    )

    cost_text = f"${COST_BASIS_USD:.2f}" if COST_BASIS_USD > 0 else "not configured"
    total_usd = snap.get("total_value_usd") or 0
    snap_time = snap.get("timestamp", "unknown")

    prompt = f"""You are a Bittensor staking portfolio analyst. Review the positions below and give a concise daily briefing.

Be practical and specific. Do not give financial advice — give observations and flag things the investor should think about.
Keep it to 4-6 bullet points, plain text only (no markdown, no asterisks).

Portfolio data (as of {snap_time}):
- TAO price: ${tao_usd:.2f} USD
- Total portfolio value: ${total_usd:.2f} USD
- Cost basis: {cost_text}

Current positions:
{positions_text}
Target allocations:
{target_text}

Cover: any notable allocation drift, subnet price trends, whether conditions favour holding vs rebalancing vs deploying more capital, and anything else worth flagging. Be direct."""

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
    except Exception as e:
        log(f"ERROR calling Claude API: {e}")
        return None


# ── Main analysis run ─────────────────────────────────────────────────────────

def run_analysis():
    log("Running daily advisor analysis...")

    tao_usd = get_tao_price()
    snap = load_snapshot()

    if not snap:
        send_telegram(
            "⚠️ <b>TAO Advisor</b>\n"
            "No position snapshot found. Make sure tao_monitor.py has run at least once."
        )
        return

    alerts = rule_based_analysis(snap, tao_usd)
    ai_rec = ai_analysis(snap, tao_usd)

    total_usd = snap.get("total_value_usd") or 0
    price_str = f"${tao_usd:.2f}" if tao_usd else "unavailable"
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    msg = f"📊 <b>Daily TAO Advisor — {date_str}</b>\n"
    msg += f"TAO: {price_str}  |  Portfolio: ${total_usd:.2f}\n"

    if COST_BASIS_USD > 0:
        pnl = total_usd - COST_BASIS_USD
        pnl_pct = (pnl / COST_BASIS_USD) * 100
        sign = "+" if pnl >= 0 else ""
        msg += f"P&L vs cost basis: {sign}${pnl:.2f} ({sign}{pnl_pct:.1f}%)\n"

    msg += "\n"

    if alerts:
        msg += "<b>Rule-based alerts:</b>\n"
        msg += "\n\n".join(alerts)
        msg += "\n\n"

    if ai_rec:
        msg += f"<b>AI analysis:</b>\n{ai_rec}"
    elif ANTHROPIC_API_KEY == "none":
        msg += "<i>AI analysis disabled — add ANTHROPIC_API_KEY to .env to enable.</i>"

    if not alerts and not ai_rec and ANTHROPIC_API_KEY != "none":
        msg += "Nothing notable today — all positions within normal range."

    send_telegram(msg)
    log("Advisor analysis complete.")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="TAO daily portfolio advisor")
    parser.add_argument("--now", action="store_true", help="Run immediately instead of waiting for scheduled hour")
    args = parser.parse_args()

    if args.now:
        run_analysis()
        return

    log(f"=== TAO Advisor started — will run daily at {ADVISOR_RUN_HOUR:02d}:00 UTC ===")
    last_run_date = None

    while True:
        now = datetime.now(timezone.utc)
        if now.hour == ADVISOR_RUN_HOUR and now.date() != last_run_date:
            run_analysis()
            last_run_date = now.date()
        time.sleep(60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("Stopped by user.")
