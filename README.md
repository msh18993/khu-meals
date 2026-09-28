# 오늘 뭐 먹지? — 경희대 국제캠퍼스 학생회관 식단

GitHub Pages에서 생협의 공식 주간 식단표를 요일별로 읽기 쉽게 보여주는 정적 웹앱입니다.

## 갱신 방식

- 원문: <https://khucoop.com/35>
- GitHub Actions `Update weekly menu`가 매일 08:10 KST에 공식 이미지를 확인합니다. 생협이 식단표를 늦게 게시해도 다음 날 다시 확인합니다.
- 이번 주에 해당하는 새 이미지가 있을 때만 원본과 요일별 확대 이미지를 커밋합니다. 다음 주 식단표가 미리 게시돼도 이번 주 화면을 조기에 바꾸지 않습니다. 메뉴명·가격을 OCR로 추정해 게시하지 않습니다.
- 이번 주에 검증된 `data/menu.json` 카드 데이터가 있고 출처 이미지가 현재 공식 이미지와 일치하면 카드를 표시합니다. 그렇지 않으면 공식 이미지와 이미지에 인쇄된 날짜를 표시합니다. 이전 주의 카드를 이번 주 메뉴로 보여주지 않습니다.
- 공식 이미지가 아직 이번 주 것으로 확인되지 않으면 원문 링크와 함께 확인 필요 상태를 표시합니다.

## 로컬 실행

```bash
python -m pip install pillow
python scripts/update-menu.py
python -m http.server 8000
```

`http://localhost:8000`에서 확인합니다. 이미지는 변경된 경우에만 다시 저장됩니다.

## 배포

GitHub Pages는 `main` 브랜치의 `/ (root)`에서 배포됩니다. 워크플로가 `disabled_manually` 상태라면 GitHub Actions에서 한 번 활성화해야 예약 실행됩니다.
