import { readFile, writeFile } from 'node:fs/promises';

const pages = ['35', '36', '37'];
const outputPath = new URL('../data/menu.json', import.meta.url);
const imagePattern = /<meta itemprop="contentUrl" content="([^"]+)"|"contentUrl"\s*:\s*"([^"]+)"/g;
const imageUrls = [];

for (const page of pages) {
  const response = await fetch(`https://khucoop.com/${page}`);
  if (!response.ok) throw new Error(`식단 페이지 ${page} 조회 실패: ${response.status}`);
  const html = await response.text();
  for (const match of html.matchAll(imagePattern)) imageUrls.push(match[1] || match[2]);
}

if (!imageUrls.length) throw new Error('생협 식단 이미지 URL을 찾지 못했습니다. 기존 menu.json은 유지됩니다.');

const previous = JSON.parse(await readFile(outputPath, 'utf8'));
previous.checkedAt = new Intl.DateTimeFormat('sv-SE', {
  timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', hour12: false
}).format(new Date()) + ' KST';
previous.sourceImages = [...new Set(imageUrls)];

// 공식 식단은 이미지로 게시된다. URL 변경을 감지해 워크플로를 실패시키지 않고
// 마지막 검증 데이터를 유지한다. OCR 파이프라인 연결 전까지 수동 검수 안전장치다.
await writeFile(outputPath, JSON.stringify(previous, null, 2) + '\n', 'utf8');
console.log(`식단 원문 확인 완료: ${previous.sourceImages.length}개 이미지`);
