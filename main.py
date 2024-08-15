import os
from dotenv import load_dotenv
import discord
from discord.ext import commands, tasks
import requests
from datetime import datetime, timedelta
import schedule
import time
import logging
import threading

# Configure logging
logging.basicConfig(level=logging.DEBUG)

load_dotenv()
token = os.getenv('DISCORD_BOT_TOKEN')

# Define intents
intents = discord.Intents.default()
intents.message_content = True

# Define the bot with command prefix and intents
bot = commands.Bot(command_prefix='!', intents=intents)

announcement_channels = {}
ANILIST_API_URL = "https://graphql.anilist.co"


def fetch_upcoming_anime():
    url = ANILIST_API_URL
    query = """
    query($page: Int, $perPage: Int) {
        Page(page: $page, perPage: $perPage) {
            airingSchedules(notYetAired: true, sort: [TIME]) {
                id
                episode
                airingAt
                media {
                    id
                    title {
                        romaji
                        english
                    }
                }
            }
        }
    }
    """
    variables = {
        "page": 1,
        "perPage": 10
    }
    try:
        response = requests.post(ANILIST_API_URL, json={'query': query, 'variables': variables})
        response.raise_for_status()
        data = response.json()
        logging.debug(f"Received data: {data}")
        return data.get('data', {}).get('Page', {}).get('airingSchedules', [])
    except requests.exceptions.RequestException as e:
        logging.error(f"API request failed: {e}")
        return None


# Send alert to Discord
async def send_alert(guild_id, alert_message):
    channel_id = announcement_channels.get(guild_id)
    if not channel_id:
        logging.error(f"No announcement channel set for guild {guild_id}.")
        return

    channel = bot.get_channel(channel_id)
    if channel:
        await channel.send(alert_message)
    else:
        logging.error(f"Channel with ID {channel_id} not found in guild {guild_id}.")


# Schedule alerts 24 hours before each episode airs
def schedule_alerts():
    upcoming_anime = fetch_upcoming_anime()
    if upcoming_anime is None:
        logging.error("Failed to fetch upcoming anime data. Skipping scheduling.")
        return

    for anime in upcoming_anime:
        title = anime['media']['title']['romaji'] or anime['media']['title']['english']
        airing_time = datetime.fromtimestamp(anime['airingAt'])
        alert_time = airing_time - timedelta(hours=24)
        alert_message = f"Reminder: **{title}** (Episode {anime['episode']}) will air at {airing_time.strftime('%d/%m/%Y at %H:%M')}!"

        for guild_id in announcement_channels.keys():
            schedule.every().day.at(alert_time.strftime("%H:%M")).do(
                lambda msg=alert_message, gid=guild_id: bot.loop.create_task(send_alert(gid, msg))
            )
    logging.info("Scheduled alerts 24 hours before upcoming anime.")


# Create a report of all upcoming episodes for the week
async def send_weekly_report():
    upcoming_anime = fetch_upcoming_anime()
    if upcoming_anime is None:
        logging.error("Failed to fetch upcoming anime data for the week.")
        return

    now = datetime.now()
    week_later = now + timedelta(days=7)
    weekly_anime = [anime for anime in upcoming_anime if now <= datetime.fromtimestamp(anime['airingAt']) <= week_later]

    if not weekly_anime:
        report_message = "No anime episodes are scheduled to air this week."
    else:
        report_message = "Here are the anime episodes airing this week:\n"
        for anime in weekly_anime:
            title = anime['media']['title']['romaji'] or anime['media']['title']['english']
            airing_time = datetime.fromtimestamp(anime['airingAt'])
            report_message += f"- **{title}** (Episode {anime['episode']}) airing at {airing_time.strftime('%d/%m/%Y at %H:%M')}\n"

    for guild_id in announcement_channels.keys():
        await send_alert(guild_id, report_message)


@tasks.loop(hours=24)
async def weekly_summary():
    today = datetime.utcnow().date()
    if today.weekday() == 6:
        await send_weekly_report()


@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')
    schedule_alerts()
    weekly_summary.start()

    schedule.every().sunday.at("10:00").do(lambda: bot.loop.create_task(send_weekly_report()))
    logging.info("Bot is ready and scheduling tasks.")


@bot.command(name='setchannel')
@commands.has_permissions(administrator=True)
async def set_channel(ctx, channel: discord.TextChannel):
    """Sets the announcement channel for the bot."""
    announcement_channels[ctx.guild.id] = channel.id
    await ctx.send(f"Announcement channel set to {channel.mention}.")


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.errors.MissingPermissions):
        await ctx.send("You don't have the required permissions to use this command.")
    elif isinstance(error, commands.errors.BadArgument):
        await ctx.send("Invalid argument. Please provide a valid channel.")
    elif isinstance(error, commands.errors.CommandNotFound):
        await ctx.send("Command not found.")
    else:
        await ctx.send("An error occurred. Please try again.")


# Run the schedule in a separate thread
def run_schedule():
    while True:
        schedule.run_pending()
        time.sleep(1)


schedule_thread = threading.Thread(target=run_schedule)
schedule_thread.start()


@bot.command(name='hello')
async def hello(ctx):
    """Responds with a greeting message."""
    await ctx.send(f"Hello, {ctx.author.mention}! How can I assist you today?")


@bot.command(name='upcoming')
async def upcoming_anime(ctx):
    """Fetches and sends a list of upcoming anime."""
    upcoming_anime = fetch_upcoming_anime()
    if upcoming_anime is None:
        await ctx.send("Sorry, I couldn't fetch the upcoming anime schedule.")
        return

    if not upcoming_anime:
        await ctx.send("No upcoming animes.")
        return

    message = "Here are the upcoming anime:\n"
    for anime in upcoming_anime:
        title = anime['media']['title']['romaji'] or anime['media']['title']['english']
        airing_time = datetime.fromtimestamp(anime['airingAt'])
        message += f"- **{title}** (Episode {anime['episode']}) airing at {airing_time.strftime('%d/%m/%Y at %H:%M')}\n"

    await ctx.send(message)


bot.run(token)
