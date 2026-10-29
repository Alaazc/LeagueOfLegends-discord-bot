#comment
import discord
from discord.ext import commands
import logging
from dotenv import load_dotenv
import os
from Scraper import *

load_dotenv()
token = os.getenv("DISCORD_TOKEN")

handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')

intents = discord.Intents.default()
intents.members = True
intents.presences = True
intents.message_content = True
intents.messages = True

bot = commands.Bot(command_prefix='!', intents=intents)
bot.remove_command('help')

async def send_tierlist(ctx, role):
    await ctx.send(f" Fetching tier list...")
    try:
        result = await tierList(role)
        if len(result) > 1900:
            chunks = [result[i:i + 1900] for i in range(0, len(result), 1900)]
            for chunk in chunks:
                await ctx.send(f"```\n{chunk}\n```")
        else:
            await ctx.send(f"```\n{result}\n```")
    except Exception as e:
        await ctx.send(f" Error fetching tier list: `{e}`")

def build_embed(champ: str, role: str, df: pd.DataFrame) -> discord.Embed:
    data = dict(zip(df["Stat"], df["Value"]))

    tier = data.get("Tier", "?")
    win_rate = data.get("Win Rate", "?")
    summ1    = data.get("Summoner 1", "?")
    summ2    = data.get("Summoner 2", "?")
    primary_tree = data.get("Primary Tree", "?")
    keystone = data.get("Keystone", "?")
    m_rune_1 = data.get("Main Tree Rune 1", "?")
    m_rune_2 = data.get("Main Tree Rune 2", "?")
    m_rune_3 = data.get("Main Tree Rune 3", "?")
    secondary_tree = data.get("Secondary Tree", "?")
    s_rune_1 = data.get("Sub Tree Rune 1", "?")
    s_rune_2 = data.get("Sub Tree Rune 2", "?")
    shard_1 = data.get("Shard 1", "?")
    shard_2 = data.get("Shard 2", "?")
    shard_3 = data.get("Shard 3", "?")
    counters = data.get("Counters", [])
    skills   = data.get("Skill Priority", [])

    embed = discord.Embed(
        title=f"{champ.upper()}  ·  {role.upper()}",
        description=f" ***Rank:*** {tier} \n\n"
                    f"***Win Rate:*** {win_rate} \n\n"
                    f"***Summoner Spells:*** {summ1}  ·  {summ2} \n\n"
                    f"***Runes:*** \n"
                    f"Primary tree: {primary_tree} \n"
                    f"---Keystone: {keystone} \n"
                    f"-----Row 1: {m_rune_1} \n"
                    f"-----Row 2: {m_rune_2} \n"
                    f"-----Row 3: {m_rune_3} \n\n"
                    f"Secondary tree: {secondary_tree} \n"
                    f"---Row 1: {s_rune_1} \n"
                    f"---Row 2: {s_rune_2} \n\n"
                    f"Shards:\n"
                    f"---{shard_1} \n"
                    f"---{shard_2} \n"
                    f"---{shard_3} \n\n"
                    f"***Counters:***\n{counters} \n\n"
                    f"***Skill priority:***\n{skills} \n",
        color = discord.Color.red()
    )
    embed.set_author(
        name="u.gg Build Guide",
    )
    embed.set_thumbnail(
        url=f"https://ddragon.leagueoflegends.com/cdn/14.8.1/img/champion/{champ.capitalize()}.png"
    )

    embed.set_image(url="attachment://items.png")
    embed.set_footer(text="Items shown below  ·  Source: u.gg")

    return embed

class BuildView(discord.ui.View):
    def __init__(self, builds, champ, role):
        super().__init__(timeout=None)
        self.original_message = None  # set after sending
        for url, build_type in builds:
            button = discord.ui.Button(
                label=build_type.upper(),
                style=discord.ButtonStyle.blurple
            )
            button.callback = self.make_callback(url, build_type, champ, role)
            self.add_item(button)

    def make_callback(self, url, build_type, champ, role):
        async def callback(interaction: discord.Interaction):
            if not interaction.response.is_done():
                await interaction.response.defer()

            # delete the old "Other Builds" button message
            if self.original_message:
                try:
                    await self.original_message.delete()
                except:
                    pass

            loading = await interaction.followup.send(
                f"Fetching **{champ.capitalize()}** {build_type.upper()} build…"
            )

            try:
                df, image_groups = await get_build(champ, role, url=url)
                stitched = stitch_all_groups(image_groups)
                embed    = build_embed(champ, f"{role} · {build_type}", df)

                await loading.delete()
                await interaction.followup.send(
                    embed=embed,
                    file=discord.File(stitched, filename="items.png"),
                )
            except Exception as e:
                print(f" build failed: {e}")
                try:
                    await loading.delete()
                except:
                    pass
                await interaction.followup.send(f"Failed to fetch build: `{e}`")

        return callback

#====================================================================================================================

@bot.event
async def on_ready():
    print(f" Logged in as {bot.user}")
    await get_browser()

@bot.event
async def on_disconnect():
    global browser_instance, playwright_instance
    if browser_instance:
        await browser_instance.close()
    if playwright_instance:
        await playwright_instance.stop()

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    await bot.process_commands(message)

@bot.command()
async def help(ctx):
    embed = discord.Embed(title="Bot Commands & Guide",
                          description="Bot Commands",
                            color=discord.Color.blue())
    embed.add_field(name="Tier List", value=f"`{ctx.prefix}tierlist-<role>`\n*Example:* `{ctx.prefix}tierlist jg`", inline=False)
    embed.add_field(name="", value=" ", inline=False)
    embed.add_field(name="Build", value=f"`{ctx.prefix} !build <champion>-<role>`\n*Example:* `{ctx.prefix}build garen-top`", inline=False)
    embed.set_footer(text=f"Requested by {ctx.author.display_name}", icon_url=ctx.author.display_avatar.url)
    embed.add_field(name="", value="Valid roles = top, jg, mid, bot, supp", inline=False)
    embed.add_field(name="", value="If a character has a space included in their name it must be included. Example: Dr. Mundo, Jarven IV ", inline=False)
    await ctx.send(embed=embed)

@bot.command(name='tierlist')
@commands.cooldown(1, 20, commands.BucketType.guild)
async def tierlist(ctx, role: str = None):
    if role is None:
        await ctx.send("Please specify a role. Example: `!tierlist top`\nValid roles: `top`, `jg`, `mid`, `bot`, `supp`")
        return
    role = role.lower()
    if role not in TIER_LIST_URLS:
        await ctx.send(f"Invalid role `{role}`. Valid roles: `top`, `jg`, `mid`, `bot`, `supp`")
        return
    await send_tierlist(ctx, role)

@tierlist.error
async def tierlist_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"Cooldown! Try again in `{error.retry_after:.0f}s`")


@bot.command(name="build")
@commands.cooldown(1, 15, commands.BucketType.user)
async def build_command(ctx, *, args: str):
    try:
        champ, role = args.lower().split("-", 1)
    except ValueError:
        await ctx.send(" Usage: `!build <champion>-<role>`  e.g. `!build zed-mid`")
        return

    champ = champ.strip()
    role  = role.strip()

    if role not in ("top", "jg", "mid", "bot", "supp"):
        await ctx.send(f" Invalid role `{role}`. Valid roles: `top`, `jg`, `mid`, `bot`, `supp`")
        return

    loading = await ctx.send(f" Fetching **{champ.capitalize()}** {role.upper()} build…")

    if not is_champion(champ):
        await loading.delete()
        await ctx.send(f" Invalid champion name `{champ}`. Check your spelling and try again.")
        return


    try:
        (df, image_groups), builds = await asyncio.gather(
            get_build(champ, role),
            other_builds(champ, role)
        )

    except Exception as e:
        await loading.delete()
        await ctx.send(f" Failed to fetch build: `{e}`")
        return

    await loading.delete()

    stitched = stitch_all_groups(image_groups)
    embed    = build_embed(champ, role, df)
    await ctx.send(
        embed=embed,
        file=discord.File(stitched, filename="items.png"),
    )

    # only send buttons if other builds exist
    if builds:
        view = BuildView(builds, champ, role)
        button_msg = await ctx.send(
            content="**Other Builds:**",
            view=view
        )
        view.original_message = button_msg


@build_command.error
async def build_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"⏳ Cooldown! Try again in `{error.retry_after:.0f}s`")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(" Usage: `!build <champion>-<role>`  e.g. `!build zed-mid`")


bot.run(token, log_handler=handler, log_level=logging.DEBUG)
