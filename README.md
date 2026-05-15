# 🚀 SUI Buy Bot

A Telegram buy-alert bot for the **SUI blockchain**.
It monitors DEX swap events (Cetus, Turbos, …) and posts a formatted alert every time someone buys your token.

```
🐋 New DEEP Buy! 🐋

💰 Spent:    450.00 SUI ($765.00)
🪙 Got:      1,250,000 DEEP ($810.25)
📈 Price:    $0.000648

🟢🟢🟢🟢🟢🟢⚪⚪

🏦 Mkt Cap:  $6.48M
📊 24h Vol:  $312.5K

🔗 DEX:      Cetus
👤 Buyer:    0x1a2b…9f0d

🔍 Explorer  |  SuiVision
📉 Chart
```

---

## Features

- 🔁 Real-time polling via SUI JSON-RPC (`suix_queryEvents`)
- 🏦 Supports **Cetus** and **Turbos** (+ any custom DEX package)
- 💵 Live USD prices via **DexScreener** + CoinGecko fallback
- 📊 Market cap & 24 h volume in every alert
- 🐟🐬🐋 Emoji tier by buy size
- ⚡ Admin commands: pause/resume, set minimum buy filter
- 🔒 Optional admin-only command lock

---

## Quick Start

### 1. Clone & install

```bash
git clone https://github.com/yourname/sui-buy-bot
cd sui-buy-bot
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
nano .env          # fill in your values (see below)
```

**Required variables:**

| Variable | Description |
|---|---|
| `TELEGRAM_TOKEN` | Bot token from [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_CHAT_ID` | Channel or group ID to post alerts in |
| `TRACKED_TOKEN` | Full SUI coin type, e.g. `0x<pkg>::<module>::<struct>` |
| `TOKEN_SYMBOL` | Display symbol, e.g. `DEEP` |

### 3. Add the bot to your channel

1. Create a Telegram channel (public or private)
2. Add your bot as an **Admin** with "Post Messages" permission
3. Copy the channel ID (e.g. `-1001234567890`) into `TELEGRAM_CHAT_ID`

### 4. Run

```bash
python main.py
```

---

## Commands

| Command | Description |
|---|---|
| `/start` | Welcome message |
| `/status` | Show stats & current config |
| `/pause` | Pause alerts |
| `/resume` | Resume alerts |
| `/setmin 100` | Only alert on buys ≥ $100 |
| `/help` | Show command list |

---

## Adding a custom DEX

If your token trades on a DEX not listed here, add the package ID to `.env`:

```env
EXTRA_DEX_PACKAGES=0xYOUR_DEX_PACKAGE_ID
```

For full event parsing, add a parser class in `monitor.py` following the `CetusParser` pattern.

---

## Architecture

```
main.py          ← entry point, wires everything together
config.py        ← all settings, loaded from .env
monitor.py       ← SUI RPC polling + swap event parsing
price_feed.py    ← DexScreener / CoinGecko USD prices
formatter.py     ← builds the Telegram HTML message
bot.py           ← python-telegram-bot glue + command handlers
```

---

## Supported DEXes

| DEX | Package | Status |
|---|---|---|
| Cetus | `0x1eabed7…` | ✅ Supported |
| Turbos | `0x91bfbc3…` | ✅ Supported |
| DeepBook | `0x000…dee9` | 🔜 Planned |
| FlowX | — | 🔜 Planned |

---

## Production Tips

- Use a **private RPC** (Triton One, Syndica, BlockEden) for better reliability and lower latency
- Set `POLL_INTERVAL=1.0` for near-real-time alerts
- Run with `pm2` or `systemd` so the bot auto-restarts on crash
- Set `MIN_BUY_USD=10` to filter spam micro-buys

---

## License

MIT
