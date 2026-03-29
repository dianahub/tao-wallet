#!/usr/bin/env python3
"""
tao_monitor.py — Fetches and logs your Bittensor staking positions.
Run manually or via PM2/cron every hour.

Usage:
  python3 tao_monitor.py
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv
import bittensor

load_dotenv()

COLDKEY   = os.getenv("COLDKEY_ADDRESS", "")
CG_KEY    = os.getenv("COINGECKO_API_KEY", "none")
DASH_URL  = os.getenv("DASHBOARD_URL", "none")
LOG_DIR   = os.path.dirname(os.path.abspath(__file__))
LOG_FILE  = os.path.join(LOG_DIR, "tao_monitor.log")
SNAP_FILE = "/tmp/tao_latest.json"

SUBNET_VALIDATORS = {
    0:  ("Root → TAO.com", "5HK5tp6t2S59DywmHRWPBVJeJ86T61KjurYqeooqj8sREpeN"),
    64: ("Chutes",          "5Dt7HZ7Zpw4DppPxFM7Ke3Cm7sDAWhsZXmM5ZAmE7dSVJbcQ"),
    62: ("Ridges",          "5Djyacas3eWLPhCKsS3neNSJonzfxJmD3gcrMTFDc4eHsn62"),
    4:  ("Targon",          "5Hp18g9P8hLGKp9W3ZDr4bvJwba6b6bY3P2u3VdYf8yMR8FM"),
    75: ("Hippius",         "5G1Qj93Fy22grpiGKq6BEvqqmS2HVRs3jaEdMhq9absQzs6g"),
    68: ("Nova",            "5F1tQr8K2VfBr2pG5MpAQf62n5xSAsjuCZheQUy82csaPavg"),
    55: ("Ko/Precog",       "5CzSYnS88EpVv7Kve7U1VCYKjCbtKpxZNHMacAy3BkfCsn55"),
}


def log(msg):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")
    trim_log()


def trim_log(max_lines=10080):  # ~7 days at 1 line/min
    try:
        with open(LOG_FILE, "r") as f:
            lines = f.readlines()
        if len(lines) > max_lines:
            with open(LOG_FILE, "w") as f:
                f.writelines(lines[-max_lines:])
    except Exception:
        pass


def get_tao_price():
    """Fetch TAO price in USD from CoinGecko."""
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
        log(f"ERROR: Failed to fetch TAO price: {e}")
        return None


async def fetch_positions(tao_usd):
    positions = []
    try:
        async with bittensor.AsyncSubtensor(network="finney") as sub:
            for netuid, (name, hotkey) in SUBNET_VALIDATORS.items():
                try:
                    result = await sub.get_stake_for_coldkey_and_hotkey(
                        coldkey_ss58=COLDKEY,
                        hotkey_ss58=hotkey,
                        netuids=[netuid],
                    )
                    # result is dict[netuid -> StakeInfo]
                    stake_info = result.get(netuid)
                    stake_tao = float(stake_info.stake) if stake_info else 0.0

                    if netuid == 0:
                        value_usd = stake_tao * tao_usd if tao_usd else None
                        positions.append({
                            "netuid": netuid,
                            "name": name,
                            "stake_tao": stake_tao,
                            "value_usd": value_usd,
                            "note": "Root TAO stake",
                        })
                    else:
                        # Alpha subnets: value is approximate (bonding curve pricing)
                        try:
                            price = await sub.get_subnet_price(netuid=netuid)
                            price_tao = float(price) if price else 0.0
                        except Exception:
                            price_tao = 0.0

                        value_tao = stake_tao * price_tao
                        value_usd = value_tao * tao_usd if tao_usd else None
                        positions.append({
                            "netuid": netuid,
                            "name": name,
                            "stake_alpha": stake_tao,
                            "price_tao": price_tao,
                            "value_tao": value_tao,
                            "value_usd": value_usd,
                            "note": "Alpha token value is approximate (bonding curve pricing)",
                        })
                except Exception as e:
                    log(f"ERROR fetching SN{netuid} {name}: {e}")
                    positions.append({"netuid": netuid, "name": name, "error": str(e)})
    except Exception as e:
        log(f"ERROR connecting to Bittensor network: {e}")

    return positions


def save_snapshot(snapshot):
    tmp = SNAP_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(snapshot, f, indent=2)
    os.replace(tmp, SNAP_FILE)


def post_to_dashboard(snapshot):
    try:
        r = requests.post(f"{DASH_URL}/api/tao-snapshot", json=snapshot, timeout=10)
        r.raise_for_status()
        log("Dashboard updated.")
    except Exception as e:
        log(f"ERROR posting to dashboard: {e}")


async def main():
    if not COLDKEY:
        log("ERROR: COLDKEY_ADDRESS not set in .env")
        sys.exit(1)

    log("=== TAO Monitor starting ===")

    tao_usd = get_tao_price()
    if tao_usd:
        log(f"TAO price: ${tao_usd:.2f} USD")
    else:
        log("WARNING: Could not fetch TAO price — USD values will be unavailable")

    positions = await fetch_positions(tao_usd)

    total_usd = sum(p.get("value_usd") or 0 for p in positions)

    log(f"\n{'SN':<5} {'Name':<22} {'Stake':>12}   {'Value (USD)':>12}")
    log(f"{'-'*60}")
    for p in positions:
        if "error" in p:
            log(f"SN{p['netuid']:<3} {p['name']:<22}   ERROR: {p['error']}")
        elif p["netuid"] == 0:
            usd = f"${p['value_usd']:.2f}" if p.get("value_usd") is not None else "N/A"
            log(f"SN{p['netuid']:<3} {p['name']:<22} {p['stake_tao']:>10.4f} TAO   {usd:>12}")
        else:
            usd = f"${p['value_usd']:.2f}" if p.get("value_usd") is not None else "N/A"
            log(f"SN{p['netuid']:<3} {p['name']:<22} {p['stake_alpha']:>10.4f} α     {usd:>12} (approx)")
    log(f"{'-'*60}")
    log(f"{'TOTAL USD VALUE':<40} ${total_usd:.2f}")
    log("(Alpha token values are approximations based on bonding curve pricing)")

    snapshot = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tao_usd": tao_usd,
        "total_value_usd": total_usd,
        "positions": positions,
    }

    if DASH_URL and DASH_URL != "none":
        post_to_dashboard(snapshot)
    else:
        save_snapshot(snapshot)
        log(f"Snapshot saved to {SNAP_FILE}")

    log("=== TAO Monitor complete ===\n")


if __name__ == "__main__":
    asyncio.run(main())
