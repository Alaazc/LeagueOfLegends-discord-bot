import discord
from discord.ext import commands
import logging
from dotenv import load_dotenv
import os
from bs4 import BeautifulSoup, element
from playwright.async_api import async_playwright
import asyncio
import pandas as pd
from tabulate import tabulate
import time
from PIL import Image
import io
import httpx
import re
import webserver

webserver.keep_alive()


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

build_cache = {}

TIER_LIST_URLS = {
    "top":  "https://u.gg/lol/top-lane-tier-list",
    "jungle":   "https://u.gg/lol/jungle-tier-list",
    "mid":  "https://u.gg/lol/mid-lane-tier-list",
    "bot":  "https://u.gg/lol/adc-tier-list",
    "support": "https://u.gg/lol/support-tier-list",
}

ROLE_URL_MAP = {
    "top":  "top",
    "jg":   "jungle",
    "mid":  "mid",
    "bot":  "adc",
    "supp": "support",
}
cache = {role: {"data": None, "timestamp": 0} for role in TIER_LIST_URLS}
CACHE_DURATION = 1800

playwright_instance = None
browser_instance = None

async def get_browser():
    global playwright_instance, browser_instance
    if browser_instance is None or not browser_instance.is_connected():
        import subprocess, sys
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            check=True
        )
        subprocess.run(
            [sys.executable, "-m", "playwright", "install-deps", "chromium"],
            check=True
        )
        playwright_instance = await async_playwright().start()
        browser_instance = await playwright_instance.chromium.launch(
            headless=True,
            args=['--disable-blink-features=AutomationControlled']
        )
        print("Browser launched")
    return browser_instance


async def tierList(role):  # ✅ takes role instead of url
    url = TIER_LIST_URLS[role]

    if cache[role]["data"] and (time.time() - cache[role]["timestamp"]) < CACHE_DURATION:
        print(f" Returning cached data for {role}")
        return cache[role]["data"]

    browser = await get_browser()
    context = await browser.new_context(
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        viewport={'width': 1920, 'height': 1080},
    )
    page = await context.new_page()

    async def block_resources(route):
        if route.request.resource_type in ["image", "font", "media", "stylesheet"]:
            await route.abort()
        else:
            await route.continue_()
    await page.route("**/*", block_resources)

    await page.goto(url, timeout=60000, wait_until='domcontentloaded')
    await page.wait_for_selector('.rt-tr-group', timeout=30000)
    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await asyncio.sleep(1)

    content = await page.content()
    await context.close()

    soup = BeautifulSoup(content, 'html.parser')

    champs = []
    for rows in soup.find_all("div", class_="rt-tr-group"):
        text = ' '.join(rows.get_text(strip=True).split())
        match = re.match(r'(\d+)([A-Za-z]+)([A-Z][+-]?)([\d.]+%)([\d.]+%)([\d.]+%)([\d,]+)', text)
        if not match:
            match = re.match(r'(\d+)([A-Za-z\s]+?)\s+([A-Z][+-]?)\s+([\d.]+%)', text)
        if match:
            groups = match.groups()
            champs.append({
                "No":       groups[0].strip(),
                "Champion": groups[1].strip(),
                "Tier":     groups[2].strip(),
                "Win Rate": groups[3].strip()
            })

    df = pd.DataFrame(champs)
    df.index = range(1, len(df) + 1)
    df["No"]       = df["No"].str.ljust(4)
    df["Champion"] = df["Champion"].str.ljust(16)
    df["Tier"]     = df["Tier"].str.ljust(6)
    df["Win Rate"] = df["Win Rate"].str.ljust(8)

    result = tabulate(df, headers=["No", "Champion", "Tier", "Win Rate"], tablefmt="plain", showindex=False)

    # ✅ save to role-specific cache
    cache[role]["data"] = result
    cache[role]["timestamp"] = time.time()
    return result


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

async def get_soup(url):
    browser = await get_browser()
    context = await browser.new_context(
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        viewport={'width': 1920, 'height': 1080},
    )
    page = await context.new_page()

    async def block_resources(route):
        if route.request.resource_type in ["image", "font", "media", "stylesheet"]:
            await route.abort()
        else:
            await route.continue_()

    await page.route("**/*", block_resources)
    await page.goto(url, timeout=60000, wait_until='domcontentloaded')
    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await asyncio.sleep(1)

    content = await page.content()
    await context.close()

    return BeautifulSoup(content, 'html.parser')

async def get_item_sprite(soup, game_state_container, item_container):
    sprite_cache = {}
    images = []

    starters = soup.find("div", class_=f"{game_state_container}")
    item_divs = starters.find_all("div", class_=f"{item_container}")

    for item in item_divs:
        window_div = item.find("div", style=lambda s: s and "height: 36px; width: 36px;" in s)
        if not window_div:
            continue

        sprite_div = window_div.find("div", style=lambda s: s and "background-image" in s)
        if not sprite_div:
            continue

        style = sprite_div.get("style", "")
        url_match = re.search(r'url\("(.+?)"\)', style)
        pos_match = re.search(r'background-position:\s*(-?\d+)px\s*(-?\d+)px', style)
        scale_match = re.search(r'scale\(([\d.]+)\)', style)

        if not all([url_match, pos_match, scale_match]):
            continue

        url = url_match.group(1)
        x = abs(int(pos_match.group(1)))
        y = abs(int(pos_match.group(2)))
        scale = float(scale_match.group(1))
        raw_size = 48
        display_size = int(raw_size * scale)

        # download sprite sheet (cached)
        if url not in sprite_cache:
            async with httpx.AsyncClient() as client:
                response = await client.get(url)
                sprite_cache[url] = Image.open(io.BytesIO(response.content))
        sprite = sprite_cache[url]

        # crop and resize
        cropped = sprite.crop((x, y, x + raw_size, y + raw_size))
        resized = cropped.resize((display_size, display_size), Image.LANCZOS)

        buf = io.BytesIO()
        resized.save(buf, format="PNG")
        buf.seek(0)
        images.append(buf)

    return images

async def get_build(champ, role, url = None):
    if url is None:
        if url is None:
            url_role = ROLE_URL_MAP.get(role, role)
            url = f"https://u.gg/lol/champions/{champ}/build/{url_role}"
            soup = await get_soup(url)
    else:
        soup = await get_soup(url)

    data = []

    label_divs = soup.find("div", class_="flex flex-wrap gap-[12px] max-[700px]:flex-col")
    inner_label_divs = label_divs.find("div",
                                       class_="""grid gap-[1px] grid-cols-6 max-xs:grid-cols-3 max-xs:grid-rows-2 rounded-[3px] bg-purple-500 [&>*]:bg-purple-200 overflow-hidden flex-1""")
    children = inner_label_divs.find_all("div", recursive=False)  # direct children only

    tier = children[0].get_text(strip=True).replace("Tier", "").strip()
    win_rate = children[1].get_text(strip=True).replace("Win Rate", "").strip()

    data.append(tier)
    data.append(win_rate)

    summs = soup.find("div", class_="content-section_content summoner-spells")
    summs_div = summs.find("div", class_=lambda c: c and "flex" in c)
    if summs:
        summs_imgs = summs.find_all("img")  # just grab all imgs directly
        for img in summs_imgs:
            summoner = img.get("alt", "").strip()
            if summoner:
                summoner = summoner.replace("Summoner Spell", "")
                data.append(summoner)

    runes = []

    desktop = soup.find("div", class_="rune-trees-container media-query media-query_MOBILE_LARGE__DESKTOP_LARGE")
    parent = desktop.find("div", class_=lambda c: c and "rune-tree primary-tree" in c)

    tree_div = parent.find("div", class_="rune-image-container")
    if tree_div:
        tree_img = tree_div.find("img")
        treeRune = "".join(tree_img.get("alt", "").split()[3:])
        runes.append(treeRune)

    # get the active keystone (Conqueror etc.)
    keystone_div = parent.find("div", class_="perk keystone perk-active")
    if keystone_div:
        keystone_img = keystone_div.find("img")
        keystoneRune = " ".join(keystone_img.get("alt", "").split()[2:])
        runes.append(keystoneRune)

    runes_div = parent.find_all("div", class_="perk perk-active")
    if runes_div:
        for div_ in runes_div:
            runes_img = div_.find("img")  # find img inside each div
            if runes_img:
                rune = runes_img.get("alt", "").split()[2:]
                rune = " ".join(rune)
                runes.append(rune)

    parent2 = desktop.find("div", class_=lambda c: c and "secondary-tree" in c)

    tree_div2 = parent2.find("div", class_="rune-image-container")

    if tree_div2:
        tree_img = tree_div2.find("img")
        treeRune = "".join(tree_img.get("alt", "").split()[3:])
        runes.append(treeRune)

    runes_div = parent2.find_all("div", class_="perk perk-active")
    if runes_div:
        for div_ in runes_div:
            runes_img = div_.find("img")  # find img inside each div
            if runes_img:
                rune = runes_img.get("alt", "").split()[2:]
                rune = " ".join(rune)
                runes.append(rune)

    shard_container = parent2.find("div", class_=lambda c: c and "rune-tree stat-shards-container" in c)
    activeShard_divs = shard_container.find_all("div", class_=lambda c: c and "shard shard-active" in c)
    if activeShard_divs:
        for div_ in activeShard_divs:
            shard_img = div_.find("img")
            if shard_img:
                shard = shard_img.get("alt", "").split()
                shard = " ".join(shard)
                runes.append(shard)

    data.extend(runes)

    counters_tree = soup.find("div", class_="toughest-matchups")
    counters = counters_tree.find_all("a", class_="champion-matchup")

    match_ups = []
    for a_tag in counters:
        name_div = a_tag.find("div", class_="champion-name")
        if name_div:
            name = name_div.get_text(strip=True)
            match_ups.append(name)

    data.append(match_ups)

    skills = soup.find("div", class_="skill-priority-path")
    skill_label = skills.find_all("div", class_="champion-skill-with-label")

    skills_prio = []
    for img in skill_label:
        skillName_img = img.find("img")
        if skillName_img:
            skill = skillName_img.get("alt", "").split()
            skill = " ".join(skill)
            skills_prio.append(skill)

    data.append(skills_prio)

    rows = [
        ("Tier", data[0]),
        ("Win Rate", data[1]),
        ("Summoner 1", data[2]),
        ("Summoner 2", data[3]),
        ("Primary Tree", data[4]),
        ("Keystone", data[5]),
        ("Main Tree Rune 1", data[6]),
        ("Main Tree Rune 2", data[7]),
        ("Main Tree Rune 3", data[8]),
        ("Secondary Tree", data[9]),
        ("Sub Tree Rune 1", data[10]),
        ("Sub Tree Rune 2", data[11]),
        ("Shard 1", data[12]),
        ("Shard 2", data[13]),
        ("Shard 3", data[14]),
        ("Counters", data[15]),
        ("Skill Priority", data[16]),
    ]

    df = pd.DataFrame(rows, columns=["Stat", "Value"])

    starting = await get_item_sprite(soup, "content-section_content starting-items", "item-img")
    core = await get_item_sprite(soup, "content-section_content core-items", "sprite")
    option1 = await get_item_sprite(soup, "content-section_content item-options item-options-1", "item-img")
    option2 = await get_item_sprite(soup, "content-section_content item-options item-options-2", "item-img")

    image_groups = {
        "Starting Items": starting,
        "Core Build": core,
        "4th and 5th items": option1,
        "6th item": option2,
    }
    return df, image_groups

def stitch_all_groups(image_groups, item_size=64, padding=8, label_height=20, background=(30, 30, 30, 255)):
    from PIL import ImageDraw, ImageFont

    # calculate total canvas size
    total_height = padding
    for name, imgs in image_groups.items():
        if imgs:
            total_height += label_height + item_size + padding

    max_width = max(
        (item_size + padding) * len(imgs) + padding
        for imgs in image_groups.values() if imgs
    )

    combined = Image.new("RGBA", (max_width, total_height), background)
    draw = ImageDraw.Draw(combined)

    try:
        font = ImageFont.truetype("arial.ttf", 14)
    except:
        font = ImageFont.load_default()

    y = padding
    for name, imgs in image_groups.items():
        if not imgs:
            continue

        # draw label
        draw.text((padding, y), name, fill=(255, 255, 255, 255), font=font)
        y += label_height

        # paste items
        for i, buf in enumerate(imgs):
            item = Image.open(buf).resize((item_size, item_size), Image.NEAREST)
            x = padding + i * (item_size + padding)
            combined.paste(item, (x, y))

        y += item_size + padding

    out = io.BytesIO()
    combined.save(out, format="PNG")
    out.seek(0)
    return out

async def other_builds(champ, role):
    url_role = ROLE_URL_MAP.get(role, role)
    url = f"https://u.gg/lol/champions/{champ}/build/{url_role}"
    soup = await get_soup(url)
    base_url = "https://u.gg"

    container = soup.find("div", class_="flex gap-[12px] max-sm:hidden")
    if not container:
        return []

    links = container.find_all("a", class_=lambda c: c and "bg-purple-200" in c)

    builds = []
    for link in links:
        href = link.get("href")
        if href:
            full_url = base_url + href
            parts = href.strip("/").split("/")
            print(f"href: {href}, parts: {parts}")  # ✅ see exact structure
            build_type = parts[2]
            builds.append((full_url, build_type))

    print(f"total builds found: {len(builds)}")
    return builds

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
        icon_url="https://static.bigbrain.gg/assets/lol/icons/ugg-logo.png"
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
        self.original_message = None  # ✅ set after sending
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

            # ✅ delete the old "Other Builds" button message
            if self.original_message:
                try:
                    await self.original_message.delete()
                except:
                    pass

            loading = await interaction.followup.send(
                f"🔄 Fetching **{champ.capitalize()}** {build_type.upper()} build…"
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

class view(discord.ui.View):
    @discord.ui.button(label = None, style = discord.ButtonStyle.blurple)
    async def button(self, button, ctx):
        await get_build()

@bot.command()
async def help(ctx):
    embed = discord.Embed(title="Bot Commands & Guide",
                          description="Bot Commands",
                            color=discord.Color.blue())
    embed.add_field(name="Tier List", value=f"`{ctx.prefix}tierlist [role]`\n*Example:* `{ctx.prefix}tierlist jg`", inline=False)
    embed.add_field(name="", value=" ", inline=False)
    embed.add_field(name="Build", value=f"`{ctx.prefix}build-[champ]`\n*Example:* `{ctx.prefix}build garen-top`", inline=False)
    embed.set_footer(text=f"Requested by {ctx.author.display_name}", icon_url=ctx.author.display_avatar.url)
    embed.add_field(name="", value="Valid roles = top, jg, mid, bot, supp", inline=False)
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

    loading = await ctx.send(f"🔄 Fetching **{champ.capitalize()}** {role.upper()} build…")

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

    # ✅ only send buttons if other builds exist
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
