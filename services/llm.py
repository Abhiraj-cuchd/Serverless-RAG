import logging
import requests
import re
import time
import collections

logger = logging.getLogger(__name__)

# ── Rate Limiter ───────────────────────────────────────────────────
_request_timestamps = collections.deque()
RATE_LIMIT_MAX = 40       # max requests
RATE_LIMIT_WINDOW = 60    # per 60 seconds

SARVAM_API_URL = "https://api.sarvam.ai/v1/chat/completions"
SARVAM_MODEL = "sarvam-105b"


def expand_query(question: str, sarvam_api_key: str) -> str:
    """
    Rewrite a short question into a descriptive paragraph.
    Improves vector similarity matching for short or vague queries.
    """
    # Safety guard — never pass None to Sarvam AI
    if not question:
        return ""

    question = str(question).strip()
    if not question:
        return ""

    try:
        headers = {
            "api-subscription-key": sarvam_api_key,
            "Content-Type": "application/json"
        }
        payload = {
            "model": SARVAM_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a search query expander. "
                        "Rewrite the user's question into a descriptive paragraph "
                        "of 2-3 sentences that would help find relevant content in a document. "
                        "Output only the expanded query. Nothing else."
                    )
                },
                {
                    "role": "user",
                    "content": question
                }
            ],
            "max_tokens": 150,
            "temperature": 0.1
        }

        response = requests.post(
            SARVAM_API_URL,
            headers=headers,
            json=payload,
            timeout=15
        )
        response.raise_for_status()

        content = response.json()["choices"][0]["message"]["content"]

        # Guard against None response content
        if not content:
            return question

        expanded = content.strip()

        # Strip think block if present
        if "<think>" in expanded and "</think>" in expanded:
            expanded = expanded.split("</think>")[-1].strip()

        # Final guard — if expansion is empty fall back to original
        if not expanded:
            return question

        logger.info(f"Expanded query: {expanded[:100]}")
        return expanded

    except Exception as e:
        logger.warning(f"Query expansion failed, using original: {e}")
        return question

def check_rate_limit() -> None:
    """
    Track request timestamps and raise an error if rate limit is exceeded.
    Allows max 40 requests per 60 second window.
    """
    now = time.time()
    window_start = now - RATE_LIMIT_WINDOW

    # Remove timestamps older than the window
    while _request_timestamps and _request_timestamps[0] < window_start:
        _request_timestamps.popleft()

    # Check if limit is hit
    if len(_request_timestamps) >= RATE_LIMIT_MAX:
        oldest = _request_timestamps[0]
        wait_seconds = int(RATE_LIMIT_WINDOW - (now - oldest)) + 1
        raise RuntimeError(
            f"Rate limit exceeded. Maximum {RATE_LIMIT_MAX} requests "
            f"per minute. Please wait {wait_seconds} seconds."
        )

    # Record this request
    _request_timestamps.append(now)


def build_prompt(
    question: str,
    context_chunks: list[dict],
    chat_history: list[dict],
    is_summary: bool = False
) -> list[dict]:
    """
    Build the messages list to send to Sarvam AI.
    Includes system instructions, last 3 chat messages, retrieved context, and current question.
    """
    messages = []

    messages.append({
        "role": "system",
        "content": (
            "You are a helpful assistant that answers questions strictly based on "
            "the provided document context. "
            "If the context does not contain enough information to answer, say: "
            "'I don't have enough information in your documents to answer that.' "
            "Never make up information that is not in the context."
        )
    })

    for message in chat_history[-3:]:
        messages.append({"role": "user", "content": message["question"]})
        messages.append({"role": "assistant", "content": message["answer"]})

    max_words_per_chunk = 100 if is_summary else 300

    # Truncate each chunk to 300 words to stay within token limits
    truncated_chunks = []
    for chunk in context_chunks:
        words = chunk["chunk_text"].split()
        truncated_text = " ".join(words[:max_words_per_chunk])
        truncated_chunks.append({**chunk, "chunk_text": truncated_text})

    context_text = "\n\n---\n\n".join([
        f"Source: {chunk['document_id']}\n{chunk['chunk_text']}"
        for chunk in truncated_chunks
        if chunk.get('chunk_text')  # skip any chunks with None text
    ])

    if not context_text:
        context_text = "No relevant context found."

    messages.append({
        "role": "user",
        "content": (
            f"Here is the relevant context from your documents:\n\n"
            f"{context_text}\n\n"
            f"Question: {question}"
        )
    })

    return messages


def get_answer(
    question: str,
    context_chunks: list[dict],
    chat_history: list[dict],
    sarvam_api_key: str,
    is_summary: bool = False
) -> str:
    """
    Send the question + context + history to Sarvam AI.
    Returns the generated answer as a string.
    """
    # Safety guard
    if not question or not question.strip():
        raise ValueError("Question cannot be empty.")

    if not context_chunks:
        raise ValueError("No context chunks provided.")

    check_rate_limit()

    try:
        messages = build_prompt(question, context_chunks, chat_history, is_summary)

        headers = {
            "api-subscription-key": sarvam_api_key,
            "Content-Type": "application/json"
        }

        payload = {
            "model": SARVAM_MODEL,
            "messages": messages,
            "max_tokens": 1024,
            "temperature": 0.3
        }

        response = requests.post(
            SARVAM_API_URL,
            headers=headers,
            json=payload,
            timeout=30
        )

        response.raise_for_status()
        result = response.json()
        answer = result["choices"][0]["message"]["content"]

        clean_answer = re.sub(r"<think>.*?</think>", "", answer, flags=re.DOTALL).strip()

        logger.info(f"Sarvam AI returned answer of {len(answer)} characters")
        return clean_answer

    except requests.exceptions.Timeout:
        raise RuntimeError("Sarvam AI request timed out after 30 seconds.")
    except requests.exceptions.HTTPError as e:
        raise RuntimeError(f"Sarvam AI API error: {e}")
    except Exception as e:
        raise RuntimeError(f"Failed to get answer from Sarvam AI: {e}")


def get_chat_history(db_url: str, session_id: str) -> list[dict]:
    """
    Fetch the last 3 Q&A pairs from a session for use as chat context.
    Imported here to keep all LLM-related logic in one place.
    """
    import psycopg2

    try:
        conn = psycopg2.connect(db_url)
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT question, answer
            FROM chat_messages
            WHERE session_id = %s
            ORDER BY created_at DESC
            LIMIT 3
            """,
            (session_id,)
        )

        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        # Reverse so oldest message comes first
        history = [{"question": row[0], "answer": row[1]} for row in reversed(rows)]
        logger.info(f"Fetched {len(history)} previous messages for session {session_id}")
        return history

    except Exception as e:
        raise RuntimeError(f"Failed to fetch chat history: {e}")


def save_chat_message(
    db_url: str,
    session_id: str,
    user_id: str,
    question: str,
    answer: str,
    sources: list[str]
) -> None:
    """Save a Q&A pair and its sources into the chat_messages table."""
    import psycopg2
    import json

    try:
        conn = psycopg2.connect(db_url)
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO chat_messages (session_id, user_id, question, answer, sources)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (session_id, user_id, question, answer, json.dumps(sources))
        )

        conn.commit()
        cursor.close()
        conn.close()
        logger.info(f"Saved chat message for session {session_id}")

    except Exception as e:
        raise RuntimeError(f"Failed to save chat message: {e}")