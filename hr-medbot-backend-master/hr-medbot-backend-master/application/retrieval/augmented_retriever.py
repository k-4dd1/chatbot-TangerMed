from collections import defaultdict
from math import inf
from sqlalchemy import select, and_, func
from sqlalchemy.orm import joinedload
from database import models, session_scope
from llm_client import Embedder, Reranker
from typing import List, Dict, Any


class AugmentedRetriever:
    def __init__(self,
                 limit: int = 5,
                 prefetch_limit: int = 10,
                 *,
                 access_control_fields: dict | None = None,
                 alpha: float = 0.5,
                 summary_limit: int = 10,
                 small_chunk_limit: int = 50):
        self.limit = limit
        self.prefetch_limit = prefetch_limit
        self.alpha = alpha
        self.summary_limit = summary_limit
        self.small_chunk_limit = small_chunk_limit
        self.embedder = Embedder()
        self.reranker = Reranker()
        self.access_control_fields = access_control_fields
        self.access_filters = self._build_access_control_filters()
    
    def __call__(self, query: str) -> List[Dict[str, Any]]:
        return self.retrieve(query)

    def retrieve(self, query: str) -> List[Dict[str, Any]]:
        query_embedding = self.embedder(query)
        with session_scope() as session:
            summary_scores = self._get_submodel_similarity(session, models.BigChunkSummary, self.summary_limit, query_embedding)
            small_chunk_scores = self._get_submodel_similarity(session, models.SmallChunk, self.small_chunk_limit, query_embedding)            
            big_chunk_scores = self._merge_scores(summary_scores, small_chunk_scores)
            top_big_chunks = self._get_top_big_chunks(session, big_chunk_scores)
            reranked_chunks, rerank_scores = self._rerank_chunks_with_scores(query, top_big_chunks)
            results = []
            for i, chunk in enumerate(reranked_chunks[:self.limit]):
                chunk_id = chunk.id
                summary_score = summary_scores.get(chunk_id, 0.0)
                small_chunk_score = small_chunk_scores.get(chunk_id, 0.0)
                combined_score = big_chunk_scores.get(chunk_id, 0.0)
                rerank_score = rerank_scores[i] if i < len(rerank_scores) else 0.0
                results.append({
                    'chunk': chunk,
                    'summary_score': summary_score,
                    'small_chunk_score': small_chunk_score,
                    'combined_score': combined_score,
                    'rerank_score': rerank_score
                })
            return results

    def _merge_scores(self, summary_scores, small_chunk_scores) -> Dict[str, float]:
        combined_scores = defaultdict(float)
        for big_chunk_id, score in small_chunk_scores.items():
            combined_scores[big_chunk_id] += self.alpha * score
        for big_chunk_id, score in summary_scores.items():
            combined_scores[big_chunk_id] += (1 - self.alpha) * score
        
        return dict(combined_scores)
    
    def _build_access_control_filters(self) -> List:
        filters = []
        if not self.access_control_fields:
            return filters
        for ac_k, ac_v in self.access_control_fields.items():
            assert isinstance(ac_v, list), "Only lists accepted as values in access control"
            col = getattr(models.File, ac_k)
            filters.append(col.op("&&")(ac_v))
        return filters

    def _get_submodel_similarity(self, session, db_model, fetch_limit, query_embedding):
        base_distance = db_model.embedding.cosine_distance(query_embedding)
        query = (
            select(db_model.big_chunk_id, base_distance.label('distance'))
            .join(models.BigChunk, models.BigChunk.id == db_model.big_chunk_id)
            .join(models.File, models.File.id == models.BigChunk.file_id)
            .where(models.File.status == models.FileStatus.OK)
        )
        if self.access_filters:
            query = query.where(and_(*self.access_filters))
        query = query.order_by(base_distance).limit(fetch_limit)
        results = session.execute(query).fetchall()
        scores = defaultdict(lambda: float('-inf'))
        for row in results:
            scores[row.big_chunk_id] = 1 - row.distance # dist to similarity
        return scores

    def _get_top_big_chunks(self, session, big_chunk_scores: Dict[str, float] ) -> List[models.BigChunk]:
        """Get the top big chunks by combined similarity score."""
        if not big_chunk_scores:
            return []
        sorted_chunks = sorted(big_chunk_scores.items(), key=lambda x: x[1], reverse=True)
        top_chunk_ids = [chunk_id for chunk_id, _ in sorted_chunks[:self.prefetch_limit]]
        query = select(models.BigChunk).where(
            models.BigChunk.id.in_(top_chunk_ids)
        ).options(joinedload(models.BigChunk.file))
        big_chunks = session.execute(query).scalars().all()
        chunk_dict = {chunk.id: chunk for chunk in big_chunks}
        return [chunk_dict[chunk_id] for chunk_id in top_chunk_ids if chunk_id in chunk_dict]

    def _rerank_chunks_with_scores(self, query: str, big_chunks: List[models.BigChunk]) -> tuple[List[models.BigChunk], List[float]]:
        """Rerank big chunks using the reranker and return both chunks and scores."""
        if not big_chunks:
            return [], []
        candidates = [chunk.text for chunk in big_chunks]
        rerank_scores = self.reranker.rerank(query, candidates)
        chunk_score_pairs = list(zip(big_chunks, [score for _, score in rerank_scores]))
        chunk_score_pairs.sort(key=lambda x: x[1], reverse=True)
        reranked_chunks = [chunk for chunk, _ in chunk_score_pairs]
        scores = [score for _, score in chunk_score_pairs]
        return reranked_chunks, scores



if __name__ == "__main__":
    # Initialize retriever
    retriever = AugmentedRetriever(
        limit=5,
        prefetch_limit=25,
        alpha=0.6,
        access_control_fields={}
    )
    import time
    # Simple interactive loop
    while True:
        query = input("Enter query (or 'quit'): ").strip()
        
        if query.lower() in ['quit', 'exit', 'q']:
            break
            
        if not query:
            continue
            
        try:
            start = time.time()
            results = retriever.retrieve(query)
            end = time.time()
            elapsed_ms = (end - start) * 1000
            print(f"Found {len(results)} results in {elapsed_ms:.2f}ms:")
            for i, result in enumerate(results, 1):
                chunk = result['chunk']
                print(f"{i}. {chunk.file.title}")
                print(f"   {chunk.text[:100]}...")
                print(f"   Summary Score: {result['summary_score']:.4f}")
                print(f"   Small Chunk Score: {result['small_chunk_score']:.4f}")
                print(f"   Combined Score: {result['combined_score']:.4f}")
                print(f"   Rerank Score: {result.get("rerank_score", 0):.4f}")
                print()
                
        except Exception as e:
            print(f"Error: {e}")
