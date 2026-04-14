import logging
from pgvector.psycopg2 import register_vector
import psycopg2

logger = logging.getLogger(__name__)


def get_connection(db_url: str):
    """Create and return a PostgreSQL connection with pgvector registered."""
    conn = psycopg2.connect(db_url)
    register_vector(conn)
    return conn


def store_embeddings(
    db_url: str,
    user_id: str,
    document_id: str,
    chunks: list[str],
    embeddings: list[list[float]]
) -> None:
    """
    Save all chunks and their vectors into the embeddings table.
    Each chunk is linked to the user and document it came from.
    """
    try:
        conn = get_connection(db_url)
        cursor = conn.cursor()

        for index, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            cursor.execute(
                """
                INSERT INTO embeddings (user_id, document_id, chunk_text, chunk_index, embedding)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (user_id, document_id, chunk, index, embedding)
            )

        conn.commit()
        cursor.close()
        conn.close()
        logger.info(f"Generated embedding with {len(embedding)} dimensions")

    except Exception as e:
        raise RuntimeError(f"Failed to store embeddings: {e}")

#
# def search_similar_chunks(
#     db_url: str,
#     user_id: str,
#     query_embedding: list[float],
#     top_k: int = 5
# ) -> list[dict]:
#     """
#     Search for the top K most similar chunks for a given query vector.
#     Results are scoped strictly to the logged-in user — no cross-user leakage.
#     """
#     try:
#         conn = get_connection(db_url)
#         cursor = conn.cursor()
#
#         cursor.execute(
#             """
#             SELECT chunk_text, chunk_index, document_id,
#                    1 - (embedding <=> %s::vector) AS similarity
#             FROM embeddings
#             WHERE user_id = %s
#             ORDER BY embedding <=> %s::vector
#             LIMIT %s
#             """,
#             (query_embedding, user_id, query_embedding, top_k)
#         )
#
#         rows = cursor.fetchall()
#         cursor.close()
#         conn.close()
#
#         results = [
#             {
#                 "chunk_text": row[0],
#                 "chunk_index": row[1],
#                 "document_id": str(row[2]),
#                 "similarity": float(row[3])
#             }
#             for row in rows
#         ]
#
#         logger.info(f"Found {len(results)} similar chunks for user {user_id}")
#         return results
#
#     except Exception as e:
#         raise RuntimeError(f"Failed to search embeddings: {e}")

def search_similar_chunks(
    db_url: str,
    user_id: str,
    query_embedding: list[float],
    top_k: int = 5,
    document_ids: list[str] | None = None
) -> list[dict]:
    """
    Search for the top K most similar chunks for a given query vector.
    Results are scoped strictly to the logged-in user.
    Optionally filter by specific document IDs.
    """
    try:
        conn = get_connection(db_url)
        cursor = conn.cursor()

        if document_ids:
            # Search only within selected documents
            cursor.execute(
                """
                SELECT chunk_text, chunk_index, document_id,
                       1 - (embedding <=> %s::vector) AS similarity
                FROM embeddings
                WHERE user_id = %s
                AND document_id = ANY(%s::uuid[])
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (query_embedding, user_id, document_ids, query_embedding, top_k)
            )
        else:
            # Search all user documents
            cursor.execute(
                """
                SELECT chunk_text, chunk_index, document_id,
                       1 - (embedding <=> %s::vector) AS similarity
                FROM embeddings
                WHERE user_id = %s
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (query_embedding, user_id, query_embedding, top_k)
            )

        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        results = [
            {
                "chunk_text": row[0],
                "chunk_index": row[1],
                "document_id": str(row[2]),
                "similarity": float(row[3])
            }
            for row in rows
        ]

        logger.info(
            f"Found {len(results)} chunks for user {user_id}"
            f"{f' filtered to {len(document_ids)} docs' if document_ids else ''}"
        )
        return results

    except Exception as e:
        raise RuntimeError(f"Failed to search embeddings: {e}")


def update_document_status(db_url: str, document_id: str, status: str) -> None:
    """Update the processing status of a document (processing / ready / failed)."""
    try:
        conn = get_connection(db_url)
        cursor = conn.cursor()

        cursor.execute(
            "UPDATE documents SET status = %s WHERE id = %s",
            (status, document_id)
        )

        conn.commit()
        cursor.close()
        conn.close()
        logger.info(f"Document {document_id} status updated to '{status}'")

    except Exception as e:
        raise RuntimeError(f"Failed to update document status: {e}")

def hybrid_search(
    db_url: str,
    user_id: str,
    query_embedding: list[float],
    question: str,
    top_k: int = 5,
    document_ids: list[str] | None = None
) -> list[dict]:
    """
    Combine vector similarity search with keyword search.
    Vector results capture semantic meaning.
    Keyword results catch exact term matches.
    Merged and deduplicated before returning.
    """
    # Step 1 — vector similarity search
    vector_results = search_similar_chunks(
        db_url, user_id, query_embedding, top_k, document_ids
    )

    # Track chunk indexes already in vector results to avoid duplicates
    vector_chunk_indexes = {r["chunk_index"] for r in vector_results}

    # Step 2 — keyword search using LIKE
    try:
        conn = get_connection(db_url)
        cursor = conn.cursor()

        # Extract meaningful keywords — ignore short words
        keywords = [
            word.lower() for word in question.split()
            if len(word) > 3
        ]

        if not keywords:
            return vector_results

        # Build LIKE conditions for each keyword
        like_conditions = " OR ".join([
            "LOWER(chunk_text) LIKE %s" for _ in keywords
        ])
        like_values = [f"%{kw}%" for kw in keywords]

        if document_ids:
            cursor.execute(
                f"""
                SELECT chunk_text, chunk_index, document_id, 0.5 AS similarity
                FROM embeddings
                WHERE user_id = %s
                AND document_id = ANY(%s::uuid[])
                AND ({like_conditions})
                LIMIT %s
                """,
                [user_id, document_ids] + like_values + [top_k]
            )
        else:
            cursor.execute(
                f"""
                SELECT chunk_text, chunk_index, document_id, 0.5 AS similarity
                FROM embeddings
                WHERE user_id = %s
                AND ({like_conditions})
                LIMIT %s
                """,
                [user_id] + like_values + [top_k]
            )

        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        # Only add keyword results not already in vector results
        keyword_results = [
            {
                "chunk_text": row[0],
                "chunk_index": row[1],
                "document_id": str(row[2]),
                "similarity": float(row[3])
            }
            for row in rows
            if row[1] not in vector_chunk_indexes
        ]

    except Exception as e:
        logger.warning(f"Keyword search failed, using vector results only: {e}")
        keyword_results = []

    # Step 3 — merge: vector first, keyword appended
    combined = vector_results + keyword_results

    logger.info(
        f"Hybrid search: {len(vector_results)} vector + "
        f"{len(keyword_results)} keyword = {len(combined)} total chunks"
    )
    return combined