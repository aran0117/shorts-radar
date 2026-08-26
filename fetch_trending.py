#!/usr/bin/env python3
"""
매일 실행되는 유튜브 트렌드 수집 스크립트.

- 대상 국가: US(미국), JP(일본), HK(홍콩 - 중국 대체)
- 대상: mostPopular 차트에서 재생시간 3분 이하 영상만 (쇼츠/쇼츠형 콘텐츠)
- 정렬: 조회수 + 좋아요 합산 점수 (로그 스케일 정규화 후 50:50 가중 평균)
- 국가별 상위 10개만 최종 저장

결과물:
  data/latest.json   -> 원본 데이터 (다음 실행/디버깅용)
  index.html         -> GitHub Pages에 게시되는 최종 페이지
"""

import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta

API_KEY = os.environ.get("YOUTUBE_API_KEY")
if not API_KEY:
    print("ERROR: YOUTUBE_API_KEY 환경변수가 설정되어 있지 않습니다.", file=sys.stderr)
    sys.exit(1)

# ── 설정: 필요하면 이 부분만 바꾸면 됩니다 ──────────────────────────
COUNTRIES = [
    ("US", "🇺🇸 미국"),
    ("JP", "🇯🇵 일본"),
    ("HK", "🇭🇰 홍콩"),   # 중국(CN)은 유튜브 공식 차단 지역이라 홍콩으로 대체
]
MAX_DURATION_SEC = 180   # 3분 이하만 "쇼츠 성격 영상"으로 취급
TOP_N_PER_COUNTRY = 10
PAGES_PER_COUNTRY = 3    # 50개씩 최대 3페이지(=150개) 후보 중에서 필터링
# ────────────────────────────────────────────────────────────────

# YouTube 공식 videoCategoryId 기반 3분류 매핑
FILM_CATEGORY_IDS = {"1", "30", "31", "32", "33", "34", "35", "36", "37", "38", "39", "40", "41", "44"}
ENTERTAINMENT_CATEGORY_IDS = {"24", "43"}

def categorize(category_id: str) -> str:
    if category_id in FILM_CATEGORY_IDS:
        return "해외영화쇼츠"
    if category_id in ENTERTAINMENT_CATEGORY_IDS:
        return "예능쇼츠"
    return "중독성컨텐츠"


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


def fetch_country_candidates(region_code: str) -> list:
    candidates = []
    page_token = None
    for _ in range(PAGES_PER_COUNTRY):
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


def build_ranking(items: list) -> list:
    filtered = []
    for it in items:
        content = it.get("contentDetails", {})
        duration_sec = parse_duration_seconds(content.get("duration", ""))
        if duration_sec == 0 or duration_sec > MAX_DURATION_SEC:
            continue

        stats = it.get("statistics", {})
        view_count = int(stats.get("viewCount", 0))
        like_count = int(stats.get("likeCount", 0))  # 좋아요 비공개 영상은 0 처리

        snippet = it.get("snippet", {})
        filtered.append({
            "video_id": it.get("id"),
            "title": snippet.get("title", ""),
            "channel": snippet.get("channelTitle", ""),
            "published_at": snippet.get("publishedAt", ""),
            "thumbnail": (snippet.get("thumbnails", {}).get("high")
                          or snippet.get("thumbnails", {}).get("medium")
                          or snippet.get("thumbnails", {}).get("default")
                          or {}).get("url", ""),
            "category": categorize(str(snippet.get("categoryId", ""))),
            "duration_sec": duration_sec,
            "view_count": view_count,
            "like_count": like_count,
        })

    if not filtered:
        return []

    # 로그 스케일 min-max 정규화 후 50:50 가중 합산 점수
    import math
    log_views = [math.log1p(v["view_count"]) for v in filtered]
    log_likes = [math.log1p(v["like_count"]) for v in filtered]

    def norm(values):
        lo, hi = min(values), max(values)
        if hi - lo < 1e-9:
            return [0.5 for _ in values]
        return [(v - lo) / (hi - lo) for v in values]

    nv = norm(log_views)
    nl = norm(log_likes)

    for i, v in enumerate(filtered):
        v["score"] = round(0.5 * nv[i] + 0.5 * nl[i], 4)

    filtered.sort(key=lambda v: v["score"], reverse=True)
    return filtered[:TOP_N_PER_COUNTRY]


def main():
    kst = timezone(timedelta(hours=9))
    now_kst = datetime.now(kst)

    result = {
        "generated_at_kst": now_kst.strftime("%Y-%m-%d %H:%M:%S"),
        "countries": [],
    }

    for region_code, label in COUNTRIES:
        print(f"[{region_code}] 수집 중...")
        candidates = fetch_country_candidates(region_code)
        print(f"[{region_code}] 후보 {len(candidates)}개 수집, 3분 이하 필터링 후 랭킹 계산")
        ranking = build_ranking(candidates)
        result["countries"].append({
            "code": region_code,
            "label": label,
            "videos": ranking,
        })

    os.makedirs("data", exist_ok=True)
    with open("data/latest.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    render_html(result)
    print("완료: data/latest.json, index.html 갱신됨")


def render_html(result: dict):
    from render_html import render
    html = render(result)
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)


if __name__ == "__main__":
    main()
