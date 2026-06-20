import discord
from discord import app_commands
from discord.ext import commands, tasks
import json
import os
import asyncio
from datetime import datetime, timedelta
from collections import defaultdict

# ============================================================
#  DISCORD AUTO-MOD & WELCOME BOT
#  Setup: Set DISCORD_TOKEN env var, run the bot
#  Commands: /setup, /warn, /warnings, /clearwarns, /kick, /ban, /unban
# ============================================================

TOKEN = os.environ.get("DISCORD_TOKEN", "")
DEFAULT_PREFIX = "!"

# ==================== DATA STORAGE ====================

DATA_FILE = "bot_data.json"

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {
        "guilds": {},
        "warnings": {},
        "mute_roles": {},
        "log_channels": {}
    }

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

data = load_data()

# ==================== BOT SETUP ====================

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.guilds = True
intents.bans = True

class AutoModBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix=DEFAULT_PREFIX,
            intents=intents,
            help_command=None
        )
        self.spam_tracker = defaultdict(lambda: defaultdict(list))
        self.invite_tracker = defaultdict(set)

    async def setup_hook(self):
        await self.tree.sync()
        self.auto_unmute.start()
        print("Bot is ready and slash commands synced!")

bot = AutoModBot()

# ==================== HELPER FUNCTIONS ====================

def get_guild_config(guild_id):
    gid = str(guild_id)
    if gid not in data["guilds"]:
        data["guilds"][gid] = {
            "welcome_channel": None,
            "welcome_message": "Welcome {member} to {server}! 🎉",
            "welcome_enabled": False,
            "auto_mod_enabled": False,
            "max_warnings": 3,
            "spam_threshold": 5,
            "spam_interval": 5,
            "caps_threshold": 70,
            "link_filter": False,
            "invite_filter": False,
            "profanity_filter": False,
            "muted_role": None,
            "log_channel": None
        }
        save_data(data)
    return data["guilds"][gid]

def get_warnings(guild_id, user_id):
    gid, uid = str(guild_id), str(user_id)
    if gid not in data["warnings"]:
        data["warnings"][gid] = {}
    if uid not in data["warnings"][gid]:
        data["warnings"][gid][uid] = []
    return data["warnings"][gid][uid]

def add_warning(guild_id, user_id, reason, moderator_id):
    warnings = get_warnings(guild_id, user_id)
    warnings.append({
        "reason": reason,
        "moderator": moderator_id,
        "timestamp": datetime.now().isoformat()
    })
    save_data(data)
    return len(warnings)

def clear_warnings(guild_id, user_id):
    gid, uid = str(guild_id), str(user_id)
    if gid in data["warnings"] and uid in data["warnings"][gid]:
        data["warnings"][gid][uid] = []
        save_data(data)

BAD_WORDS = {
    "badword1", "badword2", "slur1", "slur2"
}

def contains_profanity(text):
    words = text.lower().split()
    return any(word in BAD_WORDS for word in words)

def is_caps_spam(text):
    if len(text) < 8:
        return False
    caps = sum(1 for c in text if c.isupper())
    return (caps / len(text)) * 100 > 70

# ==================== SLASH COMMANDS ====================

@bot.tree.command(name="setup", description="Configure the bot for this server")
@app_commands.describe(
    welcome_channel="Channel for welcome messages",
    log_channel="Channel for moderation logs",
    max_warnings="Warnings before auto-ban (default: 3)",
    auto_mod="Enable auto-moderation",
    welcome="Enable welcome messages"
)
@app_commands.checks.has_permissions(administrator=True)
async def setup(
    interaction: discord.Interaction,
    welcome_channel: discord.TextChannel = None,
    log_channel: discord.TextChannel = None,
    max_warnings: int = 3,
    auto_mod: bool = False,
    welcome: bool = False
):
    config = get_guild_config(interaction.guild.id)

    if welcome_channel:
        config["welcome_channel"] = welcome_channel.id
    if log_channel:
        config["log_channel"] = log_channel.id
    config["max_warnings"] = max(max_warnings, 1)
    config["auto_mod_enabled"] = auto_mod
    config["welcome_enabled"] = welcome

    save_data(data)

    embed = discord.Embed(
        title="⚙️ Bot Configuration",
        color=discord.Color.blue(),
        timestamp=datetime.now()
    )
    embed.add_field(name="Welcome Channel", value=welcome_channel.mention if welcome_channel else "Not set", inline=True)
    embed.add_field(name="Log Channel", value=log_channel.mention if log_channel else "Not set", inline=True)
    embed.add_field(name="Max Warnings", value=str(config["max_warnings"]), inline=True)
    embed.add_field(name="Auto-Mod", value="✅ Enabled" if auto_mod else "❌ Disabled", inline=True)
    embed.add_field(name="Welcome", value="✅ Enabled" if welcome else "❌ Disabled", inline=True)

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="automod_settings", description="Configure auto-moderation filters")
@app_commands.checks.has_permissions(administrator=True)
async def automod_settings(
    interaction: discord.Interaction,
    spam_filter: bool = None,
    caps_filter: bool = None,
    link_filter: bool = None,
    invite_filter: bool = None,
    profanity_filter: bool = None,
    spam_threshold: int = None,
    spam_interval_seconds: int = None
):
    config = get_guild_config(interaction.guild.id)

    changes = []
    if spam_filter is not None:
        config["spam_filter"] = spam_filter
        changes.append(f"Spam Filter: {'✅' if spam_filter else '❌'}")
    if caps_filter is not None:
        config["caps_filter"] = caps_filter
        changes.append(f"Caps Filter: {'✅' if caps_filter else '❌'}")
    if link_filter is not None:
        config["link_filter"] = link_filter
        changes.append(f"Link Filter: {'✅' if link_filter else '❌'}")
    if invite_filter is not None:
        config["invite_filter"] = invite_filter
        changes.append(f"Invite Filter: {'✅' if invite_filter else '❌'}")
    if profanity_filter is not None:
        config["profanity_filter"] = profanity_filter
        changes.append(f"Profanity Filter: {'✅' if profanity_filter else '❌'}")
    if spam_threshold is not None:
        config["spam_threshold"] = max(2, spam_threshold)
        changes.append(f"Spam Threshold: {spam_threshold} msgs")
    if spam_interval_seconds is not None:
        config["spam_interval"] = max(1, spam_interval_seconds)
        changes.append(f"Spam Interval: {spam_interval_seconds}s")

    save_data(data)

    if not changes:
        embed = discord.Embed(title="🔧 Current Auto-Mod Settings", color=discord.Color.blue())
        for key, val in config.items():
            if "filter" in key or "threshold" in key or "interval" in key:
                embed.add_field(name=key.replace("_", " ").title(), value=str(val), inline=True)
        await interaction.response.send_message(embed=embed)
    else:
        embed = discord.Embed(title="✅ Settings Updated", description="\n".join(changes), color=discord.Color.green())
        await interaction.response.send_message(embed=embed)

@bot.tree.command(name="warn", description="Warn a user")
@app_commands.checks.has_permissions(kick_members=True)
async def warn(interaction: discord.Interaction, user: discord.Member, reason: str = "No reason provided"):
    if user.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id:
        return await interaction.response.send_message("❌ You cannot warn someone with a higher or equal role!", ephemeral=True)

    config = get_guild_config(interaction.guild.id)
    warn_count = add_warning(interaction.guild.id, user.id, reason, interaction.user.id)

    if warn_count >= config["max_warnings"]:
        try:
            await user.ban(reason=f"Auto-banned: Reached {config['max_warnings']} warnings")
            await interaction.response.send_message(
                f"⚠️ **{user.mention}** has been **AUTO-BANNED** for reaching {warn_count} warnings!\n"
                f"Final warning reason: {reason}"
            )
        except discord.Forbidden:
            await interaction.response.send_message(f"❌ Could not auto-ban {user.mention}. Check permissions.", ephemeral=True)
        return

    embed = discord.Embed(
        title="⚠️ User Warned",
        color=discord.Color.orange(),
        timestamp=datetime.now()
    )
    embed.add_field(name="User", value=user.mention, inline=True)
    embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)
    embed.add_field(name="Warning #", value=str(warn_count), inline=True)
    embed.add_field(name="Reason", value=reason, inline=False)
    embed.add_field(name="Max Warnings", value=str(config["max_warnings"]), inline=True)

    await interaction.response.send_message(embed=embed)
    await log_action(interaction.guild, "Warning Issued", f"{user.mention} warned by {interaction.user.mention}\nReason: {reason}\nCount: {warn_count}/{config['max_warnings']}")

@bot.tree.command(name="warnings", description="Check a user's warnings")
async def warnings(interaction: discord.Interaction, user: discord.Member = None):
    target = user or interaction.user
    warns = get_warnings(interaction.guild.id, target.id)

    embed = discord.Embed(
        title=f"⚠️ Warnings for {target.display_name}",
        color=discord.Color.orange()
    )

    if not warns:
        embed.description = "No warnings found! ✅"
    else:
        for i, w in enumerate(warns, 1):
            mod = interaction.guild.get_member(w["moderator"])
            mod_name = mod.mention if mod else "Unknown"
            embed.add_field(
                name=f"Warning #{i}",
                value=f"**Reason:** {w['reason']}\n**By:** {mod_name}\n**Date:** {w['timestamp'][:10]}",
                inline=False
            )

    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="clearwarns", description="Clear all warnings for a user")
@app_commands.checks.has_permissions(administrator=True)
async def clearwarns(interaction: discord.Interaction, user: discord.Member):
    clear_warnings(interaction.guild.id, user.id)
    await interaction.response.send_message(f"✅ Cleared all warnings for {user.mention}")

@bot.tree.command(name="kick", description="Kick a user from the server")
@app_commands.checks.has_permissions(kick_members=True)
async def kick(interaction: discord.Interaction, user: discord.Member, reason: str = "No reason provided"):
    if user.top_role >= interaction.user.top_role:
        return await interaction.response.send_message("❌ You cannot kick someone with a higher or equal role!", ephemeral=True)

    await user.kick(reason=reason)
    embed = discord.Embed(title="👢 User Kicked", color=discord.Color.red())
    embed.add_field(name="User", value=user.mention, inline=True)
    embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)
    embed.add_field(name="Reason", value=reason, inline=False)

    await interaction.response.send_message(embed=embed)
    await log_action(interaction.guild, "User Kicked", f"{user.mention} kicked by {interaction.user.mention}\nReason: {reason}")

@bot.tree.command(name="ban", description="Ban a user from the server")
@app_commands.checks.has_permissions(ban_members=True)
async def ban(interaction: discord.Interaction, user: discord.Member, reason: str = "No reason provided", delete_messages_days: int = 0):
    if user.top_role >= interaction.user.top_role:
        return await interaction.response.send_message("❌ You cannot ban someone with a higher or equal role!", ephemeral=True)

    await user.ban(reason=reason, delete_message_days=min(delete_messages_days, 7))
    embed = discord.Embed(title="🔨 User Banned", color=discord.Color.dark_red())
    embed.add_field(name="User", value=user.mention, inline=True)
    embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)
    embed.add_field(name="Reason", value=reason, inline=False)

    await interaction.response.send_message(embed=embed)
    await log_action(interaction.guild, "User Banned", f"{user.mention} banned by {interaction.user.mention}\nReason: {reason}")

@bot.tree.command(name="unban", description="Unban a user")
@app_commands.checks.has_permissions(ban_members=True)
async def unban(interaction: discord.Interaction, user_id: str, reason: str = "No reason provided"):
    try:
        uid = int(user_id)
        user = await bot.fetch_user(uid)
        await interaction.guild.unban(user, reason=reason)
        await interaction.response.send_message(f"✅ Unbanned {user.mention}")
        await log_action(interaction.guild, "User Unbanned", f"{user.mention} unbanned by {interaction.user.mention}")
    except (ValueError, discord.NotFound):
        await interaction.response.send_message("❌ Invalid user ID or user not banned.", ephemeral=True)

@bot.tree.command(name="mute", description="Timeout/mute a user")
@app_commands.checks.has_permissions(moderate_members=True)
async def mute(interaction: discord.Interaction, user: discord.Member, duration_minutes: int, reason: str = "No reason provided"):
    if user.top_role >= interaction.user.top_role:
        return await interaction.response.send_message("❌ You cannot mute someone with a higher or equal role!", ephemeral=True)

    duration = timedelta(minutes=duration_minutes)
    until = datetime.now() + duration

    await user.timeout(until, reason=reason)
    embed = discord.Embed(title="🔇 User Muted", color=discord.Color.yellow())
    embed.add_field(name="User", value=user.mention, inline=True)
    embed.add_field(name="Duration", value=f"{duration_minutes} minutes", inline=True)
    embed.add_field(name="Until", value=until.strftime("%H:%M:%S"), inline=True)
    embed.add_field(name="Reason", value=reason, inline=False)

    await interaction.response.send_message(embed=embed)
    await log_action(interaction.guild, "User Muted", f"{user.mention} muted for {duration_minutes}m by {interaction.user.mention}")

@bot.tree.command(name="unmute", description="Remove timeout from a user")
@app_commands.checks.has_permissions(moderate_members=True)
async def unmute(interaction: discord.Interaction, user: discord.Member):
    await user.timeout(None)
    await interaction.response.send_message(f"✅ {user.mention} has been unmuted.")

@bot.tree.command(name="setwelcome", description="Set a custom welcome message")
@app_commands.checks.has_permissions(administrator=True)
async def setwelcome(interaction: discord.Interaction, message: str):
    config = get_guild_config(interaction.guild.id)
    config["welcome_message"] = message
    save_data(data)

    preview = message.replace("{member}", interaction.user.mention).replace("{server}", interaction.guild.name)
    await interaction.response.send_message(
        f"✅ Welcome message set!\n\n**Preview:**\n{preview}\n\n"
        f"**Variables:** `{{member}}` = user mention, `{{server}}` = server name, `{{count}}` = member count"
    )

# ==================== AUTO-MODERATION ====================

async def log_action(guild, action, description):
    config = get_guild_config(guild.id)
    if config.get("log_channel"):
        channel = guild.get_channel(config["log_channel"])
        if channel:
            embed = discord.Embed(
                title=f"🛡️ {action}",
                description=description,
                color=discord.Color.purple(),
                timestamp=datetime.now()
            )
            await channel.send(embed=embed)

async def auto_mod_check(message):
    if message.author.bot or not message.guild:
        return False

    config = get_guild_config(message.guild.id)
    if not config.get("auto_mod_enabled", False):
        return False

    content = message.content
    deleted = False
    reason = None

    if config.get("spam_filter", False):
        now = datetime.now()
        user_spam = bot.spam_tracker[message.guild.id][message.author.id]
        user_spam.append(now)

        interval = config.get("spam_interval", 5)
        threshold = config.get("spam_threshold", 5)
        user_spam[:] = [t for t in user_spam if (now - t).total_seconds() <= interval]

        if len(user_spam) >= threshold:
            reason = "Spam detected"
            try:
                await message.delete()
                deleted = True
                await message.channel.send(f"🚫 {message.author.mention} Stop spamming!", delete_after=5)
            except discord.Forbidden:
                pass

    if not deleted and config.get("caps_filter", False) and is_caps_spam(content):
        reason = "Excessive caps"
        try:
            await message.delete()
            deleted = True
            await message.channel.send(f"🚫 {message.author.mention} Please don't shout!", delete_after=5)
        except discord.Forbidden:
            pass

    if not deleted and config.get("link_filter", False):
        if "http://" in content or "https://" in content or "www." in content:
            if not message.author.guild_permissions.manage_messages:
                reason = "Unauthorized link"
                try:
                    await message.delete()
                    deleted = True
                    await message.channel.send(f"🚫 {message.author.mention} Links are not allowed!", delete_after=5)
                except discord.Forbidden:
                    pass

    if not deleted and config.get("invite_filter", False):
        if "discord.gg/" in content or "discord.com/invite/" in content:
            if not message.author.guild_permissions.manage_messages:
                reason = "Unauthorized invite"
                try:
                    await message.delete()
                    deleted = True
                    await message.channel.send(f"🚫 {message.author.mention} Invite links are not allowed!", delete_after=5)
                except discord.Forbidden:
                    pass

    if not deleted and config.get("profanity_filter", False) and contains_profanity(content):
        reason = "Inappropriate language"
        try:
            await message.delete()
            deleted = True
            await message.channel.send(f"🚫 {message.author.mention} Watch your language!", delete_after=5)
        except discord.Forbidden:
            pass

    if deleted and reason:
        await log_action(message.guild, "Auto-Mod Action", 
            f"Message by {message.author.mention} deleted in {message.channel.mention}\n"
            f"**Reason:** {reason}\n**Content:** {content[:500]}")

    return deleted

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    await auto_mod_check(message)
    await bot.process_commands(message)

# ==================== WELCOME SYSTEM ====================

@bot.event
async def on_member_join(member):
    config = get_guild_config(member.guild.id)

    if not config.get("welcome_enabled", False):
        return

    welcome_channel_id = config.get("welcome_channel")
    if not welcome_channel_id:
        return

    channel = member.guild.get_channel(welcome_channel_id)
    if not channel:
        return

    welcome_msg = config.get("welcome_message", "Welcome {member} to {server}!")
    welcome_msg = welcome_msg.replace("{member}", member.mention)
    welcome_msg = welcome_msg.replace("{server}", member.guild.name)
    welcome_msg = welcome_msg.replace("{count}", str(member.guild.member_count))

    embed = discord.Embed(
        title="🎉 Welcome!",
        description=welcome_msg,
        color=discord.Color.green(),
        timestamp=datetime.now()
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text=f"Member #{member.guild.member_count}")

    await channel.send(embed=embed)
    await log_action(member.guild, "Member Joined", f"{member.mention} joined the server.\nAccount created: {member.created_at.strftime('%Y-%m-%d')}")

@bot.event
async def on_member_remove(member):
    await log_action(member.guild, "Member Left", f"{member.mention} ({member}) left the server.")

# ==================== AUTO UNMUTE TASK ====================

@tasks.loop(minutes=1)
async def auto_unmute():
    pass

# ==================== ERROR HANDLING ====================

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ You don't have permission to use this command!")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Missing argument: {error.param.name}")
    else:
        print(f"Command error: {error}")

@setup.error
@automod_settings.error
@warn.error
@clearwarns.error
@kick.error
@ban.error
@mute.error
@unmute.error
@setwelcome.error
async def slash_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("❌ You don't have permission to use this command!", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ An error occurred: {str(error)}", ephemeral=True)

# ==================== RUN BOT ====================

@bot.event
async def on_ready():
    print(f"🤖 Logged in as {bot.user} (ID: {bot.user.id})")
    print(f"📊 Connected to {len(bot.guilds)} guilds")
    print("=" * 50)
    print("Slash Commands Available:")
    print("  /setup - Configure the bot")
    print("  /automod_settings - Configure filters")
    print("  /warn - Warn a user")
    print("  /warnings - Check warnings")
    print("  /clearwarns - Clear warnings")
    print("  /kick - Kick user")
    print("  /ban - Ban user")
    print("  /unban - Unban user")
    print("  /mute - Timeout user")
    print("  /unmute - Remove timeout")
    print("  /setwelcome - Custom welcome message")
    print("=" * 50)

if __name__ == "__main__":
    if not TOKEN:
        print("❌ ERROR: Please set the DISCORD_TOKEN environment variable!")
        print("Get one at: https://discord.com/developers/applications")
    else:
        bot.run(TOKEN)
