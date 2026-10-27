# Daily Tech Drops

Automated Amazon affiliate content for Instagram [@daily_tech_drops](https://www.instagram.com/daily_tech_drops/).
Each Sunday, Claude researches the week's best-selling, well-reviewed tech products and writes every reel
and carousel into one file in `weeks/`, opened as a pull request. GitHub renders the whole week and comments
a preview. **Merging the pull request approves the week** (works from the GitHub phone app). Each product
then posts at its scheduled time, and anyone who comments **LINK** gets the affiliate link by DM.

## How a week runs

| When | Workflow | What happens |
| --- | --- | --- |
| Sunday | Claude project routine | Researches products, writes `weeks/<monday>.yaml`, opens a pull request |
| On that pull request | `Render week` | Renders every reel and carousel, stores them on the `media` branch, comments a preview |
| You merge | | The week is approved |
| Every 30 min | `Post and reply` | Posts the next product whose time has come; DMs the link to keyword comments |
| Sunday late morning | `Weekly report` | Measures the last 7 days per post and lane, saves `reports/latest.md` for the Sunday research, opens an issue with the report |
| 1st of the month | `Refresh Instagram token` | Renews the 60-day Instagram token |

**Sunday research, read this:** if `reports/latest.md` exists, it is last week's performance report. Weight the new
week toward the lanes, product types and hooks that earned the most link DMs, saves and shares, and away from the
weakest, while still rotating lanes. Open the week's pull request body with two or three lines on what the report
showed and how it shaped the picks.

## Growth experiments (from Oct 26 2026)

Three reels a day, no separate carousels (carousels reached 1 to 8 people, reels about 100). The Sunday research
fills each day like this:

| Slot | What | Why |
| --- | --- | --- |
| 11:30 ET | New product | Fixed time, so week-over-week numbers compare |
| 19:00 ET | New product | Fixed time |
| Test time, rotating `schedule.test_times` one per day | **Remix**: a product posted at least 2 days earlier, with a new hook | Tests hook styles on the same product and photos, tests posting times, and gives winners a second run |

Remix entries carry `remix_of: <id of the first post>` and `hook_style:`, use a different hook style than the first
post, reuse its `photo_ids`, and rewrite the caption opening. Pick remixes from the report's best reels (reach, then
watch time); never remix the weakest. The shop page lists each product once.

**Hook styles** (the report guesses one from the first beat when `hook_style` is not set):
`question` ("Still fighting your trackpad?"), `demo` ("Watch this cable snap back"), `number` ("Three devices, one stand"),
`statement` ("Never lose your keys again"). Spread the week's new products across all four until the report's
"Experiments" tables show a style winning for two or three weeks in a row, then lean into it.

**Holiday plan, Nov to Dec** (never state prices or discounts, Associates rule; say "stocking stuffer", not "under $10"):
- Nov 7 to Nov 20: one of the two new products a day framed as a gift idea, with "gift" in the caption's first line.
- Nov 21 to Dec 1 (Black Friday Nov 27, Cyber Monday Nov 30): best-reviewed big-name gadgets people wait for deals on;
  the caption says "check Amazon for today's price", never the deal itself.
- Dec 2 to Dec 15: gifts by person (for the desk worker, the traveler, the gamer, the person who has everything).
- Dec 16 to Dec 21: stocking stuffers and small gifts that still ship in time; mention Prime shipping only as "check the delivery date".
- Remix slots in Nov and Dec favor the year's most tapped products from the shop page.
  Nov 7 to Nov 20 remixes are already written as gift reels (`weeks/2026-11-07-gift-reels.yaml`).

**Gift guides:** `gift_guides.yaml` lists five guides (desk worker, traveler, safer home, the person who has
everything, stocking stuffers), grouped by who the gift is for and spanning every price range. Each is a page at
`/gifts/<slug>.html` on the shop site, shown as a "Holiday gift guides" row on the shop page from Nov 1 to Dec 24.
A posted product joins a guide when its ASIN is listed there, or when its week file entry has `gift_guide: <slug>`.
A gift reel sets `content.label: Gift idea` (or `Stocking stuffer`) for the orange tag on its hook.
The Shop images workflow draws a 1000x1500 Pinterest pin per guide (`docs/gifts/<slug>.jpg`) whenever the guides
change; the guide page uses it as its preview image and has a "Save this guide to Pinterest" link. The weekly report
has a "Gift guides" table: visits, opens from the shop page, taps to Amazon and Pinterest saves per guide.

**Which posts drive sales:** the shop page counts visits and every tap on a product card (GoatCounter, site code in
`config.yaml`), and the weekly report lists them under "Shop page". Links on the shop page, Facebook and YouTube can
each carry their own Associates tracking ID (`amazon.channel_tags`), so the Associates Orders report shows which
channel and product earned each sale. Empty channel tags fall back to the base tag.

A post more than 6 hours late (for example, a week merged on Tuesday) is skipped rather than posted late.
To pull one product, delete it from the week file before its time.

## One-time setup

### 1. Repository secrets and variables
Settings > Secrets and variables > Actions.

| Secret | Where to get it | Required |
| --- | --- | --- |
| `AMAZON_TAG` | Amazon Associates > tracking ID, e.g. `dailytechdrops-20` | Yes |
| `IG_USER_ID` | From the Meta app setup below | Yes |
| `IG_ACCESS_TOKEN` | From the Meta app setup below (long-lived token) | Yes |
| `PIXABAY_API_KEY` | pixabay.com/api/docs (free account; the key is shown on that page once logged in) | Recommended (plain branded backgrounds without a footage key) |
| `PEXELS_API_KEY` | pexels.com/api (free, but new keys were paused when we tried in Oct 2026) | Optional alternative to Pixabay |
| `ANTHROPIC_API_KEY` | console.anthropic.com (paid) | No. Only for products without pre-written content |
| `ELEVENLABS_API_KEY` | elevenlabs.io (paid for commercial use) | No. Only if `voice.provider` is `elevenlabs` |
| `GOATCOUNTER_TOKEN` | goatcounter.com (free) > Settings > API > new token with "Read statistics" | For shop page clicks in the weekly report |
| `GH_PAT` | GitHub fine-grained token, this repo only, "Secrets: read and write" | For the monthly token refresh |

| Variable | Value |
| --- | --- |
| `MEDIA_BASE_URL` | Only if the carousel images are hosted somewhere other than this repo's `media` branch |
| `KEYWORD_DMS` | `off` if you use Instagram's built-in keyword auto-reply instead |

### 2. Meta app (lets the code post and DM)
1. Instagram account must be **Professional** (Creator or Business).
2. developers.facebook.com > My Apps > Create app > use case **Manage messaging and content on Instagram**.
3. Under *API setup with Instagram login*, add the Instagram account and generate a token with:
   `instagram_business_basic`, `instagram_business_content_publish`,
   `instagram_business_manage_comments`, `instagram_business_manage_messages`,
   `instagram_business_manage_insights` (for the weekly report).
4. Copy the Instagram user ID and the token into the secrets above.
5. While the app is in Development mode it works for your own account, which is all this needs.

### 3. Carousel images must be public
Instagram downloads carousel images from a URL. Reels upload directly and do not need this.
The default URL is this repo's `media` branch, which only works if the **repository is public**.
Nothing secret lives in the code; keys stay in GitHub secrets. Public repos also get unlimited Actions minutes.
If the repo stays private, set `MEDIA_BASE_URL` to another public host, or the carousel step fails while the reel still posts.

### 4. Music (optional)
Drop royalty-free `.mp3` files in `assets/music/`. One is picked at random per reel and mixed under the voice.
Use tracks you have the rights to (for example YouTube Audio Library or a Pixabay music download).

## Cost

Everything in the default setup is free: GitHub Actions (unlimited on a public repo), the Instagram API,
Pixabay or Pexels footage, and the Piper voice, which runs on GitHub's machines. Scripts are pre-written in
the week files from the Claude project, so no paid AI API is needed. ElevenLabs voices and the Claude API
are optional upgrades.

## Week files
Each entry in `weeks/<monday>.yaml` has a `slot` ("YYYY-MM-DD HH:MM", Eastern), the ASIN (from
`amazon.com/dp/<ASIN>`), name, lane, angle, verified facts, stock footage ideas, and a `content` block with
the beats, slides, caption, hashtags and DM text. See `weeks/2026-10-26.yaml` for the shape.
Posts never state prices because prices change daily.

## Running locally
```bash
pip install -r requirements.txt   # plus ffmpeg on your PATH
python -m dtd render --week weeks/2026-10-26.yaml   # writes output/<id>/ per product
```
With no API keys set it still renders a full draft using the template, which is a free way to test changes.

## Rules this follows
- Every caption, Facebook post and YouTube description ends with `#ad As an Amazon Associate I earn from qualifying purchases.` as its last line (FTC and Amazon).
- Reels run 10 to 15 seconds, never longer: 3 beats (hook, one reason, comment SHOP) and about 30 words of voiceover (Kevin, Oct 25 2026).
- No Amazon product photos: the Associates agreement limits reuse of Amazon images. Visuals are stock footage and branded text.
- Posting and DMs go through Instagram's official API only.
