-- 학과 홈페이지 주소 추가
--
-- 학과소개 본문은 DB에 복사해두지 않는다. 학교가 교육과정을 개편하면 복사본만
-- 낡은 내용으로 남아 챗봇이 계속 틀린 답을 하기 때문. 소속 정보(단과대/학부/형제
-- 학과)는 DB로 답하고, 상세 소개는 아래 홈페이지 링크로 넘긴다.
-- (campus.py의 지도 카드가 카카오맵 링크를 주는 것과 동일한 방식)
--
-- server.py는 create_all만 호출해 기존 테이블에 컬럼을 추가하지 않으므로 수동 실행 필요.
--   docker exec -i <postgres컨테이너> psql -U <user> -d <db> < add_department_homepage.sql
--
-- 출처: 학교 학과 안내 페이지 (2026-07 기준)

ALTER TABLE department ADD COLUMN IF NOT EXISTS homepage_url VARCHAR;

-- ── 소프트웨어(SW)융합대학 ────────────────────────────────────────
UPDATE department SET homepage_url = 'https://cs.wsu.ac.kr/main/index.jsp'           WHERE name = '컴퓨터공학전공';
UPDATE department SET homepage_url = 'https://it.wsu.ac.kr/main/index.jsp'           WHERE name = '컴퓨터·소프트웨어전공';
UPDATE department SET homepage_url = 'https://sima.wsu.ac.kr/main/index.jsp'         WHERE name = '글로벌미디어영상학과';
UPDATE department SET homepage_url = 'https://design.wsu.ac.kr/main/index.jsp'       WHERE name = '미디어디자인·영상전공';
UPDATE department SET homepage_url = 'https://game.wsu.ac.kr/main/index.jsp'         WHERE name = '게임소프트웨어전공';
UPDATE department SET homepage_url = 'https://gamegraphics.wsu.ac.kr/main/index.jsp' WHERE name = '게임그래픽전공';

-- ── 엔디컷국제대학 ───────────────────────────────────────────────
UPDATE department SET homepage_url = 'https://tech.endicott.ac.kr/main/index.jsp'    WHERE name = 'AI·빅데이터학과';
UPDATE department SET homepage_url = 'https://aim.wsu.ac.kr/main/index.jsp'          WHERE name = 'AI경영학과';
UPDATE department SET homepage_url = 'https://sihom.wsu.ac.kr/main/index.jsp'        WHERE name = '글로벌호스피탈리티학과';

-- ── 솔브릿지국제경영대학 ──────────────────────────────────────────
-- 영문(www.solbridge.ac.kr)·입학 홈페이지도 있으나 학생 안내용이라 국문을 쓴다.
UPDATE department SET homepage_url = 'https://korean.solbridge.ac.kr/story/main/index.jsp' WHERE name = '솔브릿지경영학부';

-- ── 철도대학 ─────────────────────────────────────────────────────
UPDATE department SET homepage_url = 'https://sira.wsu.ac.kr/main/index.jsp'            WHERE name = '글로벌철도학과';
UPDATE department SET homepage_url = 'https://civil.wsu.ac.kr/main/index.jsp'           WHERE name = '철도건설시스템전공';
UPDATE department SET homepage_url = 'https://arch.wsu.ac.kr/main/index.jsp'            WHERE name = '건축공학전공';
UPDATE department SET homepage_url = 'https://biz.wsu.ac.kr/main/index.jsp'             WHERE name = '철도경영학과';
-- 학교 안내 페이지가 철도건설시스템전공과 같은 civil 주소를 적어둠 — 학교 쪽 오기 가능성 있음
UPDATE department SET homepage_url = 'https://civil.wsu.ac.kr/main/index.jsp'           WHERE name = '철도전기시스템전공';
UPDATE department SET homepage_url = 'https://railwaysoftware.wsu.ac.kr/main/index.jsp' WHERE name = '철도소프트웨어전공';
UPDATE department SET homepage_url = 'https://rail.wsu.ac.kr/main/index.jsp'            WHERE name = '철도차량시스템학과';
UPDATE department SET homepage_url = 'https://railfree.wsu.ac.kr/main/index.jsp'        WHERE name = '철도자율전공';

-- ── 외식조리대학 ─────────────────────────────────────────────────
UPDATE department SET homepage_url = 'https://sica.wsu.ac.kr/main/index.jsp'         WHERE name = '글로벌조리전공';
UPDATE department SET homepage_url = 'https://sicaipb.wsu.ac.kr/main/index.jsp'      WHERE name = 'Lyfe조리전공';
UPDATE department SET homepage_url = 'https://sires.wsu.ac.kr/main/index.jsp'        WHERE name = '글로벌외식,조리경영전공';
UPDATE department SET homepage_url = 'https://culinary.wsu.ac.kr/main/index.jsp'     WHERE name = '외식조리전공';
UPDATE department SET homepage_url = 'https://culinaryos.wsu.ac.kr/main/index.jsp'   WHERE name = '한식·조리과학전공';
UPDATE department SET homepage_url = 'https://foodservice2.wsu.ac.kr/main/index.jsp' WHERE name = '외식,조리경영전공';
UPDATE department SET homepage_url = 'https://bpc.wsu.ac.kr/main/index.jsp'          WHERE name = '제과제빵·조리전공';
UPDATE department SET homepage_url = 'https://csnn.wsu.ac.kr/main/index.jsp'         WHERE name = '외식조리영양학과';
UPDATE department SET homepage_url = 'https://tour.wsu.ac.kr/main/index.jsp'         WHERE name = '호텔관광경영학과';
UPDATE department SET homepage_url = 'https://chefcareer.wsu.ac.kr/main/index.jsp'   WHERE name = '외식조리자율전공';

-- ── 보건복지대학 ─────────────────────────────────────────────────
UPDATE department SET homepage_url = 'https://welfare.wsu.ac.kr/main/index.jsp'             WHERE name = '사회복지학과';
UPDATE department SET homepage_url = 'https://ot.wsu.ac.kr/main/index.jsp'                  WHERE name = '작업치료학과';
UPDATE department SET homepage_url = 'https://speech.wsu.ac.kr/main/index.jsp'              WHERE name = '언어치료·청각재활학과';
UPDATE department SET homepage_url = 'https://healthbiz.wsu.ac.kr/main/index.jsp'           WHERE name = '보건의료경영학과';
UPDATE department SET homepage_url = 'https://childedu.wsu.ac.kr/main/index.jsp'            WHERE name = '유아교육과';
UPDATE department SET homepage_url = 'https://beauty.wsu.ac.kr/main/index.jsp'              WHERE name = '뷰티디자인경영학과';
UPDATE department SET homepage_url = 'https://emergency.wsu.ac.kr/main/index.jsp'           WHERE name = '응급구조학과';
UPDATE department SET homepage_url = 'https://fire2.wsu.ac.kr/main/index.jsp'               WHERE name = '소방·안전학부';
UPDATE department SET homepage_url = 'https://nursing.wsu.ac.kr/main/index.jsp'             WHERE name = '간호학과';
UPDATE department SET homepage_url = 'https://pt.wsu.ac.kr/main/index.jsp'                  WHERE name = '물리치료학과';
UPDATE department SET homepage_url = 'https://at.wsu.ac.kr/main/index.jsp'                  WHERE name = '스포츠건강재활학과';
UPDATE department SET homepage_url = 'https://animal.wsu.ac.kr/main/index.jsp'              WHERE name = '동물의료관리학과';
UPDATE department SET homepage_url = 'https://petcare.wsu.ac.kr/main/index.jsp'             WHERE name = '토탈펫케어학과';
UPDATE department SET homepage_url = 'https://nexthealth-welfare.wsu.ac.kr/main/index.jsp'  WHERE name = '보건복지자율전공';

-- ── 단과대학 직속 ────────────────────────────────────────────────
UPDATE department SET homepage_url = 'https://global.wsu.ac.kr/page/index.jsp?code=global010101' WHERE name = '자유전공학부';

-- 채운 결과 확인 (43/43이어야 함)
-- SELECT count(*) FILTER (WHERE homepage_url IS NOT NULL), count(*) FROM department;
