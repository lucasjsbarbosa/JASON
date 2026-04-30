"""One-off audit: for every channel in canais_ids.txt, fetch the latest video's
publishedAt and report how stale each channel is. Cost: ~1 + N quota units."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx

ENV_LINE = next(
    line for line in Path(".env").read_text().splitlines()
    if line.startswith("YOUTUBE_DATA_API_KEY=")
)
API_KEY = ENV_LINE.split("=", 1)[1].strip()

mapping: dict[str, str] = {}
for line in Path("canais_ids.txt").read_text(encoding="utf-8").splitlines():
    if not line.strip():
        continue
    parts = line.split()
    if len(parts) >= 2 and parts[1].startswith("UC"):
        mapping[parts[0]] = parts[1]

ids = list(mapping.values())
handle_for = {v: k for k, v in mapping.items()}

with httpx.Client(timeout=15.0) as client:
    r = client.get(
        "https://www.googleapis.com/youtube/v3/channels",
        params={"part": "contentDetails,snippet,statistics", "id": ",".join(ids), "key": API_KEY},
    )
    r.raise_for_status()
    rows = []
    for item in r.json()["items"]:
        cid = item["id"]
        title = item["snippet"]["title"]
        subs = int(item["statistics"].get("subscriberCount", 0))
        video_count = int(item["statistics"].get("videoCount", 0))
        uploads = item["contentDetails"]["relatedPlaylists"]["uploads"]
        try:
            r2 = client.get(
                "https://www.googleapis.com/youtube/v3/playlistItems",
                params={"part": "snippet", "playlistId": uploads, "maxResults": 1, "key": API_KEY},
            )
            if r2.status_code != 200:
                age_days = -1  # uploads playlist gone (deleted/private/empty)
            else:
                items = r2.json().get("items", [])
                if items:
                    pub = items[0]["snippet"]["publishedAt"]
                    pub_dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
                    age_days = (datetime.now(UTC) - pub_dt).days
                else:
                    age_days = -1
        except httpx.HTTPError:
            age_days = -1
        rows.append((handle_for[cid], title, subs, video_count, age_days, cid))

rows.sort(key=lambda r: r[4] if r[4] >= 0 else 99999)
print(f"{'handle':<26} {'title':<30} {'subs':>10} {'videos':>7} {'idade':>10}  status")
print("-" * 96)
for h, title, subs, vcount, age, _cid in rows:
    if age < 0:
        flag, age_str = "VAZIO", "n/a"
    elif age < 30:
        flag, age_str = "FRESCO", f"{age}d"
    elif age < 180:
        flag, age_str = "ATIVO ", f"{age}d"
    elif age < 365:
        flag, age_str = "MORNO ", f"{age}d"
    else:
        flag, age_str = "MORTO ", f"{age // 365}a {age % 365}d"
    print(f"{h:<26} {title[:30]:<30} {subs:>10,} {vcount:>7} {age_str:>10}  {flag}")
