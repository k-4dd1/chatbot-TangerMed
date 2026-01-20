from llm_client import Generator, Embedder
from .chunkers import GoldenChunker
from typing import List, Any
from database import models, session_scope

DEFAULT_SUMMARIZATION_SYSPROMPT =  (
"You are a helpful assistant. Summarize the following text in the same language, "
"in at most 3 concise sentences. Respond with the summary only—no intro, no headings, "
"no other commentary."
)


class NeoInserter:

    def __init__(
        self,
        *,
        bc_size = 5000,
        bc_max_size = 7000,
        bc_min_size = 3000,
        #------
        sc_size = 512,
        sc_max_size = 1024,
        sc_min_size = 256,
        #-----
        batch_size = 128,
        enable_summaries: bool = True
    ):
        self.enable_summaries = enable_summaries
        self.generator = Generator()
        self.embedder = Embedder()
        self.big_chunker = GoldenChunker(
            chunk_size = bc_size,
            max_size = bc_max_size,
            min_size = bc_min_size
        )
        self.small_chunker = GoldenChunker(
            chunk_size = sc_size,
            max_size = sc_max_size,
            min_size = sc_min_size
        )
        self.batch_size = max(1, batch_size)

    
    def _generate_summary(self, text: str) -> str:
        """Generate a concise summary for *text* using the configured LLM."""
        response = self.generator(
            messages=[
                {
                    "role": "system",
                    "content": DEFAULT_SUMMARIZATION_SYSPROMPT,
                },
                {"role": "user", "content": text},
            ],
            stream=False,
        )
        return response
    
    def _embed_in_batches(self, payload: List[str]) -> List[List[float]]:
        """Embed *payload* in deterministic order while respecting *batch_size*.
        """
        if not payload:
            return []
        result: List[List[float]] = []
        for start in range(0, len(payload), self.batch_size):
            batch = payload[start : start + self.batch_size]
            embeds = self.embedder(batch)
            result.extend(embeds)
        return result

    def insert(self, title:str, text:str, **file_kwargs):
        # ---- FILE CREATION ----
        with session_scope(write_enabled=True) as bootstrap:
            file_obj = models.File(
            title=title,
            **{k: v for k, v in file_kwargs.items() if hasattr(models.File, k)}
        )
            bootstrap.add(file_obj)
            bootstrap.flush()  # populate primary key
            inserted_file_id = file_obj.id
        try:
            # ----------------------------------------------------------------
            # 2) Continue with heavy processing (chunking, embedding, etc.)
            # ----------------------------------------------------------------

            # 1) ----------------------------------------------------------------
            # adding metadata to the big chunks
            big_chunk_pieces = self.big_chunker(text)
            # Support both dict-based and raw-string outputs
            big_chunk_texts: List[str] = [
                (bc["text"] if isinstance(bc, dict) else str(bc))
                for bc in big_chunk_pieces
            ]
            if not big_chunk_texts:
                return None

            # 2) ----------------------------------------------------------------
            # SMALL CHUNKING (+ optional summaries)
            #    We prepare the text material that needs to be embedded in a flat
            #    list so we can send it to the embedder **in batches**.
            #
            embed_payload: List[str] = []
            work_items: List[dict[str, Any]] = []  # metadata for reconstructing

            for big_idx, big_text in enumerate(big_chunk_texts):
                # 2.a) Optional summary generation
                if self.enable_summaries:
                    try:
                        summary_text = self._generate_summary(big_text)
                    except Exception as exc:
                        summary_text = big_text[:200]

                    work_items.append(
                        {
                            "type": "summary",
                            "big_idx": big_idx,
                            "text": summary_text,
                        }
                    )
                    embed_payload.append(summary_text)

                # 2.b) Small chunks
                small_chunk_pieces = self.small_chunker(big_text)
                small_chunks_texts = [
                    (sc["text"] if isinstance(sc, dict) else str(sc))
                    for sc in small_chunk_pieces
                ]
                for small_idx, small_text in enumerate(small_chunks_texts):
                    work_items.append({
                        "type": "small_chunk",
                        "big_idx": big_idx,
                        "small_idx": small_idx,
                        "text": small_text,
                    })
                    embed_payload.append(small_text)

            

            # 3) ----------------------------------------------------------------
            embeddings: List[List[float]] = self._embed_in_batches(embed_payload)
            # Map embeddings back to work_items in-place
            for item, vector in zip(work_items, embeddings, strict=True):
                item["embedding"] = vector

            # Arrange data in a structure that makes DB insertion straightforward.
            big_work: List[dict[str, Any]] = [
                {
                    "text": big_chunk_texts[i],
                    "summary": None,
                    "small_chunks": [],
                }
                for i in range(len(big_chunk_texts))
            ]

            for item in work_items:
                bi = item["big_idx"]
                if item["type"] == "summary":
                    big_work[bi]["summary"] = item
                else:
                    big_work[bi]["small_chunks"].append(item)

            # 4) ----------------------------------------------------------------
            # DATABASE PERSISTENCE –––––––––––––––––––––––––––––––––––––––––––––––
            with session_scope(write_enabled=True) as session:
                # Retrieve bootstrap file row so we can attach relationships
                file_obj: models.File | None = session.get(models.File, inserted_file_id)
                if file_obj is None:
                    raise RuntimeError("Bootstrap File row vanished before persistence step")

                # Update metadata in case it changed (rare) and clear error if any
                file_obj.status = models.File.FileStatus.OK
                file_obj.error_message = None

                for bw in big_work:
                    bc_obj = models.BigChunk(text=bw["text"], file=file_obj)
                    session.add(bc_obj)

                    # summary (if available)
                    summary_item = bw.get("summary")
                    if summary_item is not None:
                        summary_obj = models.BigChunkSummary(
                            text=summary_item["text"],
                            embedding=summary_item["embedding"],
                            big_chunk=bc_obj,
                        )
                        session.add(summary_obj)

                    # small chunks
                    for sc_item in bw["small_chunks"]:
                        sc_obj = models.SmallChunk(
                            text=sc_item["text"],
                            embedding=sc_item["embedding"],
                        )
                        bc_obj.small_chunks.append(sc_obj)

                session.flush()

            return inserted_file_id

        except Exception as exc:
            # ----------------------------------------------------------------
            # Failure handling – mark file as failed so retrieval skips it
            # ----------------------------------------------------------------
            with session_scope(write_enabled=True) as session:
                file_row: models.File | None = session.query(models.File).get(inserted_file_id)
                if file_row is not None:
                    file_row.status = models.File.FileStatus.FAILED
                    file_row.error_message = str(exc)
                    session.add(file_row)
                    session.flush()
            # Re-raise after marking failure so callers can see the error
            raise



if __name__ == "__main__":
    import os
    from tqdm import tqdm

    inserter = NeoInserter()
    file_kwargs = {}
    src = "/data_playground/cleaned-Hors-Cadres"

    md_files = [
        os.path.join(root, fname)
        for root, _, files in os.walk(src)
        for fname in files if fname.endswith(".md")
    ]

    print(f"Found {len(md_files)} markdown files.")

    for fp in tqdm(md_files):
        try:
            with open(fp, "r", encoding="utf-8") as f:
                content = f.read()
            inserter.insert(fp, content, **file_kwargs)
        except Exception as e:
            print(f"Failed to insert file {fp}: {e}")
            exit()
            continue
