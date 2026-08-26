#!/usr/bin/env python3
"""
매일 실행되는 유튜브 쇼츠 트렌드 수집 스크립트 (v3).

바뀐 점 (v2 대비):
  - 후보 수집 방식을 chart=mostPopular 에서 search.list 기반으로 교체.
    mostPopular 차트는 사실상 일반 롱폼(예고편/뮤비 등) 위주라 1분 이하로 거르면
    후보가 통째로 0개가 되는 문제가 있었다 (실제로 v2 첫 실행에서 국가별로
    후보 200~340개 중 1분 이하가 0개였음). search.list에 videoDuration=short
    (4분 이하) + order=viewCount + publishedAfter=최근 N일 조건을 걸어서 "최근에
    조회수 높은 짧은 영상"을 먼저 추리고, 거기서 다시 실제 영상 상세정보를
    videos.list로 가져와 1분 이하 + 실제 쇼츠(9:16) 검증을 그대로 적용한다.
  - "쇼츠" 판정: 1분(60초) 이하 + 실제 세로형(9:16) 쇼츠만 인정.
    후보 각각에 대해 https://www.youtube.com/shorts/<id> 요청을 날려서, 실제로
    쇼츠 플레이어로 응답하는지(진짜 쇼츠) 아니면 /watch로 리다이렉트되는지
    (쇼츠 아님)를 확인한다.
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
MAX_DURATION_SEC = 60      # 진짜 "쇼츠" 기준: 1분 이하만 (그대로 유지)
SEARCH_PAGES_PER_REGION = 2   # 지역 코드 1개당 search.list 최대 페이지(=최대 100개) 후보 수집
SEARCH_LOOKBACK_DAYS = 2      # 최근 며칠 이내 업로드된 영상 중에서 찾을지 (4일 -> 2일로 좁힘)
TOP_N_PER_GROUP = 10       # 카테고리 x 국가그룹 별로 몇 개씩 남길지
SHORTS_CHECK_DELAY_SEC = 0.1  # 유튜브에 너무 빠르게 연타하지 않도록 살짝 텀

# YouTube 공식 videoCategoryId 기반 분류 매핑
# "영화" 카테고리는 제거함(수집 자체를 안 함) - CATEGORY_DEFS에서 빠졌고,
# filter_real_shorts()에서 category가 show/viral이 아니면 검증 단계 가기 전에 버림.
FILM_CATEGORY_IDS = {"1", "30", "31", "32", "33", "34", "35", "36", "37", "38", "39", "40", "41", "44"}
ENTERTAINMENT_CATEGORY_IDS = {"24", "43"}

CATEGORY_DEFS = [
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


def api_get(endpoint: str, params: dict) -> dict:
    url = f"https://www.googleapis.com/youtube/v3/{endpoint}?" + urllib.parse.urlencode(params)
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


def search_region_video_ids(region_code: str) -> list:
    """search.list로 최근 N일 이내 업로드된, 조회수 높은 '짧은'(4분 이하) 영상 후보를
    모은다. mostPopular 차트는 사실상 롱폼 위주라 여기서는 쓰지 않는다."""
    published_after = (
        datetime.now(timezone.utc) - timedelta(days=SEARCH_LOOKBACK_DAYS)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    ids = []
    page_token = None
    for _ in range(SEARCH_PAGES_PER_REGION):
        params = {
            "part": "id",
            "type": "video",
            "q": "#shorts",   # 진짜 원인: search.list는 q(검색어) 없이는 필터만으로 무조건 0개를
                              # 반환한다(브라우저로 직접 검증함). order/publishedAfter 조합 문제가
                              # 아니었음. q를 넣어야만 실제로 결과가 나옴.
            "videoDuration": "short",   # 유튜브 API 기준 4분 이하 (정확한 초 단위 필터는 아래에서 별도 적용)
            "order": "viewCount",   # q가 있으면 order=viewCount + publishedAfter 조합도 정상 동작함
                                     # (실측 확인). 조회수 높은 후보를 먼저 가져와야 페이지 수 제한
                                     # (SEARCH_PAGES_PER_REGION) 안에서 좋은 후보를 더 많이 건짐.
            "regionCode": region_code,
            "publishedAfter": published_after,
            "maxResults": 50,
            "key": API_KEY,
        }
        if page_token:
            params["pageToken"] = page_token
        try:
            data = api_get("search", params)
        except Exception as e:
            print(f"[{region_code}] search API 호출 실패: {e}", file=sys.stderr)
            break

        total_results = (data.get("pageInfo") or {}).get("totalResults")
        print(f"[{region_code}] search 응답: totalResults={total_results}, items={len(data.get('items', []))}", file=sys.stderr)

        for item in data.get("items", []):
            vid = (item.get("id") or {}).get("videoId")
            if vid:
                ids.append(vid)
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return ids


def fetch_video_details(video_ids: list) -> list:
    """search.list로 얻은 video id 목록에 대해 videos.list로 상세정보(통계/길이/카테고리)를
    50개씩 배치로 가져온다."""
    items = []
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i + 50]
        params = {
            "part": "snippet,statistics,contentDetails",
            "id": ",".join(batch),
            "key": API_KEY,
        }
        try:
            data = api_get("videos", params)
        except Exception as e:
            print(f"videos.list 호출 실패: {e}", file=sys.stderr)
            continue
        items.extend(data.get("items", []))
    return items


def collect_group_candidates(region_codes: list) -> list:
    """여러 지역 코드의 후보를 합치고 video id 기준으로 중복 제거한 뒤 상세정보를 가져온다."""
    seen_ids = set()
    all_ids = []
    for region_code in region_codes:
        for vid in search_region_video_ids(region_code):
            if vid not in seen_ids:
                seen_ids.add(vid)
                all_ids.append(vid)
    return fetch_video_details(all_ids)


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
    """카테고리(영화 제외) + 길이 필터를 먼저 적용해 후보를 줄인 다음,
    통과한 것만 실제 쇼츠인지 확인(제일 비싼 단계라 후보를 최대한 줄여놓고 들어감)."""
    records = []
    for item in items:
        rec = to_video_record(item)
        if rec["category"] not in ("show", "viral"):   # 영화로 분류되면 검증 단계까지 안 감
            continue
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
