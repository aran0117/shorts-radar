#!/usr/bin/env python3
"""
매일 실행되는 유튜브 쇼츠 트렌드 수집 스크립트 (v2).

바뀐 점 (v1 대비):
  - "쇼츠" 판정을 훨씬 엄격하게: 1분(60초) 이하 + 실제 세로형(9:16) 쇼츠만 인정.
    유튜브 mostPopular 차트에는 롱폼(예고편 등)도 섞여 있어서, 길이만 보고
    거르면 "짧은 롱폼"이 섞여 들어온다. 그래서 후보 각각에 대해
    https://www.youtube.com/shorts/<id> 요청을 날려서, 실제로 쇼츠 플레이어로
    응답하는지(진짜 쇼츠) 아니면 /watch로 리다이렉트되는지(쇼츠 아님)를 확인한다.
  - 국가: 미국(US), 일본(JP), 홍콩+대만(HK, TW를 하나로 합쳐서 "홍콩·대만" 그룹으로 랭킹)
  - 카테고리별 x 국가(그룹)별로 각각 TOP 10을 따로 뽑는다.
  - 결과를 "날짜별 스냅샷" 파일로 계속 누적 저장한다 (덮어쓰지 않음).
    -> data/days/<YYYY-MM-DD>.json
    -> data/index.json (지금까지 쌓인 날짜 목록, 프론트엔드 페이지네이션용)

  index.html은 이 데이터 파일들을 읽어서 카테고리 탭 / 국가 탭 / 날짜 페이지네이션을
  자바스크립트로 그려주는 정적 SPA라서, 이 스크립트는 더 이상 index.html을 직접
  생성하지 않는다.
"""

import json
import os
import re
import sys
import time
import http.client
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta

API_KEY = os.environ.get("YOUTUBE_API_KEY")
if not API_KEY:
    print("ERROR: YOUTUBE_API_KEY 환경변수가 설정되어 있지 않습니다.", file=sys.stderr)
    sys.exit(1)

# ── 설정: 필요하면 이 부분만 바꾸면 됩니다 ──────────────────────────
# region_codes: 실제 유튜브 mostPopular API에 넣을 국가 코드(여러 개면 합쳐서 하나의
#               그룹으로 랭킹). label: 화면에 보여줄 이름. key: 데이터 파일 내부 식별자.
REGION_GROUPS = [
    {"key": "US", "label": "🇺🇸 미국", "region_codes": ["US"]},
    {"key": "JP", "label": "🇯🇵 일본", "region_codes": ["JP"]},
    {"key": "HK_TW", "label": "🇭🇰🇹🇼 홍콩·대만", "region_codes": ["HK", "TW"]},
]
MAX_DURATION_SEC = 60      # 진짜 "쇼츠" 기준: 1분 이하만
PAGES_PER_REGION = 4       # 지역 코드 1개당 최대 4페이지(=최대 200개) 후보 수집
TOP_N_PER_GROUP = 10       # 카테고리 x 국가그룹 별로 몇 개씩 남길지
SHORTS_CHECK_DELAY_SEC = 0.1  # 유튜브에 너무 빠르게 연타하지 않도록 살짝 텀

# YouTube 공식 videoCategoryId 기반 3분류 매핑
FILM_CATEGORY_IDS = {"1", "30", "31", "32", "33", "34", "35", "36", "37", "38", "39", "40", "41", "44"}
ENTERTAINMENT_CATEGORY_IDS = {"24", "43"}

CATEGORY_DEFS = [
    {"key": "film", "label": "🎬 영화"},
    {"key": "show", "label": "🎤 예능"},
    {"key": "viral", "label": "🔥 화제/이슈"},
]


def categorize(category_id: str) -> str:
    if category_id in FILM_CATEGORY_IDS:
        return "film"
    if category_id in ENTERTAINMENT_CATEGORY_IDS:
        return "show"
    return "viral"


DURATION_RE = re.compile(
    r"P(?:(?P<days>\d+)D)?T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?"
)


def parse_duration_seconds(iso_duration: str) -> int:
    m = DURATION_RE.match(iso_duration or "")
    if not m:
        return 0
    parts = m.groupdict()
    days = int(parts["days"] or 0)
    hours = int(parts["hours"] or 0)
    minutes = int(parts["minutes"] or 0)
    seconds = int(parts["seconds"] or 0)
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def api_get(params: dict) -> dict:
    url = "https://www.googleapis.com/youtube/v3/videos?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def is_real_vertical_short(video_id: str) -> bool:
    """
    https://www.youtube.com/shorts/<id> 로 리다이렉트 없이 200이 오면 진짜 쇼츠(9:16),
    /watch?v=... 로 리다이렉트되면 쇼츠가 아닌 일반(롱폼) 영상이다.
    네트워크 오류 등 판단이 애매하면 안전하게 "쇼츠 아님"으로 처리한다.
    """
    conn = None
    try:
        conn = http.client.HTTPSConnection("www.youtube.com", timeout=10)
        conn.request(
            "GET",
            f"/shorts/{video_id}",
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        resp = conn.getresponse()
        body = resp.read()  # 커넥션 재사용을 위해 body를 반드시 읽어준다
        if resp.status in (301, 302, 303, 307, 308):
            location = resp.getheader("Location", "") or ""
            return "/watch" not in location
        if resp.status == 200:
            # 일부는 200을 주면서 본문 안에서 canonical 링크가 /watch로 잡히는 경우가
            # 있어 한 번 더 확인한다.
            text = body.decode("utf-8", errors="ignore")
            if f'"canonical" href="https://www.youtube.com/watch' in text:
                return False
            return True
        return False
    except Exception:
        return False
    finally:
        if conn:
            conn.close()


def fetch_region_candidates(region_code: str) -> list:
    candidates = []
    page_token = None
    for _ in range(PAGES_PER_REGION):
        params = {
            "part": "snippet,statistics,contentDetails",
            "chart": "mostPopular",
            "regionCode": region_code,
            "maxResults": 50,
            "key": API_KEY,
        }
        if page_token:
            params["pageToken"] = page_token
        try:
            data = api_get(params)
        except Exception as e:
            print(f"[{region_code}] API 호출 실패: {e}", file=sys.stderr)
            break

        candidates.extend(data.get("items", []))
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return candidates


def collect_group_candidates(region_codes: list) -> list:
    """여러 지역 코드의 후보를 합치고 video id 기준으로 중복 제거."""
    seen_ids = set()
    merged = []
    for region_code in region_codes:
        for item in fetch_region_candidates(region_code):
            vid = item.get("id")
            if vid and vid not in seen_ids:
                seen_ids.add(vid)
                merged.append(item)
    return merged


def to_video_record(item: dict) -> dict:
    content = item.get("contentDetails", {})
    stats = item.get("statistics", {})
    snippet = item.get("snippet", {})
    return {
        "video_id": item.get("id"),
        "title": snippet.get("title", ""),
        "channel": snippet.get("channelTitle", ""),
        "published_at": snippet.get("publishedAt", ""),
        "thumbnail": (snippet.get("thumbnails", {}).get("high")
                      or snippet.get("thumbnails", {}).get("medium")
                      or snippet.get("thumbnails", {}).get("default")
                      or {}).get("url", ""),
        "category": categorize(str(snippet.get("categoryId", ""))),
        "duration_sec": parse_duration_seconds(content.get("duration", "")),
        "view_count": int(stats.get("viewCount", 0)),
        "like_count": int(stats.get("likeCount", 0)),
    }


def filter_real_shorts(items: list) -> list:
    """길이 필터를 먼저 적용해 후보를 줄인 다음, 통과한 것만 실제 쇼츠인지 확인."""
    records = []
    for item in items:
        rec = to_video_record(item)
        if rec["duration_sec"] == 0 or rec["duration_sec"] > MAX_DURATION_SEC:
            continue
        records.append(rec)

    verified = []
    for rec in records:
        if is_real_vertical_short(rec["video_id"]):
            verified.append(rec)
        time.sleep(SHORTS_CHECK_DELAY_SEC)
    return verified


def score_and_rank(records: list, top_n: int) -> list:
    if not records:
        return []
    import math
    log_views = [math.log1p(v["view_count"]) for v in records]
    log_likes = [math.log1p(v["like_count"]) for v in records]

    def norm(values):
        lo, hi = min(values), max(values)
        if hi - lo < 1e-9:
            return [0.5 for _ in values]
        return [(v - lo) / (hi - lo) for v in values]

    nv = norm(log_views)
    nl = norm(log_likes)
    for i, v in enumerate(records):
        v["score"] = round(0.5 * nv[i] + 0.5 * nl[i], 4)

    records.sort(key=lambda v: v["score"], reverse=True)
    return records[:top_n]


def main():
    kst = timezone(timedelta(hours=9))
    now_kst = datetime.now(kst)
    today_str = now_kst.strftime("%Y-%m-%d")

    # group_key -> verified short records (아직 카테고리로 안 나눔)
    group_verified = {}
    for group in REGION_GROUPS:
        print(f"[{group['key']}] 후보 수집 중...")
        candidates = collect_group_candidates(group["region_codes"])
        print(f"[{group['key']}] 후보 {len(candidates)}개 -> 1분 이하 필터 -> 실제 쇼츠 검증 중 (시간이 좀 걸립니다)")
        verified = filter_real_shorts(candidates)
        print(f"[{group['key']}] 실제 쇼츠로 확인된 영상 {len(verified)}개")
        group_verified[group["key"]] = verified

    snapshot = {
        "date": today_str,
        "generated_at_kst": now_kst.strftime("%Y-%m-%d %H:%M:%S"),
        "categories": {},
    }

    for cat in CATEGORY_DEFS:
        cat_key = cat["key"]
        snapshot["categories"][cat_key] = {}
        for group in REGION_GROUPS:
            group_key = group["key"]
            pool = [v for v in group_verified[group_key] if v["category"] == cat_key]
            ranked = score_and_rank(pool, TOP_N_PER_GROUP)
            snapshot["categories"][cat_key][group_key] = ranked

    os.makedirs("data/days", exist_ok=True)
    with open(f"data/days/{today_str}.json", "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)

    index_path = "data/index.json"
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            index_data = json.load(f)
    else:
        index_data = {"dates": [], "categories": CATEGORY_DEFS, "groups": REGION_GROUPS}

    index_data["categories"] = CATEGORY_DEFS
    index_data["groups"] = [{"key": g["key"], "label": g["label"]} for g in REGION_GROUPS]
    if today_str not in index_data["dates"]:
        index_data["dates"].append(today_str)
    index_data["dates"].sort()

    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index_data, f, ensure_ascii=False, indent=2)

    print(f"완료: data/days/{today_str}.json, data/index.json 갱신됨")


if __name__ == "__main__":
    main()
