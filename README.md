# Daily Tech Drops

Automated Amazon affiliate content for Instagram [@daily_tech_drops](https://www.instagram.com/daily_tech_drops/).
Every morning GitHub Actions picks the next product, uses its pre-written script and caption, renders a reel
and a photo carousel, and opens an approval issue. Add the **approved** label (works from the GitHub phone app)
and it posts. Anyone who comments **LINK** gets the affiliate link by DM.

## How a day runs

| Time (Eastern) | Workflow | What happens |
| --- | --- | --- |
| 7:00 a.m. | `Daily drop` | Picks a product from `products.yaml`, writes content, renders `reel.mp4` + 5 slides, opens an issue |
| When you approve | `Publish drop` | Posts the reel and carousel, records the post, closes the issue |
| Every 30 min | `Comment link DMs` | DMs the link to anyone who commented the keyword, replies "Sent! Check your DMs." |
| 1st of the month | `Refresh Instagram token` | Renews the 60-day Instagram token |

Set the repository variable `AUTO_PUBLISH` to `true` to skip approval and post as soon as the draft is ready.

## One-time setup

### 1. Repository secrets and variables
Settings > Secrets and variables > Actions.

| Secret | Where to get it | Required |
| --- | --- | --- |
| `AMAZON_TAG` | Amazon Associates > tracking ID, e.g. `dailytechdrops-20` | Yes |
| `IG_USER_ID` | From the Meta app setup below | Yes |
| `IG_ACCESS_TOKEN` | From the Meta app setup below (long-lived token) | Yes |
| `PEXELS_API_KEY` | pexels.com/api (free) | Recommended (plain branded backgrounds without it) |
| `ANTHROPIC_API_KEY` | console.anthropic.com (paid) | No. Only for products without pre-written content |
| `ELEVENLABS_API_KEY` | elevenlabs.io (paid for commercial use) | No. Only if `voice.provider` is `elevenlabs` |
| `GH_PAT` | GitHub fine-grained token, this repo only, "Secrets: read and write" | For the monthly token refresh |

| Variable | Value |
| --- | --- |
| `AUTO_PUBLISH` | `true` to post without approval (leave unset at first) |
| `MEDIA_BASE_URL` | Only if the carousel images are hosted somewhere other than this repo's `media` branch |
| `KEYWORD_DMS` | `off` if you use Instagram's built-in keyword auto-reply instead |

### 2. Meta app (lets the code post and DM)
1. Instagram account must be **Professional** (Creator or Business).
2. developers.facebook.com > My Apps > Create app > use case **Manage messaging and content on Instagram**.
3. Under *API setup with Instagram login*, add the Instagram account and generate a token with:
   `instagram_business_basic`, `instagram_business_content_publish`,
   `instagram_business_manage_comments`, `instagram_business_manage_messages`.
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
Pexels footage, and the Piper voice, which runs on GitHub's machines. Scripts are pre-written in
`products.yaml` from the Claude project, so no paid AI API is needed. ElevenLabs voices and the Claude API
are optional upgrades.

## Adding products
Add entries to `products.yaml`. Each needs the ASIN (from `amazon.com/dp/<ASIN>`), a name, a lane, an angle,
a few verified facts and stock footage ideas, plus a `content` block with the beats, slides, caption,
hashtags and DM text (see the first product for the shape). Posts never state prices because prices change daily.

## Running locally
```bash
pip install -r requirements.txt   # plus ffmpeg on your PATH
python -m dtd generate --date 2026-10-21   # writes output/2026-10-21/
```
With no API keys set it still renders a full draft using the template, which is a free way to test changes.

## Rules this follows
- Every caption starts with `#ad As an Amazon Associate I earn from qualifying purchases.` (FTC and Amazon).
- No Amazon product photos: the Associates agreement limits reuse of Amazon images. Visuals are stock footage and branded text.
- Posting and DMs go through Instagram's official API only.
