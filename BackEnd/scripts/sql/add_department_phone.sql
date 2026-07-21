-- 학과 대표 연락처 추가
--
-- "컴공 전화번호 뭐야?" 류 질문을 DB로 바로 답하기 위한 컬럼.
-- 학과 카드(dept_card)에 📞 한 줄로 노출된다.
--
-- 값 규칙:
--   - 전화번호만 저장한다. 팩스는 넣지 않는다 — 학생이 팩스로 전화 걸 일이 없고,
--     한 칸에 섞이면 어느 쪽이 전화인지 구분이 안 된다.
--   - 번호가 여러 개면 학교 안내 순서대로 쉼표로 잇는다(대표번호가 앞).
--   - 학교 안내에 전화번호가 없는 학과는 NULL로 둔다. 지어내지 않는다.
--
-- server.py는 create_all만 호출해 기존 테이블에 컬럼을 추가하지 않으므로 수동 실행 필요.
--   docker exec -i <postgres컨테이너> psql -U <user> -d <db> < add_department_phone.sql
--
-- 출처: 학교 학과 안내 페이지 (2026-07 기준)

ALTER TABLE department ADD COLUMN IF NOT EXISTS phone VARCHAR;

-- ── 소프트웨어(SW)융합대학 ────────────────────────────────────────
UPDATE department SET phone = '042-630-9710' WHERE name = '컴퓨터공학전공';
UPDATE department SET phone = '042-630-9850' WHERE name = '컴퓨터·소프트웨어전공';
UPDATE department SET phone = '042-630-9346' WHERE name = '글로벌미디어영상학과';
UPDATE department SET phone = '042-630-9270' WHERE name = '게임소프트웨어전공';
UPDATE department SET phone = '042-630-9758' WHERE name = '게임그래픽전공';
-- 미디어디자인·영상전공: 학교 안내에 팩스와 '공고·홍보문의'만 있고 대표 전화가 없어 NULL 유지

-- ── 철도대학 ─────────────────────────────────────────────────────
UPDATE department SET phone = '042-630-9346'                             WHERE name = '글로벌철도학과';
UPDATE department SET phone = '042-629-6710'                             WHERE name = '철도건설시스템전공';
UPDATE department SET phone = '042-630-9720'                             WHERE name = '건축공학전공';
UPDATE department SET phone = '042-630-9770, 042-630-9871, 042-630-9199' WHERE name = '철도경영학과';
UPDATE department SET phone = '042-629-6710'                             WHERE name = '철도전기시스템전공';
UPDATE department SET phone = '042-629-6730, 042-630-9700'               WHERE name = '철도소프트웨어전공';
UPDATE department SET phone = '042-629-6780, 042-629-6778'               WHERE name = '철도차량시스템학과';
UPDATE department SET phone = '042-630-9751'                             WHERE name = '철도자율전공';

-- ── 외식조리대학 ─────────────────────────────────────────────────
UPDATE department SET phone = '042-629-6652'                             WHERE name = '글로벌조리전공';
UPDATE department SET phone = '042-629-6864'                             WHERE name = 'Lyfe조리전공';
UPDATE department SET phone = '042-629-6654'                             WHERE name = '글로벌외식,조리경영전공';
UPDATE department SET phone = '042-629-6821'                             WHERE name = '외식조리전공';
UPDATE department SET phone = '042-629-6582'                             WHERE name = '한식·조리과학전공';
UPDATE department SET phone = '042-630-9370'                             WHERE name = '외식,조리경영전공';
UPDATE department SET phone = '042-630-9250'                             WHERE name = '제과제빵·조리전공';
UPDATE department SET phone = '042-630-9380, 042-630-9740'               WHERE name = '외식조리영양학과';
UPDATE department SET phone = '042-630-9268, 042-630-9760, 042-630-9768' WHERE name = '호텔관광경영학과';
UPDATE department SET phone = '042-630-9257'                             WHERE name = '외식조리자율전공';

-- ── 보건복지대학 ─────────────────────────────────────────────────
UPDATE department SET phone = '042-630-9830'                             WHERE name = '사회복지학과';
UPDATE department SET phone = '042-630-9820, 042-630-9827'               WHERE name = '작업치료학과';
UPDATE department SET phone = '042-630-9220'                             WHERE name = '언어치료·청각재활학과';
UPDATE department SET phone = '042-630-4610'                             WHERE name = '보건의료경영학과';
UPDATE department SET phone = '042-630-9360, 042-630-9367'               WHERE name = '유아교육과';
UPDATE department SET phone = '042-629-6670, 042-629-6675'               WHERE name = '뷰티디자인경영학과';
UPDATE department SET phone = '042-630-9280'                             WHERE name = '응급구조학과';
UPDATE department SET phone = '042-629-6770'                             WHERE name = '소방·안전학부';
UPDATE department SET phone = '042-629-9290, 042-630-9298, 042-630-9214' WHERE name = '간호학과';
UPDATE department SET phone = '042-630-4620'                             WHERE name = '물리치료학과';
UPDATE department SET phone = '042-630-9840'                             WHERE name = '스포츠건강재활학과';
UPDATE department SET phone = '042-630-9912'                             WHERE name = '동물의료관리학과';
UPDATE department SET phone = '042-630-9911, 042-630-9938'               WHERE name = '토탈펫케어학과';
UPDATE department SET phone = '042-630-9296'                             WHERE name = '보건복지자율전공';

-- 엔디컷국제대학(AI경영·AI빅데이터·글로벌호스피탈리티), 솔브릿지경영학부, 자유전공학부는
-- 학교 학과 안내에 대표 전화가 없어 NULL. 확인되면 여기에 추가할 것.

-- 채운 결과 확인
-- SELECT name, phone FROM department WHERE phone IS NOT NULL ORDER BY id;
