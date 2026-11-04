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


def data_uri(path: Path) -> str:
    kind = "png" if path.suffix.lower() == ".png" else "jpeg"
    return f"data:image/{kind};base64," + base64.b64encode(path.read_bytes()).decode()


def run(endpoint: str, body: dict) -> str:
    r = requests.post(f"{API}/{endpoint}", headers=HEAD, json=body, timeout=60)
    if r.status_code >= 300:
        sys.exit(f"{endpoint} failed {r.status_code}: {r.text[:400]}")
    task = r.json()["id"]
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
            ref = data_uri(Path(shot.get("product_photo") or default_photo))
            charge(COST_STILL)
            url = run("text_to_image", {"model": "gen4_image", "ratio": "720:1280", "promptText": shot["still"],
                                        "referenceImages": [{"uri": ref, "tag": "product"}]})
            still.write_bytes(requests.get(url, timeout=120).content)
            print(f"{shot['id']}: still made ({spent}/{cap} credits)")
        if not clip.exists():
            charge(COST_CLIP)
            url = run("image_to_video", {"model": "gen4_turbo", "ratio": "720:1280", "duration": 5,
                                         "promptImage": data_uri(still), "promptText": shot["motion"]})
            clip.write_bytes(requests.get(url, timeout=300).content)
            print(f"{shot['id']}: clip made ({spent}/{cap} credits)")
    print(f"done: {spent} of {cap} credits used")


if __name__ == "__main__":
    main(sys.argv[1])
