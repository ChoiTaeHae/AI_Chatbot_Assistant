from app.rag.Embedding import BaaiEmbedding
from app.rag.Retrieval.qdrant_store import (
    QdrantVectorStore,
    SearchResult,
)
from app.rag.Retrieval.Reranker import BgeReranker

# reranker score 임계값 - 이 값 이상인 청크는 전부 반환
SCORE_THRESHOLD = 0.3
# 최대 반환 청크 수 - LLM 컨텍스트 초과 방지
MAX_CHUNKS = 10


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
        같은 article(조문)의 청크를 합쳐서 반환
        - 제29조가 3개 청크로 나뉘어 있으면 하나로 합침
        - article이 없는 청크(문단 단위)는 그대로 유지
        - 합친 후 score는 가장 높은 값 유지
        """
        merged: dict[str, SearchResult] = {}
        no_article: list[SearchResult] = []

        for result in results:
            article = result.metadata.get("article")
            source = result.metadata.get("source", "")

            # article 없는 청크(문단 단위)는 합치지 않고 별도 보관
            if not article:
                no_article.append(result)
                continue

            key = f"{source}::{article}"

            if key in merged:
                existing = merged[key]
                # "(계속)" 표시 제거 후 본문만 추출
                new_text = result.text.replace(f"{article} (계속)\n", "").strip()
                merged[key] = SearchResult(
                    text=existing.text + "\n" + new_text,
                    score=max(existing.score, result.score),
                    metadata=existing.metadata,
                )
            else:
                merged[key] = result

        all_results = list(merged.values()) + no_article
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

        # 넉넉하게 후보 가져오기 (합치기 + score 필터링 후 충분한 결과 보장)
        results = self.vector_store.search(
            query_embedding=query_embedding,
            limit=30,
            source=source,
            topic=topic,
        )

        if not results:
            return []

        # 같은 조문 청크 합치기
        merged_results = self._merge_same_article(results)

        # reranker로 질문과의 관련도 점수 계산
        scores = self.reranker.rerank(
            question,
            [result.text for result in merged_results],
        )

        reranked = sorted(
            zip(merged_results, scores),
            key=lambda x: x[1],
            reverse=True,
        )

        # limit이 명시적으로 지정된 경우 → TOP K 방식
        if limit is not None:
            final_results = [result for result, _ in reranked[:limit]]
        else:
            # limit 미지정 → score 임계값 이상인 청크 전부 반환 (최대 MAX_CHUNKS개)
            final_results = [
                result for result, score in reranked
                if score >= SCORE_THRESHOLD
            ][:MAX_CHUNKS]

            # 임계값 이상인 게 하나도 없으면 최소 1개는 반환
            if not final_results and reranked:
                final_results = [reranked[0][0]]

        print(f"[Retriever] 검색 {len(results)}개 → 합치기 후 {len(merged_results)}개 → 최종 {len(final_results)}개")

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