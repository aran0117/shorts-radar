#!/usr/bin/env python3
"""result(dict) -> 완성된 index.html 문자열을 만드는 렌더러."""

import html as html_escape_lib

CATEGORY_STYLE = {
    "해외영화쇼츠": {"emoji": "🎬", "class": "cat-film"},
    "예능쇼츠": {"emoji": "🎤", "class": "cat-show"},
    "중독성컨텐츠": {"emoji": "🔥", "class": "cat-viral"},
}


def esc(s: str) -> str:
    return html_escape_lib.escape(s or "", quote=True)


def format_count(n: int) -> str:
    n = int(n)
    if n >= 100_000_000:
        return f"{n / 100_000_000:.1f}억"
    if n >= 10_000:
        return f"{n / 10_000:.1f}만"
    return f"{n:,}"


def video_card(v: dict, rank: int) -> str:
    cat = CATEGORY_STYLE.get(v["category"], {"emoji": "📺", "class": "cat-viral"})
    url = f"https://www.youtube.com/watch?v={esc(v['video_id'])}"
    mm, ss = divmod(int(v["duration_sec"]), 60)
    duration_label = f"{mm}:{ss:02d}"

    return f"""
      <a class="card" href="{url}" target="_blank" rel="noopener">
        <div class="thumb-wrap">
          <img class="thumb" src="{esc(v['thumbnail'])}" alt="" loading="lazy" />
          <span class="rank">#{rank}</span>
          <span class="duration">{duration_label}</span>
        </div>
        <div class="card-body">
          <span class="cat-badge {cat['class']}">{cat['emoji']} {esc(v['category'])}</span>
          <h3 class="title">{esc(v['title'])}</h3>
          <p class="channel">{esc(v['channel'])}</p>
          <div class="stat-row">
            <span>👁 {format_count(v['view_count'])}</span>
            <span>👍 {format_count(v['like_count'])}</span>
            <span class="score">점수 {v['score']:.2f}</span>
          </div>
        </div>
      </a>
    """


def country_section(country: dict) -> str:
    cards = "\n".join(
        video_card(v, i + 1) for i, v in enumerate(country["videos"])
    )
    if not cards.strip():
        cards = '<p class="empty">이 지역은 조건에 맞는 영상을 찾지 못했어요 (지역 트렌딩 데이터가 비어있을 수 있음).</p>'
    return f"""
    <section class="country-section">
      <h2 class="country-title">{esc(country['label'])}</h2>
      <div class="grid">
        {cards}
      </div>
    </section>
    """


def render(result: dict) -> str:
    sections = "\n".join(country_section(c) for c in result["countries"])
    generated = esc(result.get("generated_at_kst", ""))

    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>글로벌 쇼츠 트렌드</title>
<meta name="robots" content="noindex, nofollow" />
<style>
  :root {{
    --bg: #0b0d12;
    --card-bg: #141821;
    --card-border: #232838;
    --text: #eef1f7;
    --text-dim: #9aa3b8;
    --accent: #7c9dff;
    --film: #ff9d6c;
    --show: #7ce0c3;
    --viral: #ff7ca8;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Pretendard", "Segoe UI", sans-serif;
  }}
  header {{
    padding: 32px 24px 16px;
    max-width: 1200px;
    margin: 0 auto;
  }}
  header h1 {{
    margin: 0 0 4px;
    font-size: 28px;
    letter-spacing: -0.02em;
  }}
  header p {{
    margin: 0;
    color: var(--text-dim);
    font-size: 14px;
  }}
  main {{
    max-width: 1200px;
    margin: 0 auto;
    padding: 8px 24px 48px;
  }}
  .country-section {{
    margin-top: 36px;
  }}
  .country-title {{
    font-size: 20px;
    margin: 0 0 14px;
    padding-bottom: 8px;
    border-bottom: 1px solid var(--card-border);
  }}
  .grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(230px, 1fr));
    gap: 16px;
  }}
  .card {{
    display: block;
    background: var(--card-bg);
    border: 1px solid var(--card-border);
    border-radius: 12px;
    overflow: hidden;
    text-decoration: none;
    color: var(--text);
    transition: transform 0.15s ease, border-color 0.15s ease;
  }}
  .card:hover {{
    transform: translateY(-3px);
    border-color: var(--accent);
  }}
  .thumb-wrap {{
    position: relative;
    aspect-ratio: 16 / 9;
    background: #000;
  }}
  .thumb {{
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }}
  .rank {{
    position: absolute;
    top: 8px;
    left: 8px;
    background: rgba(0,0,0,0.72);
    color: #fff;
    font-weight: 700;
    font-size: 12px;
    padding: 3px 8px;
    border-radius: 6px;
  }}
  .duration {{
    position: absolute;
    bottom: 8px;
    right: 8px;
    background: rgba(0,0,0,0.72);
    color: #fff;
    font-size: 11px;
    padding: 2px 6px;
    border-radius: 4px;
  }}
  .card-body {{
    padding: 12px;
  }}
  .cat-badge {{
    display: inline-block;
    font-size: 11px;
    font-weight: 600;
    padding: 2px 8px;
    border-radius: 999px;
    margin-bottom: 8px;
  }}
  .cat-film {{ background: rgba(255,157,108,0.15); color: var(--film); }}
  .cat-show {{ background: rgba(124,224,195,0.15); color: var(--show); }}
  .cat-viral {{ background: rgba(255,124,168,0.15); color: var(--viral); }}
  .title {{
    font-size: 14px;
    line-height: 1.4;
    margin: 0 0 6px;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }}
  .channel {{
    font-size: 12px;
    color: var(--text-dim);
    margin: 0 0 10px;
  }}
  .stat-row {{
    display: flex;
    gap: 10px;
    font-size: 12px;
    color: var(--text-dim);
    flex-wrap: wrap;
  }}
  .score {{
    margin-left: auto;
    color: var(--accent);
    font-weight: 600;
  }}
  .empty {{
    color: var(--text-dim);
    font-size: 14px;
  }}
  footer {{
    max-width: 1200px;
    margin: 0 auto;
    padding: 0 24px 40px;
    color: var(--text-dim);
    font-size: 12px;
  }}
</style>
</head>
<body>
  <header>
    <h1>🌏 글로벌 쇼츠 트렌드</h1>
    <p>매일 자동 갱신 · 마지막 업데이트: {generated} (KST) · 3분 이하 영상 · 조회수+좋아요 합산 점수 기준 국가별 TOP 10</p>
  </header>
  <main>
    {sections}
  </main>
  <footer>
    개인용으로 생성된 페이지입니다. 데이터 출처: YouTube Data API (mostPopular).
  </footer>
</body>
</html>
"""
