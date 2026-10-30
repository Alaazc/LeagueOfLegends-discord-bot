from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from PIL import Image
import asyncio
import httpx
import io
import re
import pandas as pd
import time
from tabulate import tabulate
import json
from PIL import ImageDraw, ImageFont
import subprocess
import sys

playwright_instance = None
browser_instance = None

build_cache = {}

TIER_LIST_URLS = {
    "top":  "https://u.gg/lol/top-lane-tier-list",
    "jg":   "https://u.gg/lol/jungle-tier-list",
    "mid":  "https://u.gg/lol/mid-lane-tier-list",
    "bot":  "https://u.gg/lol/adc-tier-list",
    "supp": "https://u.gg/lol/support-tier-list",
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

async def get_browser():
    global playwright_instance, browser_instance
    if browser_instance is None or not browser_instance.is_connected():
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            check=True
        )
        playwright_instance = await async_playwright().start()
        browser_instance = await playwright_instance.chromium.launch(
            headless=True,
            args=['--disable-blink-features=AutomationControlled',
                  "--no-sandbox",
                  "--disable-setuid-sandbox",
                  "--disable-dev-shm-usage",
                  "--disable-accelerated-2d-canvas",
                  "--no-first-run",
                  "--no-zygote",
            ]
        )
        print("Browser launched")
    return browser_instance

async def close_browser():
    """Close Playwright's browser and driver. Safe to call multiple times."""
    global browser_instance, playwright_instance

    if browser_instance is not None:
        try:
            await browser_instance.close()
        except Exception as e:
            print(f"Error closing browser: {e}")
        finally:
            browser_instance = None

    if playwright_instance is not None:
        try:
            await playwright_instance.stop()
        except Exception as e:
            print(f"Error stopping playwright: {e}")
        finally:
            playwright_instance = None

async def get_soup_tierlist(url):
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
    await asyncio.sleep(2)

    await page.mouse.move(960, 400)

    all_rows = {}
    last_max_rank = -1
    no_new = 0

    while no_new < 5:
        rows = await page.evaluate("""
            () => {
                const tbody = document.querySelector('.rt-tbody');
                if (!tbody) return [];
                const rows = tbody.querySelectorAll('[class*="rt-tr-group"]');
                return Array.from(rows).map(r => r.innerText.trim());
            }
        """)

        for text in rows:
            text = ' '.join(text.split())
            match = re.match(r"(\d+)\s*([\w']+(?:\s[\w']+)*)\s+([A-Z][+-]?)\s+([\d.]+%)", text)
            if match:
                rank = match.group(1).strip()
                all_rows[rank] = {
                    "No":       rank,
                    "Champion": match.group(2).strip(),
                    "Tier":     match.group(3).strip(),
                    "Win Rate": match.group(4).strip()
                }

        current_max = max(int(k) for k in all_rows.keys()) if all_rows else 0
        no_new = no_new + 1 if current_max == last_max_rank else 0
        last_max_rank = current_max

        await page.mouse.wheel(0, 15 * 40)
        await asyncio.sleep(0.8)

    await context.close()
    return all_rows

async def tierList(role):
    url = TIER_LIST_URLS[role]

    if cache[role]["data"] and (time.time() - cache[role]["timestamp"]) < CACHE_DURATION:
        print(f"Returning cached data for {role}")
        return cache[role]["data"]

    all_rows = await get_soup_tierlist(url)  # correct function

    champs = sorted(all_rows.values(), key=lambda x: int(x["No"]))
    df = pd.DataFrame(champs)

    result = tabulate(df, headers=["No", "Champion", "Tier", "Win Rate"], tablefmt="plain", showindex=False)

    cache[role]["data"] = result
    cache[role]["timestamp"] = time.time()
    return result


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

    build_divs = soup.find("div", class_=lambda c: c and "champion-recommended-build" in c)

    label_divs = build_divs.find("div", class_=lambda c: c and "flex-wrap" in c and "gap-[12px]" in c)

    inner_label_divs = label_divs.find("div", class_=lambda c: c and "grid" in c and "flex-1" in c)

    label_container = inner_label_divs.find("div", class_=lambda c: c and "grid-cols-6" in c and "bg-purple-200" in c)

    tier = label_container.find("div", class_=lambda c: c and "font-extrabold" in c)
    tier_letter = tier.get_text(strip=True)

    data.append(tier_letter)

    winrate_div = label_container.find("div", class_=lambda c: c and "okay-tier" in c)

    winrate_val = winrate_div.get_text(strip=True)
    data.append(winrate_val)

    rune_spell = build_divs.find("div", class_=lambda c: c and "rune-spell" in c)

    rune_spell_inner = rune_spell.find("div", class_=lambda c: c and "content-section content-section_unset grid-1 max-sm:!flex max-sm:!flex-col" in c)

    summoner_divs =rune_spell_inner.find("div", class_=lambda c: c and "content-section_content summoner-spells" in c)

    summoner_container = summoner_divs.find("div", class_=lambda c: c and "flex" in c)


    if summoner_container:
        summoners_imgs = summoner_container.find_all("img")  # just grab all imgs directly
        for img in summoners_imgs:
            summoner = img.get("alt", "").strip()
            if summoner:
                summoner = summoner.replace("Summoner Spell", "")
                data.append(summoner)

    runes = []

    desktop = build_divs.find("div", class_="rune-trees-container media-query media-query_MOBILE_LARGE__DESKTOP_LARGE")

    parent = desktop.find("div", class_=lambda c: c and "rune-tree primary-tree" in c)


    tree_div = parent.find("div", class_="rune-image-container")
    if tree_div:
        tree_img = tree_div.find("img")
        treeRune = "".join(tree_img.get("alt", "").split()[3:])
        runes.append(treeRune)

    # get the active keystone (Conqueror etc.)
    keystone_divs = parent.find("div", class_=lambda c: c and "perk-row keystone-row" in c)

    keystone_div = keystone_divs.find("div", class_="perk keystone perk-active")
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
    except Exception:
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

    container = soup.find("div", class_=lambda c: c and "rune-spell" in c)
    if not container:
        return []

    link_container = container.find("div", class_=lambda c: c and "flex gap-[12px]" in c)
    if not link_container:
        return []

    links = link_container.find_all("a", href=True)

    builds = []
    for link in links:
        href = link.get("href")
        if href:
            full_url = base_url + href
            parts = href.strip("/").split("/")

            try:
                champ_index = parts.index(champ)
                build_type = parts[champ_index - 1] if champ_index > 2 else "default"
            except ValueError:
                build_type = parts[-1]

            if not build_type or build_type == url_role or build_type == "default":
                continue

            builds.append((full_url, build_type))

    return builds

def is_champion(champ: str) -> bool:
    champ = champ.strip().title()
    with open("all_champs.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    champions = data.get("champions", {})
    if champ in champions:
        return True
    else:
        return False
