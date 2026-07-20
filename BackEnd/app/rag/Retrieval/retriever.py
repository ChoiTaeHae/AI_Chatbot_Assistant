from app.core.config import settings
from app.rag.Embedding import BaaiEmbedding, baai_embedding
from app.rag.Retrieval.qdrant_store import (
    QdrantVectorStore,
    SearchResult,
)
from app.rag.Retrieval.Reranker import BgeReranker

# reranker score 임계값 - Sigmoid 적용, 절대평가 0~1 (0.4 이상을 유의미한 문서로 판단)
SCORE_THRESHOLD = 0.4
# 최대 반환 청크 수 - LLM 컨텍스트 초과 방지
MAX_CHUNKS = 5

# 같은 source URL의 청크를 합칠 때 최대 글자 수
# (너무 길면 LLM 컨텍스트 초과 에러 발생 및 리랭커 점수 폭락 → 2000자로 제한)
MAX_MERGED_LENGTH = 2000


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
        # BGE reranker는 순수 (질문, 본문) 쌍으로 학습됨 — 메타데이터 헤더 없이 본문만 전달
        # 리랭킹 쿼리: 재작성 검색어(question)와 원본 질문(original_question) 둘 다로 채점해
        # 청크별 max를 취한다. 원본이 "공결신청하고싶은데 파일도 같이 줄래?"처럼 노이즈/복합
        # 요청이면 리랭커 점수가 폭락(정답 문서 0.126)하지만, 깔끔한 재작성 키워드로는 0.9+로
        # 살아난다(실측). max라 원본만 쓰던 기존 대비 점수가 내려갈 일이 없어 회귀 위험이 없다.
        rerank_texts = [result.text for result in results]
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
        # 무관한 조각(0.00x)이 컨텍스트를 낭비하는 것 방지. 전부 미달이면 빈 컨텍스트로
        # 반환되어 rag_general의 "자료 못 찾음" 가드로 빠진다.
        MIN_FALLBACK = 5

        FALLBACK_MIN_SCORE = 0.15

        if len(filtered_results) < MIN_FALLBACK and reranked_results:
            fallback = [r for r in reranked_results[:MIN_FALLBACK] if r.score >= FALLBACK_MIN_SCORE]
            added = [r for r in fallback if r not in filtered_results]
            filtered_results = filtered_results + added
            print(f"[Retriever] 임계값 통과 {len(filtered_results) - len(added)}개 → 상위 {MIN_FALLBACK}개로 보강 (top score={reranked_results[0].score:.3f})")

        # LLM 컨텍스트 보호를 위해 최대 반환 개수 제한
        filtered_results = filtered_results[:MAX_CHUNKS]

        # ★ 디버그: threshold 통과 후 살아남은 청크의 chunk_index만 따로 출력
        survived_indices = [r.metadata.get("chunk_index", "?") for r in filtered_results]
        print(f"[Retriever] 임계값 통과 chunk_index 목록: {survived_indices}")

        # 4. 살아남은 청크들을 문서의 원래 순서(chunk_index)대로 오름차순 정렬
        # (순서대로 정렬해야 합쳤을 때 동아리나 규정 목록이 뒤죽박죽 섞이지 않음)
        filtered_results.sort(key=lambda r: r.metadata.get("chunk_index", 0))

        # 5. 합치기 실행 (이어지는 문맥 복원)
        final_results = self._merge_same_article(filtered_results)

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