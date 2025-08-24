# Discord Ticket Bot + Streamlit Dashboard

A lightweight ticket system for your DayZ server's Discord. Users open tickets via slash commands, the bot creates a thread and logs details to SQLite. Staff manage and reply from a Streamlit dashboard; the bot relays dashboard messages to the thread.

## Features
- `/ticket_open` with a reason → creates a thread in your support channel and logs to DB
- `/ticket_claim` and `/ticket_close` for staff
- SQLite-backed
- Streamlit dashboard: filter tickets, set status, send canned replies (bot posts them)
- Single-server (guild) focused for simplicity

## Setup

1. **Python** 3.10+ recommended.
2. Install deps:
   ```bash
   pip install -r requirements.txt
   ```
3. Copy the example config:
   ```bash
   cp config.example.toml config.toml
   ```
   Fill in:
   - `discord.bot_token`
   - `discord.guild_id`
   - `discord.support_channel_id` (a text channel where threads are allowed)
   - `discord.staff_role_id`
   - `app.db_path` (default: `tickets.db`)

4. **Run the bot** (first terminal):
   ```bash
   python bot.py
   ```
   The bot will create tables on startup.

5. **Run the dashboard** (second terminal):
   ```bash
   streamlit run streamlit_app.py
   ```

6. In Discord, test:
   - `/ticket_open reason:"I can't connect to the server"`
   - Inside the created thread, staff can `/ticket_claim` and `/ticket_close`.

## Notes
- The dashboard queues replies in the DB. The bot picks them up every ~5s and posts in the thread.
- This starter uses threads to avoid channel sprawl. If you prefer private channels per ticket, we can switch it.
- Permissions: ensure your staff role has access to the support channel/threads.

## Common tweaks
- Add categories (priority, type) → new columns in `tickets` and small UI changes.
- Multi-guild support → add `guild_id` columns everywhere and separate configs.
- Webhook relay → send status updates to a staff-only channel.
