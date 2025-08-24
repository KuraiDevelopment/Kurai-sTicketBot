import os
import sqlite3
import pandas as pd
import streamlit as st
import tomllib

CONFIG_PATH = "config.toml" if os.path.exists("config.toml") else "config.example.toml"
with open(CONFIG_PATH, "rb") as f:
    cfg = tomllib.load(f)
DB_PATH = cfg["app"]["db_path"]

st.set_page_config(page_title="Discord Ticket Dashboard", layout="wide")
st.title("🎫 Discord Ticket Dashboard")

def read_df(query: str, params=()):
    con = sqlite3.connect(DB_PATH)
    try:
        df = pd.read_sql_query(query, con, params=params)
    finally:
        con.close()
    return df

def list_tickets(status: str | None = None) -> pd.DataFrame:
    if status:
        return read_df("SELECT * FROM tickets WHERE status = ? ORDER BY created_at DESC", (status,))
    else:
        return read_df("SELECT * FROM tickets ORDER BY created_at DESC")

def queue_message(thread_id: int, message: str, created_by: str="dashboard"):
    con = sqlite3.connect(DB_PATH)
    try:
        cur = con.cursor()
        cur.execute(
            "INSERT INTO outbox (thread_id, message, created_by, delivered) VALUES (?, ?, ?, 0)",
            (thread_id, message, created_by)
        )
        con.commit()
    finally:
        con.close()

def set_ticket_status(thread_id: int, status: str):
    con = sqlite3.connect(DB_PATH)
    try:
        cur = con.cursor()
        cur.execute(
            "UPDATE tickets SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE thread_id = ?",
            (status, thread_id)
        )
        con.commit()
    finally:
        con.close()

# Sidebar filters
st.sidebar.header("Filters")
status_filter = st.sidebar.selectbox("Status", options=["all", "open", "claimed", "closed"], index=0)

if status_filter == "all":
    df = list_tickets(None)
else:
    df = list_tickets(status_filter)

st.subheader("Tickets")
if df.empty:
    st.info("No tickets yet.")
else:
    st.dataframe(df, use_container_width=True)

st.subheader("Manage a Ticket")
col1, col2 = st.columns(2)

with col1:
    thread_id = st.text_input("Thread ID", placeholder="Enter the Discord thread ID from the table")
    canned = st.text_area("Message to send (bot will post in the thread)", height=120, placeholder="Type a reply for the user...")
    who = st.text_input("From (label)", value="dashboard")
    send_btn = st.button("Queue Message")
    if send_btn:
        if thread_id and canned:
            try:
                queue_message(int(thread_id), canned, who)
                st.success("Queued! The bot will deliver this in a few seconds.")
            except Exception as e:
                st.error(f"Error: {e}")
        else:
            st.warning("Provide both Thread ID and a message.")

with col2:
    new_status = st.selectbox("Set Status", options=["open", "claimed", "closed"])
    set_status_btn = st.button("Update Status")
    if set_status_btn:
        if thread_id:
            try:
                set_ticket_status(int(thread_id), new_status)
                st.success(f"Status set to {new_status}.")
            except Exception as e:
                st.error(f"Error: {e}")
        else:
            st.warning("Enter a Thread ID first.")

st.caption("Tip: Run the bot and this dashboard at the same time. Both share the same SQLite database for seamless ops.")
