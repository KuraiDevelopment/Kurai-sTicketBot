
import os
import asyncio
import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv
import tomllib
from typing import Optional, List, Dict

from db import ensure_schema, add_ticket_full, set_ticket_status, fetch_outbox, mark_outbox_delivered
from integrations import enrich_context

load_dotenv()
CONFIG_PATH = "config.toml" if os.path.exists("config.toml") else "config.example.toml"
with open(CONFIG_PATH, "rb") as f:
    cfg = tomllib.load(f)

DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN") or cfg["discord"]["bot_token"]
GUILD_ID = int(cfg["discord"]["guild_id"])
SUPPORT_CHANNEL_ID = int(cfg["discord"]["support_channel_id"])
STAFF_ROLE_ID = int(cfg["discord"]["staff_role_id"])
DB_PATH = cfg["app"]["db_path"]

FORUM_CHANNEL_ID = int(cfg.get("forum_channel_id", 0) or 0)
PING_ROLE_IDS: List[int] = list(cfg.get("ping_role_ids", []))

CATEGORY_MAP: Dict[str, int] = dict(cfg.get("ticket_categories", {}))

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

def allowed_mentions():
    return discord.AllowedMentions(everyone=False, users=True, roles=True, replied_user=False)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    await ensure_schema(DB_PATH)
    try:
        await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
        print("Slash commands synced to guild.")
    except Exception as e:
        print("Command sync failed:", e)
    outbox_worker.start()

# ---------- UI Components ----------

class CategorySelect(discord.ui.Select):
    def __init__(self, categories: List[str]):
        options = [discord.SelectOption(label=c, value=c) for c in categories]
        super().__init__(placeholder="Choose a ticket category…", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        view: TicketPanelView = self.view  # type: ignore
        view.selected_category = self.values[0]
        # Trigger modal to collect info
        await interaction.response.send_modal(TicketInfoModal(view.selected_category))

class OpenTicketButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Open Ticket", style=discord.ButtonStyle.primary, custom_id="open_ticket_btn")

    async def callback(self, interaction: discord.Interaction):
        view: TicketPanelView = self.view  # type: ignore
        if not view.categories:
            await interaction.response.send_message("No categories configured.", ephemeral=True)
            return
        # Replace the message with the select menu
        select_view = TicketPanelView(view.categories)
        await interaction.response.send_message("Select a category to begin:", view=select_view, ephemeral=True)

class TicketPanelView(discord.ui.View):
    def __init__(self, categories: List[str]):
        super().__init__(timeout=None)
        self.categories = categories
        self.selected_category: Optional[str] = None
        self.add_item(OpenTicketButton())
        # We keep the select hidden until user presses the button (served ephemerally)

class TicketInfoModal(discord.ui.Modal, title="Ticket Info"):
    category: Optional[str] = None

    reason = discord.ui.TextInput(label="Describe your issue", style=discord.TextStyle.paragraph, max_length=1000, required=True, placeholder="What happened? Steps to reproduce?")
    steam_id = discord.ui.TextInput(label="Steam ID / Profile URL", required=False, max_length=200, placeholder="Optional but helpful")
    kofi = discord.ui.TextInput(label="Ko-fi Handle/Link", required=False, max_length=200, placeholder="If you've supported the server")
    cftools = discord.ui.TextInput(label="CF-Tools ID/Link", required=False, max_length=200, placeholder="Optional")
    
    def __init__(self, category: str):
        super().__init__()
        self.category = category

    async def on_submit(self, interaction: discord.Interaction):
        user = interaction.user
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("This must be used in a server.", ephemeral=True)
            return
        category_name = self.category or "Uncategorized"
        parent_target_id = CATEGORY_MAP.get(category_name)

        # Create private channel under mapped category (if provided)
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        }
        staff_role = guild.get_role(STAFF_ROLE_ID)
        if staff_role:
            overwrites[staff_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_channels=True)

        created_channel = None
        if parent_target_id:
            parent = guild.get_channel(parent_target_id)
            try:
                created_channel = await guild.create_text_channel(
                    name=f"ticket-{user.display_name[:20]}",
                    category=parent if isinstance(parent, discord.CategoryChannel) else None,
                    overwrites=overwrites
                )
            except Exception as e:
                print("Channel create failed:", e)
        
        # Fallback: create a public thread in support channel
        created_thread = None
        support_channel = bot.get_channel(SUPPORT_CHANNEL_ID)
        if created_channel is None and isinstance(support_channel, (discord.TextChannel,)):
            try:
                created_thread = await support_channel.create_thread(
                    name=f"🎫 {user.display_name} • {category_name}",
                    type=discord.ChannelType.public_thread,
                    reason=f"Ticket by {user}"
                )
            except Exception as e:
                print("Thread create failed:", e)

        # Optional forum post
        forum_post = None
        if FORUM_CHANNEL_ID:
            forum = bot.get_channel(FORUM_CHANNEL_ID)
            if isinstance(forum, discord.ForumChannel):
                try:
                    forum_post = await forum.create_thread(
                        name=f"{user.display_name} • {category_name}",
                        content=f"**Issue:** {self.reason}\n**Steam:** {self.steam_id}\n**Ko-fi:** {self.kofi}\n**CF-Tools:** {self.cftools}",
                    )
                except Exception as e:
                    print("Forum post failed:", e)

        # Enrich context (stubbed)
        ctx = await enrich_context(str(self.kofi), str(self.steam_id), str(self.cftools))

        # Compose intro
        intro = (
            f"Hello {user.mention}, thanks for opening a ticket.\n"
            f"**Category:** {discord.utils.escape_markdown(category_name)}\n"
            f"**Issue:** {self.reason}\n"
        )
        if self.steam_id:
            intro += f"**Steam:** {self.steam_id}\n"
        if self.kofi:
            intro += f"**Ko-fi:** {self.kofi}\n"
        if self.cftools:
            intro += f"**CF-Tools:** {self.cftools}\n"

        # Ping roles
        role_mentions = " ".join([f"<@&{rid}>" for rid in PING_ROLE_IDS]) if PING_ROLE_IDS else ""

        # Send intro to the created destination
        thread_id = 0
        channel_id = 0
        forum_id = 0

        if created_channel:
            try:
                await created_channel.send(role_mentions + "\n" + intro, allowed_mentions=allowed_mentions())
            except Exception:
                pass
            channel_id = created_channel.id
        elif created_thread:
            try:
                await created_thread.send(role_mentions + "\n" + intro, allowed_mentions=allowed_mentions())
            except Exception:
                pass
            thread_id = created_thread.id
        else:
            await interaction.response.send_message("Failed to create a ticket channel or thread. Please contact staff.", ephemeral=True)
            return

        if forum_post:
            forum_id = forum_post.id if hasattr(forum_post, "id") else 0

        # Save to DB
        await add_ticket_full(
            DB_PATH,
            user_id=user.id,
            username=str(user),
            reason=str(self.reason),
            guild_id=guild.id,
            thread_id=thread_id or None,
            channel_id=channel_id or None,
            forum_post_id=forum_id or None,
            category=category_name,
            ko_fi=str(self.kofi) if self.kofi else None,
            steam_id=str(self.steam_id) if self.steam_id else None,
            cftools_id=str(self.cftools) if self.cftools else None,
        )

        # Acknowledge
        if created_channel:
            await interaction.response.send_message(f"Ticket created: {created_channel.mention}", ephemeral=True)
        else:
            await interaction.response.send_message(f"Ticket created: <#{thread_id}>", ephemeral=True)

# ---------- Commands ----------

@bot.tree.command(name="ticket_panel", description="Post the ticket panel", guild=discord.Object(id=GUILD_ID))
async def ticket_panel(interaction: discord.Interaction):
    categories = list(CATEGORY_MAP.keys())
    if not categories:
        await interaction.response.send_message("No categories configured in config.toml [ticket_categories].", ephemeral=True)
        return
    embed = discord.Embed(title="Tactica DayZ • Support", description="Open a ticket to reach the staff team. Click the button below.", color=0x2b2d31)
    view = TicketPanelView(categories)
    await interaction.response.send_message(embed=embed, view=view)
    
@bot.tree.command(name="ticket_claim", description="Claim the current ticket", guild=discord.Object(id=GUILD_ID))
async def ticket_claim(interaction: discord.Interaction):
    ch = interaction.channel
    if not isinstance(ch, (discord.TextChannel, discord.Thread)):
        await interaction.response.send_message("Use this inside the ticket channel/thread.", ephemeral=True)
        return
    member = interaction.user
    if isinstance(member, discord.Member):
        if STAFF_ROLE_ID not in [r.id for r in member.roles]:
            await interaction.response.send_message("You need the staff role to claim tickets.", ephemeral=True)
            return
    target_id = ch.id if isinstance(ch, discord.TextChannel) else ch.id
    await set_ticket_status(DB_PATH, target_id, "claimed", claimed_by=interaction.user.id)
    await ch.send(f"{member.mention} has claimed this ticket.")
    await interaction.response.send_message("Ticket claimed.", ephemeral=True)

@bot.tree.command(name="ticket_close", description="Close the current ticket", guild=discord.Object(id=GUILD_ID))
async def ticket_close(interaction: discord.Interaction):
    ch = interaction.channel
    if not isinstance(ch, (discord.TextChannel, discord.Thread)):
        await interaction.response.send_message("Use this inside the ticket channel/thread.", ephemeral=True)
        return
    await set_ticket_status(DB_PATH, ch.id, "closed")
    await ch.send("This ticket is now closed. If you need anything else, open a new one with `/ticket_panel`.")
    await interaction.response.send_message("Closed.", ephemeral=True)
    try:
        if isinstance(ch, discord.Thread):
            await ch.archive(locked=True)
        elif isinstance(ch, discord.TextChannel):
            await ch.edit(archived=True)  # not valid; left as placeholder. You may delete channel instead.
    except Exception:
        pass

@tasks.loop(seconds=5)
async def outbox_worker():
    try:
        pending = await fetch_outbox(DB_PATH)
        for row in pending:
            target_id = int(row["thread_id"]) if row["thread_id"] else None
            channel = None
            if target_id:
                channel = bot.get_channel(target_id)
                if channel is None:
                    try:
                        channel = await bot.fetch_channel(target_id)
                    except Exception:
                        channel = None
            if channel is None and row.get("thread_id", 0) == 0 and row.get("channel_id", 0):
                # Fallback if schema extends later
                channel = bot.get_channel(int(row["channel_id"]))

            if channel is not None:
                try:
                    await channel.send(row["message"])
                    await mark_outbox_delivered(DB_PATH, row["id"])
                except Exception as e:
                    print("Failed to deliver:", e)
    except Exception as e:
        print("Outbox worker error:", e)

if __name__ == "__main__":
    asyncio.run(bot.start(DISCORD_TOKEN))
