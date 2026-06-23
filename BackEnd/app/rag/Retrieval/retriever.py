from app.rag.Embedding import BaaiEmbedding
from app.rag.Retrieval.qdrant_store import (
    QdrantVectorStore,
    SearchResult,
)
from app.rag.Retrieval.Reranker import BgeReranker

# reranker score 임계값 - 이 값 이상인 청크는 전부 반환
SCORE_THRESHOLD = 0.04
# 최대 반환 청크 수 - LLM 컨텍스트 초과 방지
MAX_CHUNKS = 10

# 같은 source URL의 청크를 합칠 때 최대 글자 수
# (너무 길면 LLM 컨텍스트 초과 에러 발생 및 리랭커 점수 폭락 → 1200자로 제한)
MAX_MERGED_LENGTH = 4000


class Retriever:
    """Embed a question and retrieve relevant chunks from Qdrant."""

    def __init__(
        self,
        embedding: BaaiEmbedding | None = None,
        vector_store: QdrantVectorStore | None = None,
    ) -> None:
        self.embedding = embedding or BaaiEmbedding()
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
    ) -> list[SearchResult]:

        question = question.strip()
        if not question:
            return []

        query_embedding = self.embedding.embed_text(question)

        # 1. 넉넉하게 후보 가져오기 (Vector Search)
        results = self.vector_store.search(
            query_embedding=query_embedding,
            limit=30,
            source=source,
            topic=topic,
        )

        if not results:
            return []

        # 2. ★ 중요: 합치기 "전"에 리랭킹을 수행 (짧은 원본 청크 기준으로 평가)
        raw_texts = [result.text for result in results]
        scores = self.reranker.rerank(question, raw_texts)

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
            label = f"{article}" if article else f"source={src[:40]}"
            passed = "✅" if result.score >= SCORE_THRESHOLD else "❌"
            print(f"  [{i}] {passed} score={result.score:.3f} length={length}자 | {label}")

        # 3. SCORE_THRESHOLD로 필터링 (관련 있는 청크만 살리기)
        filtered_results = [r for r in reranked_results if r.score >= SCORE_THRESHOLD]
        
        # 임계값 이상인 게 하나도 없으면 가장 높은 것 1개는 살림
        if not filtered_results and reranked_results:
            filtered_results = [reranked_results[0]]
            print(f"[Retriever] 임계값 통과 청크 없음 → 최소 1개 강제 반환 (score={filtered_results[0].score:.3f})")

        # LLM 컨텍스트 보호를 위해 최대 반환 개수 제한
        filtered_results = filtered_results[:MAX_CHUNKS]

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