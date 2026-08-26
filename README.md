# 글로벌 쇼츠 트렌드 (개인용)

매일 자동으로 미국 / 일본 / 홍콩의 유튜브 인기 급상승(mostPopular) 영상 중
3분 이하 영상만 걸러서, 조회수+좋아요 합산 점수로 국가별 TOP 10을 뽑아
`index.html` 페이지로 만들어주는 완전 무료 자동화입니다.

- 실행 주체: GitHub Actions (매일 UTC 00:00 = 한국시간 09:00 자동 실행)
- 결과 확인: GitHub Pages (`https://<내깃허브아이디>.github.io/<저장소이름>/`)
- 비용: 0원 (개인 GitHub 무료 플랜 범위 안에서 충분)

---

## 1. YouTube Data API 키 발급받기 (5분)

1. https://console.cloud.google.com/ 접속 → 구글 계정으로 로그인
2. 상단 프로젝트 선택 드롭다운 → "새 프로젝트" → 이름 아무거나 (예: `shorts-trend`) → 만들기
3. 좌측 메뉴 "API 및 서비스" → "라이브러리" 이동
4. 검색창에 `YouTube Data API v3` 검색 → 클릭 → "사용 설정(Enable)" 버튼 클릭
5. 좌측 메뉴 "API 및 서비스" → "사용자 인증 정보(Credentials)" 이동
6. 상단 "+ 사용자 인증 정보 만들기" → "API 키" 선택 → 키가 생성됨 (예: `AIzaSy...`로 시작하는 문자열)
7. 이 키를 복사해서 잘 보관 (다음 단계에서 GitHub Secret으로 등록할 거예요)
8. (선택, 권장) 방금 만든 키 옆 "키 제한" 클릭 → "API 제한사항"에서 "YouTube Data API v3"만 체크 → 저장
   → 이렇게 하면 이 키로 다른 구글 API는 호출 못 하게 제한되어 더 안전합니다.

무료 할당량: 하루 10,000 유닛. 이 스크립트는 하루 한 번 실행 시 국가당 최대 3번 호출(3개국 = 9번)만 쓰므로 전혀 문제 없습니다.

---

## 2. GitHub 저장소(repo) 만들기

1. https://github.com/new 접속
2. Repository name: 원하는 이름 (예: `my-shorts-trend`)
3. **Public**으로 설정 (⚠️ GitHub 무료 플랜은 Private 저장소에서는 GitHub Pages를 못 씁니다. Public이어야 페이지가 무료로 열립니다.
   대신 아무한테도 링크를 안 알려주면 사실상 나만 아는 페이지가 됩니다. 영상 정보 자체도 이미 유튜브에 공개된 데이터라 민감할 게 없어요.)
4. "Create repository" 클릭

---

## 3. 파일 올리기

받으신 압축파일(shorts-trend.zip)의 압축을 풀면 아래 구조입니다. **폴더 구조를 그대로 유지**해서 올려야 합니다.

```
.github/workflows/daily.yml
fetch_trending.py
render_html.py
README.md
```

올리는 방법 (Git 안 써도 됨):

1. 방금 만든 저장소 페이지에서 "Add file" → "Upload files" 클릭
2. 압축 푼 폴더 안의 파일/폴더를 통째로 브라우저 창에 드래그 앤 드롭
   (`.github` 폴더까지 통째로 끌어다 놓으면 구조가 유지됩니다)
3. 아래 "Commit changes" 클릭

---

## 4. API 키를 GitHub Secret으로 등록하기

1. 저장소 페이지 → "Settings" 탭
2. 좌측 "Secrets and variables" → "Actions"
3. "New repository secret" 클릭
4. Name: `YOUTUBE_API_KEY`
5. Secret: 1단계에서 복사해둔 API 키 붙여넣기
6. "Add secret" 클릭

---

## 5. GitHub Pages 켜기

1. 저장소 "Settings" → 좌측 "Pages"
2. "Build and deployment" → Source: **Deploy from a branch**
3. Branch: `main` / `/ (root)` 선택 → Save

몇 분 뒤 이 화면에 페이지 주소가 뜹니다:
`https://<내깃허브아이디>.github.io/<저장소이름>/`

이 주소가 나만 보는 트렌드 페이지 링크입니다. 즐겨찾기 해두세요.

---

## 6. 첫 실행 (수동으로 한 번 돌려보기)

기본적으로 매일 자동 실행되지만, 처음엔 바로 확인해보고 싶을 테니 수동으로 한 번 실행해봅니다.

1. 저장소 "Actions" 탭 → 좌측 "Daily Global Shorts Trend" 클릭
2. 우측 "Run workflow" 버튼 → "Run workflow" 클릭
3. 1~2분 후 초록색 체크가 뜨면 성공. 5단계에서 확인한 Pages 주소 접속 → 결과 확인

이후로는 매일 한국시간 오전 9시에 자동으로 갱신됩니다.

---

## 커스터마이징

`fetch_trending.py` 상단 "설정" 부분만 수정하면 됩니다.

- `COUNTRIES`: 국가 코드/이름 변경 (예: 홍콩 대신 대만 `TW`로)
- `MAX_DURATION_SEC`: 몇 분 이하까지 "쇼츠"로 볼지 (기본 180초 = 3분)
- `TOP_N_PER_COUNTRY`: 국가별 몇 개씩 보여줄지 (기본 10개)
- 카테고리 분류 기준(`FILM_CATEGORY_IDS`, `ENTERTAINMENT_CATEGORY_IDS`)도 필요하면 조정 가능
- 자동 실행 시각을 바꾸고 싶으면 `.github/workflows/daily.yml`의 `cron` 값 수정
  (UTC 기준입니다. 한국시간 - 9시간 = UTC)

수정 후 GitHub 웹사이트에서 해당 파일을 열어 연필 아이콘(Edit) 눌러 직접 고치고 커밋하면 됩니다.
