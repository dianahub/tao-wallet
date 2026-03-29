#!/usr/bin/env python3
"""
tao_simulate.py — Simulates your strategy with a test amount of TAO.
Shows what your portfolio would look like if you staked right now.
No real transactions. Read-only.

Usage:
  python3 tao_simulate.py
  python3 tao_simulate.py --amount 10
"""

import argparse
import asyncio
import os

import requests
from dotenv import load_dotenv
import bittensor

load_dotenv()

CG_KEY = os.getenv("COINGECKO_API_KEY", "none")

SUBNET_VALIDATORS = {
    0:  ("Root → TAO.com", "5HK5tp6t2S59DywmHRWPBVJeJ86T61KjurYqeooqj8sREpeN", 0.500),
    64: ("Chutes",          "5Dt7HZ7Zpw4DppPxFM7Ke3Cm7sDAWhsZXmM5ZAmE7dSVJbcQ", 0.165),
    62: ("Ridges",          "5Djyacas3eWLPhCKsS3neNSJonzfxJmD3gcrMTFDc4eHsn62", 0.110),
    4:  ("Targon",          "5Hp18g9P8hLGKp9W3ZDr4bvJwba6b6bY3P2u3VdYf8yMR8FM", 0.095),
    75: ("Hippius",         "5G1Qj93Fy22grpiGKq6BEvqqmS2HVRs3jaEdMhq9absQzs6g", 0.070),
    68: ("Nova",            "5F1tQr8K2VfBr2pG5MpAQf62n5xSAsjuCZheQUy82csaPavg", 0.035),
    55: ("Ko/Precog",       "5CzSYnS88EpVv7Kve7U1VCYKjCbtKpxZNHMacAy3BkfCsn55", 0.025),
}


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
        print(f"WARNING: Could not fetch TAO price: {e}")
        return None


async def get_subnet_prices():
    prices = {}
    print("Connecting to Bittensor network to fetch subnet prices...")
    try:
        async with bittensor.AsyncSubtensor(network="finney") as sub:
            for netuid in SUBNET_VALIDATORS:
                if netuid == 0:
                    prices[netuid] = 1.0  # Root: 1 TAO = 1 TAO
                    continue
                try:
                    price = await sub.get_subnet_price(netuid=netuid)
                    prices[netuid] = float(price) if price else 0.0
                except Exception as e:
                    print(f"  WARNING: Could not fetch price for SN{netuid}: {e}")
                    prices[netuid] = 0.0
    except Exception as e:
        print(f"ERROR connecting to network: {e}")
    return prices


async def main():
    parser = argparse.ArgumentParser(description="Simulate TAO strategy allocation")
    parser.add_argument("--amount", type=float,
                        default=float(os.getenv("TAO_DEPLOY_AMOUNT", "1.0")),
                        help="TAO amount to simulate (default: TAO_DEPLOY_AMOUNT from .env)")
    args = parser.parse_args()
    total_tao = args.amount

    print(f"\n=== TAO STRATEGY SIMULATION ===")
    print(f"Simulating {total_tao:.4f} TAO deployed across subnets\n")

    tao_usd = get_tao_price()
    if tao_usd:
        print(f"Live TAO price: ${tao_usd:.2f} USD")
        print(f"Total value:    ${total_tao * tao_usd:.2f} USD\n")
    else:
        print("(Could not fetch live price — USD values will show as N/A)\n")

    subnet_prices = await get_subnet_prices()

    print(f"\n{'SN':<5} {'Name':<22} {'Alloc':>6}  {'TAO':>8}  {'Alpha Tokens':>14}  {'Value (USD)':>12}")
    print(f"{'-'*75}")

    total_usd = 0.0
    for netuid, (name, hotkey, pct) in SUBNET_VALIDATORS.items():
        tao_amount = total_tao * pct
        price_tao = subnet_prices.get(netuid, 0.0)

        if netuid == 0:
            # Root: stake stays in TAO
            value_usd = tao_amount * tao_usd if tao_usd else None
            usd_str = f"${value_usd:.2f}" if value_usd is not None else "N/A"
            print(f"SN{netuid:<3} {name:<22} {pct*100:>5.1f}%  {tao_amount:>8.4f}  {'(TAO)':>14}  {usd_str:>12}")
            if value_usd:
                total_usd += value_usd
        else:
            # Alpha subnet: TAO buys alpha tokens at current price
            if price_tao > 0:
                alpha_tokens = tao_amount / price_tao
                value_usd = tao_amount * tao_usd if tao_usd else None
                usd_str = f"${value_usd:.2f}" if value_usd is not None else "N/A"
                print(f"SN{netuid:<3} {name:<22} {pct*100:>5.1f}%  {tao_amount:>8.4f}  {alpha_tokens:>14.4f}α  {usd_str:>12} (approx)")
                if value_usd:
                    total_usd += value_usd
            else:
                print(f"SN{netuid:<3} {name:<22} {pct*100:>5.1f}%  {tao_amount:>8.4f}  {'(price N/A)':>14}  {'N/A':>12}")

    print(f"{'-'*75}")
    usd_total_str = f"${total_usd:.2f}" if total_usd else "N/A"
    print(f"{'TOTAL':<32} {total_tao:>8.4f} TAO  {'':>14}  {usd_total_str:>12}")
    print(f"\nNote: Alpha token values are approximate — based on bonding curve pricing.")
    print(f"Note: This is a simulation only. No transactions have been made.\n")


if __name__ == "__main__":
    asyncio.run(main())
