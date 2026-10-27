# job-hunter-agent

**English** · [Русский](README.ru.md)

A personal Telegram bot that monitors job-posting channels for you. It reads
only the Telegram channels you add, filters posts by your keywords and
stop-words, and forwards the matching vacancies to your private chat. Channels
and keywords are managed directly from the bot with commands — no config
editing or restarts needed.

## Why

Job hunting through Telegram means scrolling dozens of channels a day, most of
which are noise. This bot does the scrolling: it checks your channels on a
schedule, keeps only the posts that match what you are looking for, and never
sends the same vacancy twice.

## Features

- **Reads any channel your account can see** — public channels, private (paid)
  channels you are subscribed to, and even bots that send you vacancies in DMs.
  Uses the Telegram user API (Telethon) in read-only mode.
- **Flexible keyword matching** — case-insensitive whole-word search,
  `*` wildcards for word endings (`develop*` → developer, development), multi-word
  phrases, and stop-words that drop a post entirely (`junior`, `intern`).
  Works with Cyrillic and Latin text alike.
- **Ready-made channel groups** — `/groups` shows inline buttons with curated
  channel sets (Russia & CIS / International; IT & product, fintech, gamedev)
  that can be toggled on or off in one tap.
- **Deduplication** — every sent post is stored in SQLite; URLs are normalized
  (tracking parameters stripped), so a vacancy reposted with `?utm=...` is not
  sent again.
- **Fully managed from chat** — add/remove channels and keywords, run a search
  on demand, pause/resume the schedule, view 24-hour stats.
- **Owner-only access** — the bot responds only to the configured `chat_id`.
- **Safe by default** — the bot token is kept out of logs, secrets are excluded
  from the Docker image, logs are rotated.
- **One-command deploy** — Docker Compose with persistent volumes for config,
  session, database and logs.

## How it works

```
 ┌──────────────┐   Telethon (user API)   ┌────────────────────┐
 │  Telegram    │ ──────────────────────▶ │ sources/           │
 │  channels &  │                         │ telegram_channels  │
 │  bots        │                         └─────────┬──────────┘
 └──────────────┘                                   │ posts
                                                    ▼
 ┌──────────────┐   keywords / channels   ┌────────────────────┐
 │  You (owner) │ ◀─────────────────────▶ │ bot/ (commands,    │
 │  in Telegram │     Bot API commands    │ scheduler)         │
 └──────▲───────┘                         └─────────┬──────────┘
        │                                           ▼
        │                                 ┌────────────────────┐
        │      matched, new vacancies     │ core/matcher  →    │
        └──────────────────────────────── │ core/state (SQLite)│
                                          │ → core/notifier    │
                                          └────────────────────┘
```

A single asyncio process runs both the bot (python-telegram-bot) and the
periodic search job (its `JobQueue`). Each cycle reads recent messages from the
configured channels, runs them through the matcher, checks SQLite for
duplicates and sends what's new. Manual and scheduled searches share a lock so
they never run concurrently against the Telethon session.

## Tech stack

- Python 3.11, asyncio
- [python-telegram-bot](https://python-telegram-bot.org/) 21 — bot commands, inline keyboards, job scheduling
- [Telethon](https://docs.telethon.dev/) — reading channels via the Telegram user API
- Pydantic 2 — validation of JSON configs
- SQLite — deduplication and stats
- Docker / Docker Compose

## Project structure

```
main.py                    entry point: bot + scheduler
orchestrator.py            one search cycle: read → filter → dedupe → notify
bot/bot_commands.py        command handlers, owner-only guard, scheduling
bot/groups.py              curated channel groups with inline buttons
core/matcher.py            keyword / wildcard / stop-word matching
core/state.py              SQLite deduplication
core/notifier.py           sending vacancies to the owner
core/storage.py            JSON config storage
core/config_schema.py      Pydantic models
sources/telegram_channels.py   Telethon channel reader
sources/login_telethon.py      one-time interactive login
config/channel_groups.json     curated channel lists
```

## Getting started

### 1. Install

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### 2. Configure `.env`

| Variable | Where to get it |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Message `@BotFather` → `/newbot` → copy the token |
| `TELEGRAM_CHAT_ID` | Send any message to your bot, open `https://api.telegram.org/bot<TOKEN>/getUpdates` and take `chat.id`. Only this chat can control the bot |
| `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` | https://my.telegram.org → API development tools |
| `POLL_INTERVAL_MINUTES` | How often to check channels (default 60) |
| `TG_CHANNEL_LOOKBACK_HOURS` | How far back to read messages (default 24) |

### 3. Log in to Telegram (once)

```bash
python -m sources.login_telethon
```

Enter your phone number, the login code (and 2FA password, if enabled). This
creates `config/telethon_session.session`, reused afterwards without logging in
again.

To try a single search cycle without the bot (results go to the log):

```bash
python -m orchestrator
```

### 4. Deploy with Docker

```bash
git clone https://github.com/psihovnet/job-hunter-agent.git
cd job-hunter-agent
cp .env.example .env               # fill it in
python -m sources.login_telethon   # once, before docker-compose up
touch state.db job-hunter.log      # otherwise Docker creates directories
docker-compose up -d
docker-compose logs -f
```

`./config`, `state.db` and `job-hunter.log` are mounted as volumes and survive
container re-creation.

## Bot commands

| Command | Description |
|---|---|
| `/groups` | Curated channel groups, toggled with buttons |
| `/add_channel @ch1 t.me/ch2 1234567890` | Add channels by @username, link, id or post link; bots too |
| `/remove_channel @ch` | Remove a channel |
| `/list_channels` | Show tracked channels |
| `/my_channels [query]` | Channels your account is in (incl. private 🔒), with ready-to-use add commands |
| `/keywords` | Show keywords and stop-words |
| `/add_keyword python, team lead, develop*` | A post matches if it contains any of these |
| `/remove_keyword python` | Remove keywords |
| `/add_exclude junior, intern` | Drop posts containing any of these |
| `/remove_exclude junior` | Remove stop-words |
| `/search_now` | Check channels right now |
| `/pause`, `/resume` | Pause / resume scheduled checks |
| `/stats` | Vacancies sent in the last 24 hours |

If the keyword list is empty, every post (without stop-words) is forwarded.
