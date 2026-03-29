#!/usr/bin/env python3
"""
tao_compare.py — Compares your current staking positions against your saved baseline.

Run anytime to see P&L since you first staked.

Usage:
  python3 tao_compare.py
"""

import asyncio
import json
import os
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv
import bittensor

load_dotenv()

CG_KEY        = os.getenv("COINGECKO_API_KEY", "none")
COLDKEY       = os.getenv("COLDKEY_ADDRESS", "")
BASELINE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tao_baseline.json")

SUBNET_VALIDATORS = {
    0:  ("Root \u2192 TAO.com", "5HK5tp6t2S59DywmHRWPBVJeJ86T61KjurYqeooqj8sREpeN"),
    64: ("Chutes",              "5Dt7HZ7Zpw4DppPxFM7Ke3Cm7sDAWhsZXmM5ZAmE7dSVJbcQ"),
    62: ("Ridges",              "5Djyacas3eWLPhCKsS3neNSJonzfxJmD3gcrMTFDc4eHsn62"),
    4:  ("Targon",              "5Hp18g9P8hLGKp9W3ZDr4bvJwba6b6bY3P2u3VdYf8yMR8FM"),
    75: ("Hippius",             "5G1Qj93Fy22grpiGKq6BEvqqmS2HVRs3jaEdMhq9absQzs6g"),
    68: ("Nova",                "5F1tQr8K2VfBr2pG5MpAQf62n5xSAsjuCZheQUy82csaPavg"),
    55: ("Ko/Precog",           "5CzSYnS88EpVv7Kve7U1VCYKjCbtKpxZNHMacAy3BkfCsn55"),
}


def get_tao_price():
    headers = {}
    if CG_KEY and CG_KEY != "none":
        headers["x-cg-demo-api-key"] = CG_KEY
    r = requests.get(
        "https://api.coingecko.com/api/v3/simple/price",
        params={"ids": "bittensor", "vs_currencies": "usd"},
        headers=headers,
        timeout=10,
    )
    r.raise_for_status()
    return r.json()["bittensor"]["usd"]


async def fetch_current_positions(tao_usd):
    positions = {}
    async with bittensor.AsyncSubtensor(network="finney") as sub:
        for netuid, (name, hotkey) in SUBNET_VALIDATORS.items():
            try:
                result = await sub.get_stake_for_coldkey_and_hotkey(
                    coldkey_ss58=COLDKEY,
                    hotkey_ss58=hotkey,
                    netuids=[netuid],
                )
                stake_info = result.get(netuid)
                stake = float(stake_info.stake) if stake_info else 0.0

                if netuid == 0:
                    positions[netuid] = {
                        "name": name,
                        "stake_tao": stake,
                        "value_usd": stake * tao_usd,
                    }
                else:
                    try:
                        price = await sub.get_subnet_price(netuid=netuid)
                        price_tao = float(price) if price else 0.0
                    except Exception:
                        price_tao = 0.0
                    positions[netuid] = {
                        "name": name,
                        "stake_alpha": stake,
                        "price_tao": price_tao,
                        "value_usd": stake * price_tao * tao_usd,
                    }
            except Exception as e:
                positions[netuid] = {"name": name, "error": str(e)}
    return positions


def pct_change(old, new):
    if old == 0:
        return 0.0
    return ((new - old) / old) * 100


def arrow(val):
    if val > 0:
        return f"▲ +{val:.2f}%"
    elif val < 0:
        return f"▼ {val:.2f}%"
    return "─  0.00%"


async def main():
    if not os.path.exists(BASELINE_FILE):
        print("No baseline found. Run tao_monitor.py first, then re-run this script.")
        return

    with open(BASELINE_FILE) as f:
        baseline = json.load(f)

    baseline_time = datetime.fromisoformat(baseline["timestamp"])
    now = datetime.now(timezone.utc)
    days_elapsed = (now - baseline_time).days
    hours_elapsed = int((now - baseline_time).total_seconds() / 3600)

    print(f"\n=== TAO PORTFOLIO P&L ===")
    print(f"Since:    {baseline_time.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"Now:      {now.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"Elapsed:  {days_elapsed}d {hours_elapsed % 24}h\n")

    print("Fetching live positions from chain...")
    tao_usd = get_tao_price()
    current = await fetch_current_positions(tao_usd)

    baseline_by_netuid = {p["netuid"]: p for p in baseline.get("positions", [])}
    baseline_tao_usd = baseline.get("tao_usd", tao_usd)

    print(f"\nTAO price: ${baseline_tao_usd:.2f} → ${tao_usd:.2f}  {arrow(pct_change(baseline_tao_usd, tao_usd))}\n")

    print(f"{'SN':<5} {'Name':<22} {'Then (USD)':>11}  {'Now (USD)':>11}  {'Change':>12}  {'P&L':>9}  Tokens")
    print(f"{'-'*92}")

    total_then = baseline.get("total_value_usd", 0)
    total_now  = 0.0

    for netuid, (name, hotkey) in SUBNET_VALIDATORS.items():
        cur  = current.get(netuid, {})
        base = baseline_by_netuid.get(netuid, {})

        if "error" in cur:
            print(f"SN{netuid:<3} {name:<22}   ERROR: {cur['error']}")
            continue

        val_then = base.get("value_usd", 0)
        val_now  = cur.get("value_usd", 0)
        total_now += val_now
        change = pct_change(val_then, val_now)
        pnl    = val_now - val_then
        pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"

        if netuid == 0:
            then_stake = base.get("stake_tao", 0)
            now_stake  = cur.get("stake_tao", 0)
            reward     = now_stake - then_stake
            token_str  = f"{now_stake:.4f} TAO" + (f" (+{reward:.6f})" if reward > 0.000001 else "")
        else:
            then_alpha = base.get("stake_alpha", 0)
            now_alpha  = cur.get("stake_alpha", 0)
            reward     = now_alpha - then_alpha
            token_str  = f"{now_alpha:.4f} α" + (f" (+{reward:.6f})" if reward > 0.000001 else "")

        print(f"SN{netuid:<3} {name:<22} ${val_then:>9.2f}  ${val_now:>9.2f}  {arrow(change):>12}  {pnl_str:>9}  {token_str}")

    print(f"{'-'*92}")
    total_change = pct_change(total_then, total_now)
    total_pnl    = total_now - total_then
    pnl_str = f"+${total_pnl:.2f}" if total_pnl >= 0 else f"-${abs(total_pnl):.2f}"
    print(f"{'TOTAL':<28} ${total_then:>9.2f}  ${total_now:>9.2f}  {arrow(total_change):>12}  {pnl_str:>9}")
    print(f"\nNote: Alpha token values are approximations based on bonding curve pricing.\n")


if __name__ == "__main__":
    asyncio.run(main())
