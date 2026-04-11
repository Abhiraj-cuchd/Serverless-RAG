import logging
import requests

logger = logging.getLogger(__name__)

SARVAM_API_URL = "https://api.sarvam.ai/v1/chat/completions"
SARVAM_MODEL = "sarvam-m"


def build_prompt(
    question: str,
    context_chunks: list[dict],
    chat_history: list[dict]
) -> list[dict]:
    """
    Build the messages list to send to Sarvam AI.
    Includes system instructions, last 3 chat messages, retrieved context, and current question.
    """
    messages = []

    # System instruction — tells the AI how to behave
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

    # Add last 3 messages from chat history so follow-up questions work naturally
    for message in chat_history[-3:]:
        messages.append({"role": "user", "content": message["question"]})
        messages.append({"role": "assistant", "content": message["answer"]})

    # Build context block from retrieved chunks
    context_text = "\n\n---\n\n".join([
        f"Source: {chunk['document_id']}\n{chunk['chunk_text']}"
        for chunk in context_chunks
    ])

    # Final user message — context + actual question
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
    sarvam_api_key: str
) -> str:
    """
    Send the question + context + history to Sarvam AI.
    Returns the generated answer as a string.
    """
    try:
        messages = build_prompt(question, context_chunks, chat_history)

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

        logger.info(f"Sarvam AI returned answer of {len(answer)} characters")
        return answer

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