# 오늘 뭐 먹지? — 경희대 국제캠퍼스 학생회관 식단

GitHub Pages에서 생협의 공식 주간 식단표를 요일별로 읽기 쉽게 보여주는 정적 웹앱입니다.

## 갱신 방식

- 원문: <https://khucoop.com/35>
- GitHub Actions `Update weekly menu`가 매일 08:10 KST 예약으로 공식 이미지를 확인합니다(실제 실행은 GitHub 사정에 따라 늦어질 수 있습니다). 메뉴명·가격을 OCR로 추정해 게시하지 않습니다.
- 현재 주에 검증된 카드가 없으면 원본과 요일별 확대 이미지를 갱신합니다. 검증된 카드가 있는 상태에서 공식 이미지가 교체되면, 기존 카드/원본 묶음을 덮어쓰지 않고 `data/pending-menu.json`에 재검토 대상으로 등록합니다. 화면에는 이전 검증 카드임을 알리는 안내와 새 원본 링크를 표시합니다.
- 기존 Hermes 갱신 작업은 매일 09:10·12:10·17:10 KST에 `scripts/review-gate.py`로 출처 URL·실제 이미지 SHA-256·날짜 범위·게시된 원본 메타데이터를 확인합니다. 변경이 없으면 모델을 호출하지 않습니다. 변경이 있으면 이미지를 직접 판독하여 전사와 공식 이미지 묶음을 함께 게시합니다. 실패한 검토는 다음 확인에서도 계속 재시도 대상으로 남습니다.
- 일요일에는 기존 주간 갱신처럼 다음 주 식단을 미리 검토합니다. 이미지 URL의 업로드 날짜는 후보 선택용 힌트일 뿐이며, 게시 전에 이미지에 인쇄된 월~금 날짜를 직접 확인합니다.
- 검증된 `data/menu.json`의 출처 URL과 SHA-256이 공식 메타데이터와 일치할 때만 카드를 표시합니다. 이전 주 카드를 이번 주 메뉴로 표시하거나, 새 원본을 읽지 않고 출처만 갈아 끼우지 않습니다.
- 전사가 아직 없거나 이번 주 공식 이미지가 확인되지 않은 경우에는 공식 이미지/확인 필요 상태와 원문 링크를 제공합니다.

### 검토 후 게시

원본을 직접 읽은 후 `data/menu.json`의 메뉴·`sourceImages`·`sourceSha256`을 갱신하고 다음을 실행합니다.

```bash
python scripts/update-menu.py --publish-reviewed
python -m unittest discover -s tests -p 'test_*.py' -v
```

카드의 출처 URL·해시·5일 날짜가 새 원본과 맞지 않으면 검토 게시를 거부합니다. 검토된 JSON, 공식 메타데이터, 원본, 요일 이미지, pending 정리와 `sw.js` 캐시 버전 변경을 하나의 커밋으로 게시합니다. 일반 수집기는 검토 완료로 처리할 수 없습니다.

## 로컬 실행

```bash
python -m pip install pillow
python scripts/update-menu.py
python -m http.server 8000
```

`http://localhost:8000`에서 확인합니다. 이미지는 변경된 경우에만 다시 저장됩니다.

## 배포

GitHub Pages는 `main` 브랜치의 `/ (root)`에서 배포됩니다. 워크플로가 `disabled_manually` 상태라면 GitHub Actions에서 한 번 활성화해야 예약 실행됩니다.
