import os
import asyncio
import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv
import tomllib

from db import ensure_schema, add_ticket, set_ticket_status, fetch_outbox, mark_outbox_delivered

# Load config
load_dotenv()
CONFIG_PATH = "config.toml" if os.path.exists("config.toml") else "config.example.toml"

with open(CONFIG_PATH, "rb") as f:
    cfg = tomllib.load(f)

DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN") or cfg["discord"]["bot_token"]
GUILD_ID = int(cfg["discord"]["guild_id"])
SUPPORT_CHANNEL_ID = int(cfg["discord"]["support_channel_id"])
STAFF_ROLE_ID = int(cfg["discord"]["staff_role_id"])
DB_PATH = cfg["app"]["db_path"]

intents = discord.Intents.default()
intents.message_content = False
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    await ensure_schema(DB_PATH)
    try:
        guild = discord.Object(id=GUILD_ID)
        await bot.tree.sync(guild=guild)
        print("Slash commands synced to guild.")
    except Exception as e:
        print("Command sync failed:", e)
    outbox_worker.start()

def get_support_channel():
    return bot.get_channel(SUPPORT_CHANNEL_ID)

@bot.tree.command(name="ticket_open", description="Open a support ticket", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(reason="What do you need help with?")
async def ticket_open(interaction: discord.Interaction, reason: str):
    channel = get_support_channel()
    if channel is None:
        await interaction.response.send_message("Support channel is not configured or not found.", ephemeral=True)
        return

    thread = await channel.create_thread(
        name=f"🎫 {interaction.user.display_name}",
        type=discord.ChannelType.public_thread,
        reason=f"Ticket by {interaction.user}"
    )

    await thread.send(f"Hello {interaction.user.mention}, thanks for opening a ticket. A staff member will be with you shortly.\n**Reason:** {reason}")
    await add_ticket(DB_PATH, interaction.user.id, str(interaction.user), reason, interaction.guild_id, thread.id)
    await interaction.response.send_message(f"Ticket created: {thread.mention}", ephemeral=True)

@bot.tree.command(name="ticket_claim", description="Claim the current ticket", guild=discord.Object(id=GUILD_ID))
async def ticket_claim(interaction: discord.Interaction):
    if not isinstance(interaction.channel, discord.Thread):
        await interaction.response.send_message("Use this inside the ticket thread.", ephemeral=True)
        return

    member = interaction.user
    if isinstance(member, discord.Member):
        if STAFF_ROLE_ID not in [r.id for r in member.roles]:
            await interaction.response.send_message("You need the staff role to claim tickets.", ephemeral=True)
            return

    await set_ticket_status(DB_PATH, interaction.channel.id, "claimed", claimed_by=interaction.user.id)
    await interaction.channel.send(f"{interaction.user.mention} has claimed this ticket.")
    await interaction.response.send_message("Ticket claimed.", ephemeral=True)

@bot.tree.command(name="ticket_close", description="Close the current ticket", guild=discord.Object(id=GUILD_ID))
async def ticket_close(interaction: discord.Interaction):
    if not isinstance(interaction.channel, discord.Thread):
        await interaction.response.send_message("Use this inside the ticket thread.", ephemeral=True)
        return

    await set_ticket_status(DB_PATH, interaction.channel.id, "closed")
    await interaction.channel.send("This ticket is now closed. If you need anything else, open a new one with `/ticket_open`.")
    await interaction.response.send_message("Closed.", ephemeral=True)
    try:
        await interaction.channel.archive(locked=True)
    except Exception:
        pass

@tasks.loop(seconds=5)
async def outbox_worker():
    try:
        pending = await fetch_outbox(DB_PATH)
        for row in pending:
            thread_id = int(row["thread_id"])
            thread = bot.get_channel(thread_id)
            if thread is None:
                try:
                    thread = await bot.fetch_channel(thread_id)
                except Exception:
                    thread = None
            if thread is not None:
                try:
                    await thread.send(row["message"])
                    await mark_outbox_delivered(DB_PATH, row["id"])
                except Exception as e:
                    print("Failed to deliver to thread:", thread_id, e)
    except Exception as e:
        print("Outbox worker error:", e)

if __name__ == "__main__":
    asyncio.run(bot.start(DISCORD_TOKEN))
