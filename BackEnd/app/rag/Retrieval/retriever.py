import re

from app.core.config import settings
from app.rag.Embedding import BaaiEmbedding, baai_embedding
from app.rag.Retrieval.qdrant_store import (
    QdrantVectorStore,
    SearchResult,
)
from app.rag.Retrieval.Reranker import BgeReranker

# reranker score 임계값 - Sigmoid 적용, 절대평가 0~1 (0.4 이상을 유의미한 문서로 판단)
SCORE_THRESHOLD = 0.4
# 최대 반환 청크 수(합치기 '후' 기준) - LLM 컨텍스트 초과 방지
MAX_CHUNKS = 5
# 합치기 '전' 상한 — 같은 문서 청크는 아래에서 1개로 합쳐지므로 넉넉히 잡는다.
# (MAX_CHUNKS로 합치기 전에 자르면 문서 보강분이 도로 잘려나감)
MAX_PRE_MERGE = 12
# 같은 문서 보강 시 추가로 끌어올 최대 청크 수 (긴 규정 문서가 통째로 유입되는 것 방지)
SAME_DOC_MAX = 6

# 같은 source URL의 청크를 합칠 때 최대 글자 수
# (너무 길면 LLM 컨텍스트 초과 에러 발생 및 리랭커 점수 폭락 → 2000자로 제한)
MAX_MERGED_LENGTH = 2000

# 최종 컨텍스트 '전체' 글자 수 상한.
# 문서당 상한(2000)만 있으면 문서 5개일 때 최대 1만 자가 되어 로컬 모델 n_ctx(4096 토큰)를 넘긴다.
#
# 실측으로 확정한 환산비: Bllossom 토크나이저에서 한글은 대략 **1자 ≈ 1토큰**이다.
# (컨텍스트 3123자→프롬프트 3407토큰 / 3511자→3666 / 3757자→3801 / 3969자→4106.
#  프롬프트 토큰 ≈ 컨텍스트 글자 수 + 150 내외)
# 예전 주석의 '1.5자/토큰' 가정 때문에 4000자로 잡혀 있었는데, 그러면 컨텍스트만으로
# n_ctx를 거의 다 먹어 답변이 늘 잘렸고, 학사일정 보강이 얹히자 프롬프트가 4120토큰이 되어
# "Requested tokens exceed context window" 예외로 요청 자체가 실패했다.
# → 답변 생성 몫으로 700~800토큰을 남기도록 3200자로 낮춘다.
MAX_TOTAL_CONTEXT = 3200


def _rerank_text(result: SearchResult) -> str:
    """리랭킹에 넣을 텍스트 — 본문 앞에 '문서명 + 조문(제목)'을 한 줄 붙인다.

    청킹 과정에서 제목이 다른 청크로 떨어져 나가면(예: 공결 세부지침의 별표1 제목이
    부칙 청크에 갇히고 표·절차 청크는 제목 없이 남음) 본문만으로는 무슨 주제인지 알 수
    없어 리랭커 점수가 0에 수렴한다. 실측상 제목 한 줄을 붙이면 5~7배 상승했다.
    (저장·임베딩 텍스트는 그대로 두고 리랭킹 입력에만 사용한다)"""
    src = (result.metadata.get("source") or "").replace("_", " ").strip()
    article = (result.metadata.get("article") or "").strip()
    head = " ".join(x for x in (src, article) if x)
    return f"{head}\n{result.text}" if head else result.text


# 출처명 매칭 폴백에서 질문의 '내용어'만 남기려고 걷어낼 일반어(서비스·절차·의문어).
# 이게 남으면 '시간'이 '시간표' 문서에 우연히 걸리는 식의 오탐이 생긴다.
_SRC_MATCH_STOPWORDS = (
    "이용시간", "운영시간", "이용", "운영", "시간", "방법", "이용법", "대여", "대관", "예약",
    "신청", "정보", "안내", "문의", "사용", "위치", "어디", "어딨", "언제", "얼마", "어떻게",
    "알려줘", "알려", "뭐야", "뭔가요", "있나요", "있어", "요금", "가격", "비용",
)
_SRC_TOKEN_RE = re.compile(r"[가-힣A-Za-z0-9]+")
_SRC_NORM_RE = re.compile(r"[\s()（）\[\]·・/,_-]")


def _norm_src(s: str) -> str:
    return _SRC_NORM_RE.sub("", s or "").lower()


def _source_match_terms(*queries: str) -> list[str]:
    """질문에서 일반어를 걷어낸 '내용어'(길이 2+) 목록 — 문서 출처명과 대조할 씨앗."""
    terms: list[str] = []
    for q in queries:
        if not q:
            continue
        s = q
        for w in _SRC_MATCH_STOPWORDS:
            s = s.replace(w, " ")
        for t in _SRC_TOKEN_RE.findall(s):
            if len(t) >= 2 and t not in terms:
                terms.append(t)
    return terms


def _source_hit(source: str, text: str, terms: list[str]) -> bool:
    """출처명 또는 청크 본문(괄호·공백 제거)에 질문 내용어가 들어 있는지 — 리랭커가 0점 줘도
    관련 신호. 본문까지 보는 이유: '헬스시설'이 출처명('우송스포츠센터')엔 없고 본문
    ('헬스 시설 이용안내')에만 있는 경우까지 살리기 위함(실측)."""
    if not terms:
        return False
    hay = _norm_src(source) + _norm_src(text)
    return any(_norm_src(t) in hay for t in terms if len(_norm_src(t)) >= 2)


class Retriever:
    """Embed a question and retrieve relevant chunks from Qdrant."""

    def __init__(
        self,
        embedding: BaaiEmbedding | None = None,
        vector_store: QdrantVectorStore | None = None,
    ) -> None:
        self.embedding = embedding or baai_embedding   # 전역 싱글턴 공유 (모델 1회 로드)
        self.vector_store = vector_store or QdrantVectorStore()
        self.reranker = BgeReranker()

    def _merge_same_article(self, results: list[SearchResult]) -> list[SearchResult]:
        """
        같은 article(조문) 또는 같은 source URL의 청크를 합쳐서 반환.

        - [조문 문서] article이 있으면 source::article 키로 합침
        - [일반 문서] article=None인 청크는 source URL 키로 합침
        - 합친 후 score는 그룹 내 가장 높은 값 유지
        - 합친 텍스트가 MAX_MERGED_LENGTH를 넘으면 거기서 중단 (LLM 컨텍스트 보호)
        """
        article_merged: dict[str, SearchResult] = {}
        source_merged: dict[str, SearchResult] = {}

        for result in results:
            article = result.metadata.get("article")
            source = result.metadata.get("source", "")

            if article:
                # 조문 단위 합치기
                key = f"{source}::{article}"
                if key in article_merged:
                    existing = article_merged[key]
                    
                    # MAX_MERGED_LENGTH 초과 시 텍스트는 놔두고 점수만 갱신
                    if len(existing.text) >= MAX_MERGED_LENGTH:
                        existing.score = max(existing.score, result.score)
                        continue
                        
                    new_text = result.text.replace(f"{article} (계속)\n", "").strip()
                    merged_text = existing.text + "\n" + new_text
                    article_merged[key] = SearchResult(
                        text=merged_text,
                        score=max(existing.score, result.score),
                        metadata=existing.metadata,
                    )
                else:
                    article_merged[key] = result
            else:
                # 일반 문서 source 단위 합치기
                key = source
                if key in source_merged:
                    existing = source_merged[key]

                    # MAX_MERGED_LENGTH 초과 시 더 이상 텍스트를 붙이지 않음
                    if len(existing.text) >= MAX_MERGED_LENGTH:
                        existing.score = max(existing.score, result.score)
                        continue

                    merged_text = existing.text + "\n\n" + result.text
                    source_merged[key] = SearchResult(
                        text=merged_text,
                        score=max(existing.score, result.score),
                        metadata=existing.metadata,
                    )
                else:
                    source_merged[key] = result

        all_results = list(article_merged.values()) + list(source_merged.values())
        
        # 최종 반환 시 관련도 점수가 가장 높은 순으로 정렬하여 반환
        return sorted(all_results, key=lambda r: r.score, reverse=True)

    def search(
        self,
        question: str,
        limit: int | None = None,
        source: str | None = None,
        topic: str | None = None,
        original_question: str | None = None,
    ) -> list[SearchResult]:

        question = question.strip()
        if not question:
            return []

        # 하이브리드면 dense+sparse 함께, 아니면 기존 dense 단독
        sparse_query = None
        if settings.HYBRID_SEARCH:
            dense_list, sparse_list = self.embedding.embed_hybrid([question])
            query_embedding = dense_list[0]
            sparse_query = sparse_list[0]
        else:
            query_embedding = self.embedding.embed_text(question)

        # 1. 넉넉하게 후보 가져오기 (Vector Search / 하이브리드 융합)
        results = self.vector_store.search(
            query_embedding=query_embedding,
            limit=30,
            source=source,
            topic=topic,
            sparse_query=sparse_query,
        )

        if not results:
            return []

        # 2. ★ 중요: 합치기 "전"에 리랭킹을 수행 (원본 청크 기준 평가)
        # 리랭킹 입력에는 '문서명 + 조문' 한 줄을 앞에 붙인다(_rerank_text).
        # 순수 본문만 주면, 제목이 다른 청크로 분리된 문서에서 주제어가 사라져 점수가
        # 0에 수렴한다(공결 세부지침 실측: 0.007 → 제목 부여 시 0.039).
        # 리랭킹 쿼리: 재작성 검색어(question)와 원본 질문(original_question) 둘 다로 채점해
        # 청크별 max를 취한다. 원본이 "공결신청하고싶은데 파일도 같이 줄래?"처럼 노이즈/복합
        # 요청이면 리랭커 점수가 폭락(정답 문서 0.126)하지만, 깔끔한 재작성 키워드로는 0.9+로
        # 살아난다(실측). max라 원본만 쓰던 기존 대비 점수가 내려갈 일이 없어 회귀 위험이 없다.
        rerank_texts = [_rerank_text(result) for result in results]
        rerank_queries = [question]
        if original_question and original_question.strip() and original_question != question:
            rerank_queries.append(original_question)

        score_lists = [self.reranker.rerank(q, rerank_texts) for q in rerank_queries]
        scores = [max(col) for col in zip(*score_lists)]

        # 리랭커 점수가 반영된 새로운 결과 리스트 생성
        reranked_results = [
            SearchResult(text=r.text, score=s, metadata=r.metadata)
            for r, s in zip(results, scores)
        ]

        # 점수 순으로 내림차순 정렬
        reranked_results.sort(key=lambda x: x.score, reverse=True)

        # 디버그: rerank 점수 전체 출력
        print("[Retriever] rerank 점수 목록:")
        for i, result in enumerate(reranked_results, start=1):
            src = result.metadata.get("source", "unknown")
            article = result.metadata.get("article", "")
            length = len(result.text)
            chunk_index = result.metadata.get("chunk_index", "?")
            label = f"{article}" if article else f"source={src[:40]}"
            passed = "✅" if result.score >= SCORE_THRESHOLD else "❌"
            print(
                f"  [{i}] {passed} score={result.score:.3f} "
                f"length={length}자 | idx={chunk_index} | {label}"
            )

        # 3. SCORE_THRESHOLD로 필터링 (관련 있는 청크만 살리기)
        filtered_results = [r for r in reranked_results if r.score >= SCORE_THRESHOLD]
        
        # 임계값 통과가 적으면 상위 청크로 보강 (커버리지 확보 — 기한 등 흩어진 정보 누락 방지)
        MIN_FALLBACK = 5
        FALLBACK_MIN_SCORE = 0.15

        # 청크 동일성은 (source, chunk_index)로 판정한다.
        # 벡터 결과와 리랭크 결과는 값이 다른 별개 객체라 객체 비교(in)로는 중복 제거가 안 된다.
        def _key(r):
            return (r.metadata.get("source"), r.metadata.get("chunk_index"))

        seen = {_key(r) for r in filtered_results}
        rr_by_key = {_key(r): r for r in reranked_results}   # 벡터순으로 채울 때도 리랭크 점수 유지

        # 리랭커가 '확신한'(임계값 통과) 청크가 하나라도 있는지 — 아래 벡터 보강의 발동 조건.
        # 전부 미달이면 해당 주제 문서가 코퍼스에 아예 없는 경우가 대부분이라(장학금·주차 등),
        # 억지로 채우면 무관 문서가 LLM에 들어가 환각을 유발한다 → 채우지 않고 '못 찾음'으로 둔다.
        has_confident = bool(filtered_results)

        if len(filtered_results) < MIN_FALLBACK and reranked_results:
            passed = len(filtered_results)

            # (1) 리랭크 상위로 보강
            for r in reranked_results[:MIN_FALLBACK]:
                if len(filtered_results) >= MIN_FALLBACK:
                    break
                if r.score >= FALLBACK_MIN_SCORE and _key(r) not in seen:
                    filtered_results.append(r); seen.add(_key(r))

            # (2) 그래도 부족하면 '벡터 검색 순위'로 채운다.
            #     ko-reranker가 문서의 제목/개요 청크만 상위로 올리고 정작 답이 있는 섹션을
            #     0.0x로 깔아뭉개는 사례가 있는데(기숙사 간사 신청: 정답 청크 0.064),
            #     그때 임베딩 순위는 정확했다(같은 청크가 벡터 6위).
            if has_confident and len(filtered_results) < MIN_FALLBACK:
                for r in results:                       # results = 벡터 검색 원래 순서
                    if len(filtered_results) >= MIN_FALLBACK:
                        break
                    k = _key(r)
                    if k not in seen:
                        filtered_results.append(rr_by_key.get(k, r)); seen.add(k)
                print("[Retriever] 리랭커 보강 부족 → 벡터 순위로 채움")

            print(f"[Retriever] 임계값 통과 {passed}개 → {len(filtered_results)}개로 보강 (top score={reranked_results[0].score:.3f})")

        # 3-1b. 출처명·본문 매칭 최후 폴백 — 위까지 전부 실패(0개)했지만 질문의 '내용어'가 어떤
        # 문서의 출처명이나 본문과 겹치면 그 문서는 실제로 관련 있다('체육관 대여방법'↔'실내체육관
        # (스포츠센터)', '헬스시설'↔본문 '헬스 시설 이용안내'). 리랭커 브리틀함으로 0점 맞은 경우라
        # 그 출처 청크를 벡터 순위로 살려 '못 찾음' 오답을 막는다. 코퍼스에 그 말이 아예 없으면
        # 매칭되지 않아 발동 안 하므로 환각 방지(has_confident 취지)는 유지.
        if not filtered_results and reranked_results:
            terms = _source_match_terms(question, original_question)
            matched_src = {r.metadata.get("source") for r in reranked_results
                           if _source_hit(r.metadata.get("source"), r.text, terms)}
            if matched_src:
                for r in results:                       # results = 벡터 검색 원래 순서
                    if len(filtered_results) >= MIN_FALLBACK:
                        break
                    if r.metadata.get("source") in matched_src and _key(r) not in seen:
                        filtered_results.append(rr_by_key.get(_key(r), r)); seen.add(_key(r))
                if filtered_results:
                    print(f"[Retriever] 출처명 매칭 폴백 → {matched_src} ({len(filtered_results)}개 살림)")

        # 3-2. 같은 문서 보강 — 1등이 확신 있는 문서면 그 문서의 나머지 청크도 후보에서 끌어온다.
        # 리랭커가 공고의 '개요'만 올리고 '신청 방법' 섹션을 떨어뜨리는 경우를 복원하기 위함.
        # (같은 source는 아래 _merge_same_article에서 chunk_index 순으로 하나로 합쳐진다)
        if filtered_results:
            top = max(filtered_results, key=lambda r: r.score)
            top_src = top.metadata.get("source")
            if top_src and top.score >= SCORE_THRESHOLD:
                siblings = [r for r in reranked_results
                            if r.metadata.get("source") == top_src and _key(r) not in seen]
                # 상한을 넘으면 '문서 앞쪽'이 아니라 '관련도 높은 순'으로 고른다.
                # (위치순이면 뒤쪽에 있는 정답 섹션이 잘려나감)
                siblings.sort(key=lambda r: r.score, reverse=True)
                picked = siblings[:SAME_DOC_MAX]
                # 고른 뒤에는 문서 원래 순서로 되돌려야 합칠 때 문맥이 이어진다.
                picked.sort(key=lambda r: r.metadata.get("chunk_index", 0))
                for r in picked:
                    filtered_results.append(r); seen.add(_key(r))
                if picked:
                    print(f"[Retriever] 같은 문서 보강: '{top_src}' +{len(picked)}개 (관련도순 선별)")

        # 합치기 '전' 상한 (같은 문서 청크는 합쳐져 1개가 되므로 MAX_CHUNKS보다 넉넉히)
        filtered_results = filtered_results[:MAX_PRE_MERGE]

        # ★ 디버그: threshold 통과 후 살아남은 청크의 chunk_index만 따로 출력
        survived_indices = [r.metadata.get("chunk_index", "?") for r in filtered_results]
        print(f"[Retriever] 임계값 통과 chunk_index 목록: {survived_indices}")

        # 4. 살아남은 청크들을 문서의 원래 순서(chunk_index)대로 오름차순 정렬
        # (순서대로 정렬해야 합쳤을 때 동아리나 규정 목록이 뒤죽박죽 섞이지 않음)
        filtered_results.sort(key=lambda r: r.metadata.get("chunk_index", 0))

        # 5. 합치기 실행 (이어지는 문맥 복원)
        final_results = self._merge_same_article(filtered_results)

        # 합친 '후' 최종 개수 제한 — 문서 단위로 MAX_CHUNKS개
        final_results = final_results[:MAX_CHUNKS]

        # 전체 길이 예산 — 점수 높은 문서부터 담고 예산을 넘으면 이후 문서는 버린다.
        # (문서를 중간에 자르면 답이 잘릴 수 있어 문서 단위로 통째 제외. 최상위 1개는 항상 유지)
        if final_results:
            budget, kept = MAX_TOTAL_CONTEXT, []
            for r in final_results:                     # _merge_same_article가 score 내림차순 반환
                if kept and len(r.text) > budget:
                    continue
                kept.append(r)
                budget -= len(r.text)
            if len(kept) < len(final_results):
                print(f"[Retriever] 컨텍스트 예산 초과 → {len(final_results)}개 중 {len(kept)}개 유지 "
                      f"(총 {sum(len(r.text) for r in kept)}자 / 상한 {MAX_TOTAL_CONTEXT})")
            final_results = kept

        # 명시적으로 limit이 들어온 경우 처리
        if limit is not None:
            final_results = final_results[:limit]

        print(
            f"[Retriever] 검색 {len(results)}개 → "
            f"필터링 후 {len(filtered_results)}개 → "
            f"최종 합치기 후 {len(final_results)}개"
        )

        return final_results

    def search_context(
        self,
        question: str,
        limit: int | None = None,
        source: str | None = None,
        topic: str | None = None,
    ) -> str:

        results = self.search(
            question=question,
            limit=limit,
            source=source,
            topic=topic,
        )

        return "\n\n".join(
            f"[source={self._format_source(result)}, score={result.score:.3f}]\n{result.text}"
            for result in results
            if result.text
        )

    def _format_source(self, result: SearchResult) -> str:
        return (
            result.metadata.get("source")
            or result.metadata.get("file_name")
            or "unknown"
        )