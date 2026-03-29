#!/usr/bin/env python3
"""
tao_withdraw.py — Sends TAO from your wallet to any address.
Shows a full preview including fees before anything is sent.

Usage:
  python3 tao_withdraw.py --amount 1.0 --to 5DESTINATION_ADDRESS
"""

import argparse
import os
import sys

from dotenv import load_dotenv
import bittensor

load_dotenv()

WALLET_NAME = os.getenv("WALLET_NAME", "tao_main")


def main():
    parser = argparse.ArgumentParser(description="Withdraw TAO to another wallet")
    parser.add_argument("--amount", type=float, required=True, help="Amount of TAO to send")
    parser.add_argument("--to", type=str, required=True, help="Destination wallet address")
    parser.add_argument("--wallet", type=str, default=WALLET_NAME, help="Your wallet name")
    args = parser.parse_args()

    amount      = args.amount
    destination = args.to
    wallet_name = args.wallet

    # Basic address sanity check
    if not destination.startswith("5") or len(destination) < 40:
        print("ERROR: Destination address looks invalid. Bittensor addresses start with '5' and are 48 characters long.")
        sys.exit(1)

    print(f"\n=== TAO WITHDRAWAL PREVIEW ===\n")
    print(f"  From wallet : {wallet_name}")
    print(f"  To address  : {destination}")
    print(f"  Amount      : {amount:.4f} TAO")

    print(f"\nConnecting to Bittensor network...")
    try:
        wallet    = bittensor.Wallet(name=wallet_name)
        subtensor = bittensor.Subtensor(network="finney")
    except Exception as e:
        print(f"ERROR: Could not connect: {e}")
        sys.exit(1)

    # Fetch current balance
    try:
        balance = subtensor.get_balance(wallet.coldkeypub.ss58_address)
        balance_tao = float(balance)
        print(f"  Your balance: {balance_tao:.4f} TAO")
    except Exception as e:
        print(f"ERROR: Could not fetch balance: {e}")
        sys.exit(1)

    if balance_tao < amount:
        print(f"\nERROR: Insufficient balance. You have {balance_tao:.4f} TAO but tried to send {amount:.4f} TAO.")
        sys.exit(1)

    # Fetch transfer fee
    try:
        fee = subtensor.get_transfer_fee(
            wallet=wallet,
            dest=destination,
            value=bittensor.Balance.from_tao(amount),
        )
        fee_tao = float(fee)
        total_tao = amount + fee_tao
        print(f"  Network fee : {fee_tao:.6f} TAO")
        print(f"  Total cost  : {total_tao:.4f} TAO (amount + fee)")

        if balance_tao < total_tao:
            print(f"\nERROR: Insufficient balance to cover amount + fee.")
            print(f"  You have {balance_tao:.4f} TAO but need {total_tao:.4f} TAO.")
            sys.exit(1)

        print(f"  Remaining   : {balance_tao - total_tao:.4f} TAO after transfer")
    except Exception as e:
        print(f"WARNING: Could not fetch fee estimate: {e}")
        print("Proceeding without fee preview — actual fee will be deducted by the network.")

    print(f"\n  Double-check the destination address is correct.")
    print(f"  TAO sent to the wrong address cannot be recovered.\n")

    confirm = input("Type CONFIRM to send: ").strip()
    if confirm != "CONFIRM":
        print("Aborted — nothing was sent.")
        sys.exit(0)

    print(f"\nSending {amount:.4f} TAO to {destination}...")
    try:
        success = subtensor.transfer(
            wallet=wallet,
            dest=destination,
            amount=bittensor.Balance.from_tao(amount),
        )
        if success:
            print(f"\n✓ Transfer successful!")
            print(f"  You can verify it on: https://taostats.io/account/{destination}")
        else:
            print(f"\n✗ Transfer failed — check taostats.io for details.")
    except Exception as e:
        print(f"\n✗ Error during transfer: {e}")


if __name__ == "__main__":
    main()
