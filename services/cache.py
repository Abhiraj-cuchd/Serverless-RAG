import json
import hashlib
import logging
import psycopg2
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

CACHE_TTL_HOURS = 24


def generate_cache_key(user_id: str, question: str, document_ids: list[str]) -> str:
    """
    Generate a unique hash key for a query.
    Same user + same question + same selected docs = same cache key.
    """
    normalized = f"{user_id}:{question.lower().strip()}:{sorted(document_ids)}"
    return hashlib.md5(normalized.encode()).hexdigest()


def get_cached_answer(db_url: str, cache_key: str) -> str | None:
    """
    Look up a cache key in the database.
    Returns the cached answer if found and not expired, None otherwise.
    """
    try:
        conn = psycopg2.connect(db_url)
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT answer FROM query_cache
            WHERE cache_key = %s
            AND expires_at > now()
            """,
            (cache_key,)
        )

        row = cursor.fetchone()
        cursor.close()
        conn.close()

        if row:
            logger.info(f"Cache HIT for key {cache_key[:8]}...")
            return row[0]

        logger.info(f"Cache MISS for key {cache_key[:8]}...")
        return None

    except Exception as e:
        # Cache failure should never break the main flow
        logger.warning(f"Cache lookup failed: {e}")
        return None


def save_cached_answer(
    db_url: str,
    cache_key: str,
    user_id: str,
    question: str,
    answer: str,
    document_ids: list[str]
) -> None:
    """
    Save a question + answer pair to the cache.
    Expires after CACHE_TTL_HOURS hours.
    If the same key exists, update it.
    """
    try:
        conn = psycopg2.connect(db_url)
        cursor = conn.cursor()

        expires_at = datetime.utcnow() + timedelta(hours=CACHE_TTL_HOURS)

        cursor.execute(
            """
            INSERT INTO query_cache
              (cache_key, user_id, question, answer, document_ids, expires_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (cache_key)
            DO UPDATE SET
              answer = EXCLUDED.answer,
              expires_at = EXCLUDED.expires_at
            """,
            (
                cache_key,
                user_id,
                question,
                answer,
                json.dumps(document_ids),
                expires_at
            )
        )

        conn.commit()
        cursor.close()
        conn.close()
        logger.info(f"Cached answer for key {cache_key[:8]}...")

    except Exception as e:
        # Cache failure should never break the main flow
        logger.warning(f"Cache save failed: {e}")


def invalidate_user_cache(db_url: str, user_id: str) -> None:
    """
    Delete all cached answers for a user.
    Called when a new document is uploaded so stale answers are removed.
    """
    try:
        conn = psycopg2.connect(db_url)
        cursor = conn.cursor()

        cursor.execute(
            "DELETE FROM query_cache WHERE user_id = %s",
            (user_id,)
        )

        deleted = cursor.rowcount
        conn.commit()
        cursor.close()
        conn.close()
        logger.info(f"Invalidated {deleted} cache entries for user {user_id}")

    except Exception as e:
        logger.warning(f"Cache invalidation failed: {e}")