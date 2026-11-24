"""Can we call Wanderu's search API directly, without a browser each time?

Tests three things:
  1. Does the captured request replay at all from plain httpx?
  2. Is the anonymous X-TOKEN actually required?
  3. Can we change departDatetime and swap origin/dest freely?
"""
from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path

import httpx

RAW = Path(__file__).resolve().parent.parent / "data" / "raw" / "_probe"
BODY = json.loads((RAW / "wanderu_request_body.json").read_text(encoding="utf-8"))

URL = "https://api.wanderu.com/v2/psearch.json"
HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "en-US",
    "content-type": "text/plain",
    "referer": "https://www.wanderu.com/",
    "user-agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                   " (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
}


def call(label: str, body: dict) -> None:
    try:
        with httpx.Client(timeout=60) as c:
            r = c.post(URL, headers=HEADERS, content=json.dumps(body))
        txt = r.text
        n = 0
        carriers: dict[str, int] = {}
        if r.status_code == 200:
            try:
                res = json.loads(txt).get("result") or []
                n = len(res)
                for t in res:
                    cc = t.get("carrier")
                    carriers[cc] = carriers.get(cc, 0) + 1
            except Exception:
                pass
        top = ", ".join(f"{k}:{v}" for k, v in
                        sorted(carriers.items(), key=lambda kv: -kv[1])[:8])
        print(f"  {label:<34} {r.status_code}  {len(txt):>8}b  trips={n:<4} {top}")
        if r.status_code != 200:
            print(f"      {txt[:200]}")
    except Exception as e:
        print(f"  {label:<34} FAILED {type(e).__name__}: {str(e)[:120]}")


print("origin:", BODY["originPlace"]["address_components"][0]["long_name"])
print("dest:  ", BODY["destPlace"]["address_components"][0]["long_name"])
print("date:  ", BODY["departDatetime"])
print()

# 1. straight replay
call("replay as captured", BODY)

# 2. without the anonymous token
no_tok = copy.deepcopy(BODY)
no_tok.pop("X-TOKEN", None)
call("without X-TOKEN", no_tok)

# 3. different date, fresh batchId
other = copy.deepcopy(BODY)
other["departDatetime"] = "2026-11-22"
other["batchId"] = str(uuid.uuid4())
call("new date 2026-11-22", other)

# 4. reversed direction (NYC -> PHL)
rev = copy.deepcopy(BODY)
rev["originPlace"], rev["destPlace"] = BODY["destPlace"], BODY["originPlace"]
rev["departDatetime"] = "2026-11-22"
rev["batchId"] = str(uuid.uuid4())
call("reversed NYC->PHL 2026-11-22", rev)

# 5. reversed, no token
rev2 = copy.deepcopy(rev)
rev2.pop("X-TOKEN", None)
rev2["batchId"] = str(uuid.uuid4())
call("reversed, no token", rev2)
