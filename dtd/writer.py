"""Gets the reel script, carousel copy, caption and DM text for a product.

In order: content pre-written in the week file (free; researched and written
in the Claude project), then the Claude API if ANTHROPIC_API_KEY is set
(paid), then a plain template.
"""

from pydantic import BaseModel, Field

from .config import env


class Beat(BaseModel):
    on_screen: str = Field(description="Caption shown on screen, 3 to 8 words")
    voiceover: str = Field(description="What the narrator says during this beat, one or two short sentences")
    broll_query: str = Field(description="2 to 4 word stock footage search for this beat")


class Slide(BaseModel):
    title: str = Field(description="Slide headline, 2 to 6 words")
    body: str = Field(description="One or two short lines, under 120 characters")


class DropContent(BaseModel):
    beats: list[Beat] = Field(description="5 to 7 beats; beat 1 is the hook, the last beat is the comment call to action")
    carousel: list[Slide] = Field(description="4 or 5 slides; slide 1 is the hook, the last says to comment the keyword")
    caption: str = Field(description="Instagram caption body without hashtags or disclosure, under 900 characters")
    hashtags: list[str] = Field(description="Hashtags without the # symbol")
    dm_message: str = Field(description="Friendly DM text sent with the link; must include {link}")
    photo_query: str | None = Field(default=None, description="2 to 4 word stock photo search showing the kind of product, used on carousel slide 1 and in the first second of the reel")


SYSTEM = """You write short-form Instagram content for {brand}, an Amazon tech affiliate account.
Voice: {voice}
Rules:
- Never state a price or a discount; prices change daily.
- Never invent specs. Use only the facts provided; speak generally otherwise.
- Hook in the first beat must stop the scroll: a problem, a risk, or a surprising fact.
- The final beat and final slide tell viewers to comment "{keyword}" to get the link.
- The reel runs 20 to 35 seconds of voiceover in total.
- Plain words, no emojis in on-screen text, at most 3 emojis in the caption."""


def write_content(cfg: dict, product: dict) -> DropContent:
    keyword = cfg["instagram"]["comment_keyword"]
    if product.get("content"):
        return DropContent.model_validate(product["content"])
    if not env("ANTHROPIC_API_KEY"):
        return _template(product, keyword)

    import anthropic

    client = anthropic.Anthropic()
    facts = "\n".join(f"- {f}" for f in product.get("key_facts", []))
    prompt = (
        f"Product: {product['name']}\n"
        f"Category: {product.get('lane', '')}\n"
        f"Angle: {product.get('angle', '').strip()}\n"
        f"Known facts:\n{facts}\n"
        f"Suggested stock footage ideas: {', '.join(product.get('broll', []))}\n"
        f"Hashtag count: {cfg['instagram']['hashtags_per_post']}"
    )
    response = client.messages.parse(
        model=cfg["writer"]["model"],
        max_tokens=16000,
        output_config={"effort": cfg["writer"]["effort"]},
        system=SYSTEM.format(brand=cfg["brand"]["name"], voice=cfg["brand"]["voice"].strip(), keyword=keyword),
        messages=[{"role": "user", "content": prompt}],
        output_format=DropContent,
    )
    if response.stop_reason == "refusal" or response.parsed_output is None:
        return _template(product, keyword)
    return response.parsed_output


def _template(product: dict, keyword: str) -> DropContent:
    name = product["name"]
    facts = product.get("key_facts", []) or ["Easy to set up", "Highly rated", "Worth a look"]
    broll = product.get("broll", []) or ["technology desk"]
    beats = [Beat(on_screen="Most people get this wrong", voiceover=product.get("angle", name).strip(), broll_query=broll[0])]
    for i, fact in enumerate(facts[:3]):
        beats.append(Beat(on_screen=fact, voiceover=fact + ".", broll_query=broll[(i + 1) % len(broll)]))
    beats.append(Beat(on_screen=f"Comment {keyword} for the link", voiceover=f"Comment {keyword} and I will send you the link.", broll_query=broll[-1]))
    return DropContent(
        beats=beats,
        carousel=[Slide(title=name, body=product.get("angle", "").strip().split(". ")[0].rstrip(".") + ".")]
        + [Slide(title=f"Why it matters {i + 1}", body=f) for i, f in enumerate(facts[:3])]
        + [Slide(title=f"Comment {keyword}", body="I will DM you the Amazon link.")],
        caption=f"{name}\n\n{product.get('angle', '').strip()}\n\nComment {keyword} and I will send you the link.",
        hashtags=["techgadgets", "amazonfinds", "coolgadgets", "techtips", "gadgets", "smarthome", "amazontech", "techfinds"],
        dm_message="Here is the link you asked for: {link}\n\nAs an Amazon Associate I earn from qualifying purchases.",
    )


def full_caption(cfg: dict, content: DropContent) -> str:
    keyword = cfg["instagram"]["comment_keyword"]
    tags = " ".join("#" + t.lstrip("#").replace(" ", "") for t in content.hashtags[: cfg["instagram"]["hashtags_per_post"]])
    body = content.caption
    if keyword not in body:
        body += f"\n\nComment {keyword} for the link."
    # Disclosure goes first so it shows before "more", as the FTC expects.
    return f"{cfg['instagram']['disclosure']}\n\n{body}\n\n{tags}"
