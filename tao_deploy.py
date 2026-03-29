#!/usr/bin/env python3
"""
tao_deploy.py — Stakes TAO across configured subnets.
Runs a dry-run preview first. Type CONFIRM to execute real transactions.

Usage:
  python3 tao_deploy.py --amount 1.0
  python3 tao_deploy.py --amount 1.0 --dry-run
"""

import argparse
import asyncio
import os
import sys

from dotenv import load_dotenv
import bittensor

load_dotenv()

WALLET_NAME = os.getenv("WALLET_NAME", "tao_main")

# Subnet allocations: netuid -> (label, hotkey, fraction_of_total)
SUBNET_VALIDATORS = {
    0:  ("Root → TAO.com", "5HK5tp6t2S59DywmHRWPBVJeJ86T61KjurYqeooqj8sREpeN", 0.500),
    64: ("Chutes",          "5Dt7HZ7Zpw4DppPxFM7Ke3Cm7sDAWhsZXmM5ZAmE7dSVJbcQ", 0.165),
    62: ("Ridges",          "5Djyacas3eWLPhCKsS3neNSJonzfxJmD3gcrMTFDc4eHsn62", 0.110),
    4:  ("Targon",          "5Hp18g9P8hLGKp9W3ZDr4bvJwba6b6bY3P2u3VdYf8yMR8FM", 0.095),
    75: ("Hippius",         "5G1Qj93Fy22grpiGKq6BEvqqmS2HVRs3jaEdMhq9absQzs6g", 0.070),
    68: ("Nova",            "5F1tQr8K2VfBr2pG5MpAQf62n5xSAsjuCZheQUy82csaPavg", 0.035),
    55: ("Ko/Precog",       "5CzSYnS88EpVv7Kve7U1VCYKjCbtKpxZNHMacAy3BkfCsn55", 0.025),
}


async def verify_hotkeys(allocations):
    """Check each validator hotkey is registered on its subnet. Returns list of (netuid, name, ok, reason)."""
    results = []
    print("\nVerifying validator hotkeys on-chain...")
    try:
        async with bittensor.AsyncSubtensor(network="finney") as sub:
            for netuid, name, hotkey, pct, amount in allocations:
                try:
                    registered = await sub.is_hotkey_registered(
                        netuid=netuid, hotkey_ss58=hotkey
                    )
                    if registered:
                        results.append((netuid, name, True, "active"))
                        print(f"  SN{netuid:<3} {name:<22} ✓ active")
                    else:
                        results.append((netuid, name, False, "NOT registered on this subnet"))
                        print(f"  SN{netuid:<3} {name:<22} ✗ NOT REGISTERED — do not stake here")
                except Exception as e:
                    results.append((netuid, name, False, f"check failed: {e}"))
                    print(f"  SN{netuid:<3} {name:<22} ⚠ could not verify: {e}")
    except Exception as e:
        print(f"  Could not connect to verify hotkeys: {e}")
        return None
    return results


def print_preview(wallet_name, total, allocations):
    print("\n=== TAO DEPLOYMENT PREVIEW ===\n")
    print(f"  Wallet : {wallet_name}")
    print(f"  Total  : {total:.4f} TAO\n")
    print(f"  {'SN':<5} {'Name':<22} {'Allocation':>10}   {'TAO Amount':>10}   Validator")
    print(f"  {'-'*80}")
    for netuid, name, hotkey, pct, amount in allocations:
        print(f"  SN{netuid:<3} {name:<22} {pct*100:>9.1f}%   {amount:>10.4f} TAO   {hotkey[:16]}...")
    print(f"  {'-'*80}")
    print(f"  {'TOTAL':<27} {'100.0%':>10}   {sum(a[4] for a in allocations):>10.4f} TAO")
    print()


def main():
    parser = argparse.ArgumentParser(description="Deploy TAO across subnets")
    parser.add_argument("--amount", type=float, default=float(os.getenv("TAO_DEPLOY_AMOUNT", "1.0")),
                        help="Total TAO to deploy (default: TAO_DEPLOY_AMOUNT from .env)")
    parser.add_argument("--wallet", type=str, default=WALLET_NAME, help="Wallet name")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, no transactions")
    args = parser.parse_args()

    total = args.amount
    wallet_name = args.wallet

    allocations = [
        (netuid, name, hotkey, pct, round(total * pct, 6))
        for netuid, (name, hotkey, pct) in SUBNET_VALIDATORS.items()
    ]

    print_preview(wallet_name, total, allocations)

    # Automatically verify all hotkeys on-chain
    verification = asyncio.run(verify_hotkeys(allocations))

    if verification is None:
        print("\n⚠️  Could not verify hotkeys (network error). Manually check taostats.io before proceeding.")
    else:
        failed = [r for r in verification if not r[2]]
        if failed:
            print(f"\n🚫 {len(failed)} validator(s) are NOT active on their subnet:")
            for netuid, name, ok, reason in failed:
                print(f"   SN{netuid} {name}: {reason}")
            print("Aborting — update the hotkeys in tao_deploy.py before staking.")
            sys.exit(1)
        else:
            print("\n✓ All validators confirmed active on-chain.\n")

    if args.dry_run:
        print("[DRY RUN] No transactions executed.\n")
        return

    confirm = input("Type CONFIRM to proceed with real staking transactions: ").strip()
    if confirm != "CONFIRM":
        print("Aborted — nothing was staked.")
        sys.exit(0)

    print("\nConnecting to Bittensor network...")
    try:
        wallet = bittensor.Wallet(name=wallet_name)
        subtensor = bittensor.Subtensor(network="finney")
    except Exception as e:
        print(f"Failed to connect: {e}")
        sys.exit(1)

    print("Connected.\n")

    for netuid, name, hotkey, pct, amount in allocations:
        print(f"Staking {amount:.4f} TAO → SN{netuid} {name}...")
        try:
            success = subtensor.add_stake(
                wallet=wallet,
                hotkey_ss58=hotkey,
                netuid=netuid,
                amount=bittensor.Balance.from_tao(amount),
            )
            if success:
                print(f"  ✓ Done")
            else:
                print(f"  ✗ Transaction returned failure — check taostats.io")
        except Exception as e:
            print(f"  ✗ Error: {e}")

    print("\n=== DEPLOYMENT COMPLETE ===\n")


if __name__ == "__main__":
    main()
