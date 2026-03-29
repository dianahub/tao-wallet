#!/usr/bin/env python3
"""
tao_alerts.py — Continuous alert system for TAO price, portfolio, and Twitter.

Runs forever. Start with PM2 or: python3 tao_alerts.py

Checks:
  - TAO price every hour (price milestones + portfolio multipliers + drawdown)
  - Twitter/X keywords via Nitter RSS every 15 minutes
"""

import json
import os
import sys
import time
from datetime import datetime, timezone

import feedparser
import requests
from dotenv import load_dotenv

load_dotenv()

COLDKEY           = os.getenv("COLDKEY_ADDRESS", "")
COST_BASIS_USD    = float(os.getenv("COST_BASIS_USD", "0") or "0")
DEPLOY_TRIGGER    = float(os.getenv("DEPLOY_TRIGGER_USD", "0") or "0")
CG_KEY            = os.getenv("COINGECKO_API_KEY", "none")
BOT_TOKEN         = os.getenv("TELEGRAM_BOT_TOKEN", "none")
CHAT_ID           = os.getenv("TELEGRAM_CHAT_ID", "none")

STATE_FILE        = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tao_alert_state.json")
SNAP_FILE         = "/tmp/tao_latest.json"

PRICE_MILESTONES  = [500, 3000, 10000, 30000]       # USD
PORTFOLIO_MULT    = [2, 5, 10, 25]                   # × cost basis USD
DRAWDOWN_PCT      = 0.30                              # 30% from peak
ALPHA_SPIKE_PCT   = 0.20                              # 20% in one hour
DEPLOY_REMINDER_DAYS = 14

TWITTER_ACCOUNTS  = ["const_anto", "markjeffrey", "bittensor_", "tao_dot_com"]
KEYWORDS          = [
    "listing", "listed", "exchange", "cex", "coinbase", "binance",
    "kraken", "bybit", "okx", "kucoin", "gate.io",
    "chutes", "ridges", "targon", "hippius", "nova", "precog",
]
NITTER_BASE       = "https://nitter.poast.org"

PRICE_INTERVAL    = 3600    # 1 hour in seconds
TWITTER_INTERVAL  = 900     # 15 minutes in seconds


# ── Helpers ───────────────────────────────────────────────────────────────────

def log(msg):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{ts}] {msg}", flush=True)


def send_telegram(msg):
    if BOT_TOKEN == "none" or CHAT_ID == "none":
        log(f"[ALERT] {msg}")
        return
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=10,
        )
        r.raise_for_status()
    except Exception as e:
        log(f"ERROR sending Telegram message: {e}")


def load_state():
    if not os.path.exists(STATE_FILE):
        return default_state()
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        log(f"WARNING: Could not load state file ({e}) — starting fresh")
        return default_state()


def save_state(state):
    tmp = STATE_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, STATE_FILE)
    except Exception as e:
        log(f"ERROR saving state: {e}")


def default_state():
    return {
        "price_milestones_fired": [],
        "portfolio_mult_fired": [],
        "peak_portfolio_usd": 0.0,
        "drawdown_fired": False,
        "deploy_trigger_fired": False,
        "deploy_reminder_fired": False,
        "deploy_reminder_start": datetime.now(timezone.utc).isoformat(),
        "seen_tweet_ids": [],
        "last_alpha_prices": {},
    }


# ── Price & portfolio checks ──────────────────────────────────────────────────

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
        send_telegram(f"⚠️ TAO price check failed — alerts may be unreliable.\nError: {e}")
        log(f"ERROR fetching price: {e}")
        return None


def get_portfolio_usd():
    try:
        with open(SNAP_FILE, "r") as f:
            snap = json.load(f)
        return snap.get("total_value_usd", 0.0)
    except Exception:
        return 0.0


def check_price_alerts(state, tao_usd):
    if tao_usd is None:
        return

    # Price milestones
    for milestone in PRICE_MILESTONES:
        key = str(milestone)
        if tao_usd >= milestone and key not in state["price_milestones_fired"]:
            send_telegram(f"🚀 TAO has reached ${milestone:,}!\nCurrent price: ${tao_usd:.2f} USD")
            state["price_milestones_fired"].append(key)
            log(f"ALERT: TAO hit ${milestone}")

    # Deploy window
    if DEPLOY_TRIGGER > 0 and tao_usd <= DEPLOY_TRIGGER and not state["deploy_trigger_fired"]:
        send_telegram(f"💰 TAO is at or below your deploy trigger of ${DEPLOY_TRIGGER:.0f}!\nCurrent price: ${tao_usd:.2f} USD")
        state["deploy_trigger_fired"] = True
        log(f"ALERT: Deploy trigger hit at ${tao_usd:.2f}")

    # Portfolio multipliers
    if COST_BASIS_USD > 0:
        portfolio_usd = get_portfolio_usd()
        if portfolio_usd > 0:
            multiple = portfolio_usd / COST_BASIS_USD
            for mult in PORTFOLIO_MULT:
                key = str(mult)
                if multiple >= mult and key not in state["portfolio_mult_fired"]:
                    send_telegram(
                        f"🎉 Your TAO portfolio has reached {mult}x your investment!\n"
                        f"Portfolio: ${portfolio_usd:.2f} | Cost basis: ${COST_BASIS_USD:.2f}"
                    )
                    state["portfolio_mult_fired"].append(key)
                    log(f"ALERT: Portfolio hit {mult}x")

            # Drawdown from peak
            if portfolio_usd > state.get("peak_portfolio_usd", 0):
                state["peak_portfolio_usd"] = portfolio_usd
                state["drawdown_fired"] = False  # reset on new peak

            peak = state.get("peak_portfolio_usd", 0)
            if peak > 0:
                drawdown = (peak - portfolio_usd) / peak
                if drawdown >= DRAWDOWN_PCT and not state.get("drawdown_fired"):
                    send_telegram(
                        f"⚠️ Portfolio down {drawdown*100:.0f}% from peak — consider reviewing your position.\n"
                        f"Peak: ${peak:.2f} | Current: ${portfolio_usd:.2f}"
                    )
                    state["drawdown_fired"] = True
                    log(f"ALERT: Drawdown {drawdown*100:.0f}% from peak")

    # Deploy reminder after 14 days
    if not state.get("deploy_reminder_fired"):
        try:
            start = datetime.fromisoformat(state["deploy_reminder_start"])
            days_elapsed = (datetime.now(timezone.utc) - start).days
            if days_elapsed >= DEPLOY_REMINDER_DAYS:
                send_telegram(
                    f"⏰ It's been {DEPLOY_REMINDER_DAYS} days since setup.\n"
                    f"Have you deployed all your capital?\nCurrent TAO price: ${tao_usd:.2f} USD"
                )
                state["deploy_reminder_fired"] = True
                log("ALERT: 14-day deploy reminder sent")
        except Exception:
            pass


# ── Alpha spike check ─────────────────────────────────────────────────────────

def check_alpha_spikes(state):
    try:
        with open(SNAP_FILE, "r") as f:
            snap = json.load(f)
    except Exception:
        return

    last = state.get("last_alpha_prices", {})
    new_prices = {}

    for pos in snap.get("positions", []):
        netuid = str(pos.get("netuid"))
        if netuid == "0":
            continue
        price = pos.get("price_tao", 0)
        if price and price > 0:
            new_prices[netuid] = price
            if netuid in last and last[netuid] > 0:
                change = (price - last[netuid]) / last[netuid]
                if change >= ALPHA_SPIKE_PCT:
                    name = pos.get("name", f"SN{netuid}")
                    send_telegram(
                        f"📈 {name} (SN{netuid}) alpha token up {change*100:.0f}% in the last hour!\n"
                        f"Price: {price:.6f} TAO per alpha"
                    )
                    log(f"ALERT: {name} alpha spike {change*100:.0f}%")

    state["last_alpha_prices"] = new_prices


# ── Twitter/Nitter watcher ────────────────────────────────────────────────────

def check_twitter(state):
    seen = set(state.get("seen_tweet_ids", []))
    new_seen = set(seen)

    for account in TWITTER_ACCOUNTS:
        url = f"{NITTER_BASE}/{account}/rss"
        try:
            feed = feedparser.parse(url)
            if feed.bozo and not feed.entries:
                send_telegram(f"⚠️ Twitter watcher: feed for @{account} is unavailable — alerts from this account are paused.")
                log(f"WARNING: RSS feed unavailable for @{account}")
                continue

            for entry in feed.entries:
                tweet_id = entry.get("id", entry.get("link", ""))
                if tweet_id in seen:
                    continue
                new_seen.add(tweet_id)

                text = entry.get("summary", entry.get("title", "")).lower()
                matched = [kw for kw in KEYWORDS if kw in text]
                if matched:
                    raw_text = entry.get("summary", entry.get("title", ""))
                    send_telegram(
                        f"🐦 @{account} tweeted about: {', '.join(matched)}\n\n"
                        f"{raw_text[:300]}\n\n"
                        f"⚠️ Verify directly on X/Twitter — third-party RSS feeds can lag or fail."
                    )
                    log(f"ALERT: @{account} keyword match: {matched}")

        except Exception as e:
            log(f"ERROR checking @{account} RSS: {e}")

    state["seen_tweet_ids"] = list(new_seen)[-500:]


# ── Main loop ─────────────────────────────────────────────────────────────────

def main():
    log("=== TAO Alerts starting ===")
    send_telegram("✅ TAO alert system is now running.")

    state = load_state()

    last_price_check   = 0
    last_twitter_check = 0

    while True:
        now = time.time()

        if now - last_price_check >= PRICE_INTERVAL:
            log("Running price & portfolio checks...")
            tao_usd = get_tao_price()
            if tao_usd:
                log(f"TAO: ${tao_usd:.2f} USD")
            check_price_alerts(state, tao_usd)
            check_alpha_spikes(state)
            save_state(state)
            last_price_check = now

        if now - last_twitter_check >= TWITTER_INTERVAL:
            log("Running Twitter/Nitter checks...")
            check_twitter(state)
            save_state(state)
            last_twitter_check = now

        time.sleep(60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("Stopped by user.")
        sys.exit(0)
