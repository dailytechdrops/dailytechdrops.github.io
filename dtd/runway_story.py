"""Make the shots of an AI story video with the Runway API (stories/<name>.yaml).

Each shot: a still from gen4_image with the real product photo (per shot product_photo, else the story's) as the @product reference, then a
5 second gen4_turbo clip animated from that still. Outputs go to out/<name>/. A hard credit cap
(budget_credits) stops the run before any request that would exceed it. Shots already present in
out/<name>/ (fetched from the media branch) are skipped, so a rerun only redoes what was removed.
"""
import base64, json, os, sys, time
from pathlib import Path
import requests, yaml

API = "https://api.dev.runwayml.com/v1"
COST_STILL, COST_CLIP = 5, 25   # gen4_image 720p; gen4_turbo 5 credits/s x 5 s
HEAD = {"Authorization": f"Bearer {os.environ.get('RUNWAY_API_KEY','')}", "X-Runway-Version": "2024-11-06"}


# Guard rails added to every prompt (Kevin, Nov 4 2026: "so we do not have to recreate them").
# Each one comes from a paid redo: a dog morphing mid-jump, wired earbuds drawn for a wireless product.
GUARD_STILL = ("The product must match the reference exactly: same shape, color, logo and type; do not invent cords, "
               "parts or a different model. Natural hands with five fingers. No text, no watermarks.")
GUARD_MOTION = ("Slow, calm motion only. The product keeps exactly the same shape, color and logo in every frame. "
                "Nothing morphs, appears or disappears. No text.")
# Motion that has morphed or is likely to: refused before any credits are spent.
RISKY = ("jump", "run", "walk", "stand up", "stands up", "pick up", "picks up", "lift", "carry", "carries", "throw",
         "dance", "spin", "fast", "quick")
PROMPT_MAX = 1000   # Runway rejects longer prompt text


def prompts(shot: dict) -> tuple[str, str]:
    """The shot's still and motion prompts with its must-haves and the guard rails added."""
    must = " ".join(f"Must: {m.rstrip('.')}." for m in shot.get("must", []))
    still = " ".join(x for x in (shot["still"].strip(), must, GUARD_STILL) if x)
    motion = " ".join(x for x in (shot["motion"].strip(), must, GUARD_MOTION) if x)
    return still, motion


def check(spec: dict) -> None:
    """Refuses a story before spending anything if a shot asks for risky motion or a prompt is too long."""
    problems = []
    for shot in spec["shots"]:
        still, motion = prompts(shot)
        words = shot["motion"].lower()
        allowed = [a.lower() for a in shot.get("allow", [])]
        for w in RISKY:
            if f" {w}" in f" {words}" and w not in allowed and f"no {w}" not in words:
                problems.append(f"{shot['id']}: motion asks for '{w}' (risky; reword, or list it under allow: if it is a 'no ...')")
        for label, text in (("still", still), ("motion", motion)):
            if len(text) > PROMPT_MAX:
                problems.append(f"{shot['id']}: {label} prompt is {len(text)} characters with guard rails (max {PROMPT_MAX})")
    if problems:
        sys.exit("story refused, no credits spent:\n" + "\n".join(problems))


def data_uri(path: Path) -> str:
    kind = "png" if path.suffix.lower() == ".png" else "jpeg"
    return f"data:image/{kind};base64," + base64.b64encode(path.read_bytes()).decode()


def run(endpoint: str, body: dict) -> str:
    r = requests.post(f"{API}/{endpoint}", headers=HEAD, json=body, timeout=60)
    if r.status_code >= 300:
        sys.exit(f"{endpoint} failed {r.status_code}: {r.text[:400]}")
    task = r.json()["id"]
    print(f"runway task {task} ({endpoint})", flush=True)   # lets a lost output be fetched again by id
    for _ in range(120):
        time.sleep(5)
        t = requests.get(f"{API}/tasks/{task}", headers=HEAD, timeout=30).json()
        if t["status"] == "SUCCEEDED":
            return t["output"][0]
        if t["status"] in ("FAILED", "CANCELLED"):
            sys.exit(f"task {task} {t['status']}: {t.get('failure') or t}")
    sys.exit(f"task {task} timed out")


def main(name: str) -> None:
    if not os.environ.get("RUNWAY_API_KEY"):
        sys.exit("RUNWAY_API_KEY secret is not set")
    spec = yaml.safe_load(Path(f"stories/{name}.yaml").read_text())
    out = Path("out") / name
    out.mkdir(parents=True, exist_ok=True)
    ledger = out / "credits.json"
    spent = json.loads(ledger.read_text())["spent"] if ledger.exists() else 0
    cap = spec["budget_credits"]
    check(spec)
    stills_only = os.environ.get("STILLS_ONLY") == "1"
    default_photo = spec.get("product_photo")

    def charge(n: int) -> None:
        nonlocal spent
        if spent + n > cap:
            sys.exit(f"stopping: {spent} + {n} credits would pass the cap of {cap}")
        spent += n
        ledger.write_text(json.dumps({"spent": spent, "cap": cap}))

    for shot in spec["shots"]:
        still, clip = out / f"{shot['id']}.jpg", out / f"{shot['id']}.mp4"
        if not still.exists():
            refs = [{"uri": data_uri(Path(shot.get("product_photo") or default_photo)), "tag": "product"}]
            if shot.get("person_from"):
                # Keeps the same person across shots: an earlier still is a second reference, tagged @person.
                refs.append({"uri": data_uri(out / f"{shot['person_from']}.jpg"), "tag": "person"})
            charge(COST_STILL)
            url = run("text_to_image", {"model": "gen4_image", "ratio": "720:1280", "promptText": prompts(shot)[0],
                                        "referenceImages": refs})
            still.write_bytes(requests.get(url, timeout=120).content)
            print(f"{shot['id']}: still made ({spent}/{cap} credits)")
        if not clip.exists() and not stills_only:
            charge(COST_CLIP)
            url = run("image_to_video", {"model": "gen4_turbo", "ratio": "720:1280", "duration": 5,
                                         "promptImage": data_uri(still), "promptText": prompts(shot)[1]})
            clip.write_bytes(requests.get(url, timeout=300).content)
            print(f"{shot['id']}: clip made ({spent}/{cap} credits)")
    print(f"done: {spent} of {cap} credits used" + (" (stills only: check them, then run again for the clips)" if stills_only else ""))


if __name__ == "__main__":
    main(sys.argv[1])
