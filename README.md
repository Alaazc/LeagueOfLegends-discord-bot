<div align="center">

# League of Legends Discord Bot

**Type a command. Get a full champion build in seconds.**
Live data scraped from u.gg, delivered as rich Discord embeds, and shipped to AWS by an automated CI/CD pipeline.

![CI/CD](https://github.com/Alaazc/LeagueOfLegends-discord-bot/actions/workflows/deploy.yml/badge.svg)
![Python](https://img.shields.io/badge/python-3.12-3776AB?logo=python&logoColor=white)
![AWS EC2](https://img.shields.io/badge/hosted%20on-AWS%20EC2-FF9900?logo=amazonaws&logoColor=white)
![Code style: black](https://img.shields.io/badge/code%20style-black-000000)

<img width="1104" height="456" alt="image" src="https://github.com/user-attachments/assets/cc8ead30-833b-4f1b-bf9b-5a6149dbc80d" />

<img width="657" height="882" alt="image" src="https://github.com/user-attachments/assets/4fcb471a-6cf7-4795-9ef2-fee734412c1e" />
<img width="593" height="263" alt="image" src="https://github.com/user-attachments/assets/6225e1a6-c79f-44dd-a341-0030336bad24" />

<img width="1090" height="447" alt="image" src="https://github.com/user-attachments/assets/1405e50a-05c7-46da-a9dc-303b9ae9165a" />


</div>

---

## The bot

```
!build Katarina-mid        →  rank, win rate, runes, summoners, skill order,
                           counters, and a rendered item-build image
!tierlist top            →  the full jungle tier list, scraped live
```

| | |
|---|---|
| 🏆 **Full builds** | Rank, win rate, summoner spells, complete rune page with shards, skill priority, and toughest matchups |
| 🖼️ **Item images** | Starting, core, and situational items rendered into a single image, built on the fly |
| 🔀 **Alternate builds** | One-click buttons beneath each build swap to other build variants without retyping |
| 📊 **Tier lists** | Every role, including rows that only load as you scroll |
| 🛡️ **Safe by design** | Input validation, per-user and per-server cooldowns, and a 30-minute cache so u.gg isn't hammered |

---

## Under the hood

This isn't a thin API wrapper. u.gg has no public API, so every answer is built by driving a real browser and turning a messy page into clean data.

- **Headless Chromium via Playwright.** The pages are JavaScript-rendered, so plain HTTP requests return nothing useful. One shared browser instance is reused across requests, with a fresh isolated context per scrape.
- **Virtualized tier-list scraping.** The tier table only renders rows near the viewport. The scraper scrolls in steps, de-duplicates by rank, and stops when no new rows appear.
- **Rebuilding item icons from CSS sprites.** Items are served as one big sprite sheet positioned with CSS. The bot parses each element's `background-position` and `scale`, crops the exact tile with Pillow, and stitches the groups into one labeled image.
- **Concurrent fetching.** The build and its alternate variants are fetched together with `asyncio.gather`, so the user waits for the slower request, not the sum of both.
- **Graceful shutdown.** The bot overrides `close()` to shut down Chromium and Playwright, so each deploy restart leaves no orphaned browser processes eating memory.
- **Faster, cheaper scraping.** Images, fonts, and stylesheets are blocked at the network layer, since only the DOM is needed.

---

## CI/CD pipeline

Every change goes through the same automated path. Nothing reaches the live bot unless it passes.

```mermaid
flowchart LR
    A[git push / PR] --> B{test job}
    B -->|black --check| C[Formatting]
    B -->|flake8| D[Linting]
    B -->|pytest| E[Smoke tests]
    C & D & E --> F{All green?}
    F -->|No| G[❌ Blocked: bot untouched]
    F -->|Yes + push to main| H[deploy job]
    H --> I[SSH into EC2]
    I --> J[Sync to origin/main]
    J --> K[Install deps + Chromium]
    K --> L[Restart systemd service]
    L --> M{Service active?}
    M -->|Yes| N[✅ Live]
    M -->|No| O[❌ Deploy fails loudly]
```

**Quality gates**

| Gate | Tool | What it prevents |
|---|---|---|
| Formatting | Black | Style drift and noisy diffs |
| Linting | flake8 | Unused imports, bare `except`, undefined names |
| Tests | pytest | Broken imports shipping to production |
| PR isolation | Branch rules in the workflow | Pull requests run tests but never deploy |
| Post-deploy check | `systemctl is-active` | A crashed bot being reported as a successful deploy |

**Deployment design**

- **Triggered only by merges to `main`**, after the test job passes (`needs: test`).
- **Deterministic server state.** The deploy runs `git fetch` and `git reset --hard origin/main`, so the server always matches GitHub exactly and local drift can't block a release.
- **Always-on process management.** The bot runs as a `systemd` service with `Restart=always`, so it recovers from crashes and survives reboots.
- **Secrets stay out of the repo.** The Discord token lives in a server-side `.env`, and SSH credentials live in GitHub Actions secrets.

---

## Real problems solved along the way

Building this surfaced the kind of issues that only appear when you actually deploy:
---

## Architecture

```mermaid
flowchart TB
    U[Discord user] -->|!build / !tierlist| B[Bot.py<br/>discord.py]
    B --> S[Scraper.py]
    S --> P[Playwright<br/>headless Chromium]
    P --> W[(u.gg)]
    S --> I[Pillow<br/>item image stitching]
    S --> C[(30-min cache)]
    B -->|embed + image + buttons| U
    subgraph AWS EC2
      B
      S
      P
    end
    G[GitHub Actions] -->|SSH deploy| AWS
```

## Tech stack

| Layer | Tools |
|---|---|
| Bot | discord.py, python-dotenv |
| Scraping | Playwright, BeautifulSoup, httpx |
| Data and imaging | pandas, tabulate, Pillow |
| Infrastructure | AWS EC2 (Amazon Linux), systemd |
| Automation | GitHub Actions, Black, flake8, pytest |

---

## Run it yourself


---

## Roadmap

- [ ] Unit tests for scraping helpers using saved HTML fixtures
- [ ] Containerize with Docker and deploy via ECR
- [ ] Replace SSH deploys with AWS SSM and GitHub OIDC (no open port 22)
- [ ] Slash commands with autocomplete for champion names
- [ ] Alerts when the scraper's selectors stop matching

---

<sub>Not affiliated with or endorsed by Riot Games or u.gg. League of Legends is a trademark of Riot Games, Inc.</sub>

