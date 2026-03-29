# TAO_WALLET

Your Bittensor monitoring and simulation system.

---

## Folder location

```
C:\TAO_WALLET
```

This folder is stored directly on your C: drive and is **not synced to OneDrive or any cloud service**.

---

## How to run scripts

Open your terminal (WSL) and navigate to the folder:

```bash
cd /mnt/c/TAO_WALLET
```

Then run whichever script you need:

```bash
python3 tao_simulate.py        # See what your strategy is worth right now
python3 tao_compare.py         # Compare current values to your baseline (saved 2026-03-29)
python3 tao_monitor.py         # Fetch your live staking positions
python3 tao_alerts.py          # Run alerts continuously (price, portfolio, Twitter)
python3 tao_advisor.py         # Run daily AI + rule-based portfolio analysis
python3 tao_advisor.py --now   # Run advisor immediately (don't wait for scheduled hour)
python3 tao_deploy.py          # Deploy TAO (dry-run first, then type CONFIRM)
```

---

## What each file does

| File | Purpose |
|------|---------|
| `.env` | Your private config — wallet address, Telegram token, API keys |
| `tao_simulate.py` | Simulates your strategy with a test amount |
| `tao_compare.py` | Compares current prices to your saved baseline |
| `tao_monitor.py` | Fetches live staking positions and logs them |
| `tao_alerts.py` | 24/7 alerts: price milestones, portfolio, Twitter |
| `tao_deploy.py` | Stakes TAO across subnets (requires real TAO) |
| `tao_withdraw.py` | Sends TAO to another wallet (shows fees before confirming) |
| `tao_baseline.json` | Snapshot saved on 2026-03-29 — used by tao_compare.py |

---

## Deploying TAO

Run the dry-run first to preview exactly what will be staked:

```bash
cd /mnt/c/TAO_WALLET
python3 tao_deploy.py --amount 1.0 --wallet tao_main --dry-run
```

This is just a preview — nothing has been staked yet. Read the summary carefully. When you're ready to deploy for real, run the same command without `--dry-run` and type `CONFIRM` when prompted. The real transactions run one at a time and each takes 1–3 minutes. Full deployment takes about 15 minutes.

---

## Starting PM2 monitoring

Run these one at a time:

```bash
pm2 start /mnt/c/TAO_WALLET/tao_monitor_ecosystem.config.cjs
pm2 start /mnt/c/TAO_WALLET/tao_alerts.py --interpreter python3 --name tao-alerts
pm2 save
pm2 startup
```

PM2 will print a command after `pm2 startup` — read it before running it. It will typically look like:

```
sudo env PATH=$PATH:/usr/local/bin pm2 startup systemd -u diana --hp /home/diana
```

It needs `sudo` (admin access). If you're unsure what it's asking, check with Claude before running it. Once you've run it, type `pm2 save` again to lock in your processes.

Since you're on WSL/Linux (not macOS), skip `caffeinate`. Instead, make sure your machine doesn't suspend. On Windows, you can use **PowerToys → Awake** or Task Scheduler to keep it alive. Set a weekly reminder to run `pm2 list` and confirm both `tao-monitor` and `tao-alerts` show **online**.

---

## When you have real TAO

1. Update `.env` with your `COST_BASIS_USD` and `DEPLOY_TRIGGER_USD`
2. Run: `python3 tao_deploy.py --amount YOUR_AMOUNT`
3. Review the preview, then type `CONFIRM` to stake

Update your `.env` with what you actually spent so portfolio multiplier alerts work:

```
COST_BASIS_USD=320.93   # replace with what you paid in USD
```

The alerts system will then automatically notify you on Telegram when you hit 2x, 5x, 10x, and 25x your investment.

---

## Security reminders

- Never share your `.env` file
- Never upload this folder to Google Drive, OneDrive, or any cloud storage
- Your seed phrases are stored in `.env` — keep a physical backup written on paper
