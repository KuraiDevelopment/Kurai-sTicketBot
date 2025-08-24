import aiosqlite
from typing import Optional, List, Dict, Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    username TEXT NOT NULL,
    reason TEXT NOT NULL,
    guild_id INTEGER NOT NULL,
    thread_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'open', -- open | claimed | closed
    claimed_by INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id INTEGER NOT NULL,
    message TEXT NOT NULL,
    created_by TEXT NOT NULL, -- who queued it (staff name or dashboard)
    delivered INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_tickets_thread ON tickets(thread_id);
CREATE INDEX IF NOT EXISTS idx_outbox_thread_delivered ON outbox(thread_id, delivered);
"""

async def ensure_schema(db_path: str):
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(SCHEMA)
        await db.commit()

async def add_ticket(db_path: str, user_id: int, username: str, reason: str, guild_id: int, thread_id: int):
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "INSERT INTO tickets (user_id, username, reason, guild_id, thread_id, status) VALUES (?, ?, ?, ?, ?, 'open')",
            (user_id, username, reason, guild_id, thread_id)
        )
        await db.commit()

async def set_ticket_status(db_path: str, thread_id: int, status: str, claimed_by: Optional[int] = None):
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "UPDATE tickets SET status = ?, claimed_by = COALESCE(?, claimed_by), updated_at = CURRENT_TIMESTAMP WHERE thread_id = ?",
            (status, claimed_by, thread_id)
        )
        await db.commit()

async def get_ticket_by_thread(db_path: str, thread_id: int) -> Optional[Dict[str, Any]]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM tickets WHERE thread_id = ?", (thread_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

async def list_tickets(db_path: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        if status:
            query = "SELECT * FROM tickets WHERE status = ? ORDER BY created_at DESC"
            params = (status,)
        else:
            query = "SELECT * FROM tickets ORDER BY created_at DESC"
            params = ()
        async with db.execute(query, params) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

async def queue_message(db_path: str, thread_id: int, message: str, created_by: str = "dashboard"):
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "INSERT INTO outbox (thread_id, message, created_by, delivered) VALUES (?, ?, ?, 0)",
            (thread_id, message, created_by)
        )
        await db.commit()

async def fetch_outbox(db_path: str):
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM outbox WHERE delivered = 0 ORDER BY created_at ASC") as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

async def mark_outbox_delivered(db_path: str, outbox_id: int):
    async with aiosqlite.connect(db_path) as db:
        await db.execute("UPDATE outbox SET delivered = 1 WHERE id = ?", (outbox_id,))
        await db.commit()
