import json
import logging
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

from services.embedder import embed_text
from services.vector_store import search_similar_chunks
from services.llm import get_answer, get_chat_history, save_chat_message
from services.auth import decode_jwt_token
from services.auth import decode_jwt_token, create_user, login_user
from services.cache import generate_cache_key, get_cached_answer, save_cached_answer
from services.vector_store import search_similar_chunks, update_document_status

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

AWS_REGION = os.getenv("AWS_REGION")
DB_URL = os.getenv("SUPABASE_DB_URL")
JWT_SECRET = os.getenv("JWT_SECRET_KEY")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM")
SARVAM_API_KEY = os.getenv("SARVAM_API_KEY")
JWT_EXPIRY_MINUTES = os.getenv("JWT_EXPIRY_MINUTES", "60")
S3_BUCKET = os.getenv("S3_BUCKET")


def build_response(status_code: int, body: dict) -> dict:
    """Build a standard API Gateway response with CORS headers."""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*"
        },
        "body": json.dumps(body)
    }


def get_session_or_create(db_url: str, user_id: str, session_id: str | None, question: str) -> str:
    """
    Return existing session_id if provided.
    Otherwise create a new session using the question as the title.
    """
    if session_id:
        return session_id

    conn = psycopg2.connect(db_url)
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO sessions (user_id, title)
        VALUES (%s, %s)
        RETURNING id
        """,
        (user_id, question[:100])  # first 100 chars of question becomes title
    )

    new_session_id = str(cursor.fetchone()[0])
    conn.commit()
    cursor.close()
    conn.close()

    logger.info(f"Created new session {new_session_id} for user {user_id}")
    return new_session_id

def handle_register(event: dict) -> dict:
    """Handle POST /auth/register — no token required."""
    try:
        body = json.loads(event.get("body", "{}"))
        email = body.get("email", "").strip()
        password = body.get("password", "").strip()

        if not email or not password:
            return build_response(400, {"error": "email and password are required."})

        user = create_user(DB_URL, email, password)
        return build_response(201, {"message": "Account created successfully.", "user": user})

    except ValueError as e:
        return build_response(409, {"error": str(e)})
    except Exception as e:
        logger.error(f"Register error: {e}")
        return build_response(500, {"error": "Something went wrong."})


def handle_login(event: dict) -> dict:
    """Handle POST /auth/login — no token required."""
    try:
        body = json.loads(event.get("body", "{}"))
        email = body.get("email", "").strip()
        password = body.get("password", "").strip()

        if not email or not password:
            return build_response(400, {"error": "email and password are required."})

        token = login_user(DB_URL, email, password, JWT_SECRET, JWT_ALGORITHM, int(JWT_EXPIRY_MINUTES))
        return build_response(200, {"token": token})

    except ValueError as e:
        return build_response(401, {"error": str(e)})
    except Exception as e:
        logger.error(f"Login error: {e}")
        return build_response(500, {"error": "Something went wrong."})


def handle_query(event: dict, user_id: str) -> dict:
    """Handle POST /query — token required."""
    try:
        body = json.loads(event.get("body", "{}"))
        question = body.get("question", "").strip()
        session_id = body.get("session_id", None)
        document_ids = body.get("document_ids", [])  # optional filter

        if not question:
            return build_response(400, {"error": "question is required."})

        # Step 1 — check cache first
        cache_key = generate_cache_key(user_id, question, document_ids)
        cached_answer = get_cached_answer(DB_URL, cache_key)

        if cached_answer:
            logger.info(f"Cache HIT — returning cached answer")
            session_id = get_session_or_create(DB_URL, user_id, session_id, question)
            save_chat_message(DB_URL, session_id, user_id, question, cached_answer, [])
            return build_response(200, {
                "answer": cached_answer,
                "session_id": session_id,
                "sources": [],
                "cached": True
            })

        # Step 2 — embed the question
        query_embedding = embed_text(question, AWS_REGION)

        # Step 3 — search pgvector with optional document filter
        chunks = search_similar_chunks(
            DB_URL,
            user_id,
            query_embedding,
            top_k=5,
            document_ids=document_ids if document_ids else None
        )

        if not chunks:
            return build_response(200, {
                "answer": "I could not find relevant information in your documents.",
                "session_id": session_id,
                "sources": [],
                "cached": False
            })

        # Step 4 — get or create session
        session_id = get_session_or_create(DB_URL, user_id, session_id, question)

        # Step 5 — fetch last 3 messages for context
        chat_history = get_chat_history(DB_URL, session_id)

        # Step 6 — get answer from Sarvam AI
        answer = get_answer(question, chunks, chat_history, SARVAM_API_KEY)

        # Step 7 — extract sources
        sources = list(set(chunk["document_id"] for chunk in chunks))

        # Step 8 — save to cache
        save_cached_answer(DB_URL, cache_key, user_id, question, answer, document_ids)

        # Step 9 — save to chat history
        save_chat_message(DB_URL, session_id, user_id, question, answer, sources)

        return build_response(200, {
            "answer": answer,
            "session_id": session_id,
            "sources": sources,
            "cached": False
        })

    except RuntimeError as e:
        if "Rate limit exceeded" in str(e):
            logger.warning(f"Rate limit hit: {e}")
            return build_response(429, {"error": str(e)})
        logger.error(f"Query error: {e}")
        return build_response(500, {"error": "Something went wrong."})
    except Exception as e:
        logger.error(f"Query error: {e}")
        return build_response(500, {"error": "Something went wrong."})


def handle_upload(event: dict, user_id: str) -> dict:
    """Handle POST /ingest/upload — generates presigned S3 URL."""
    try:
        body = json.loads(event.get("body", "{}"))
        filename = body.get("filename", "").strip()

        if not filename:
            return build_response(400, {"error": "filename is required."})

        import uuid
        import boto3
        document_id = str(uuid.uuid4())
        s3_key = f"uploads/{user_id}/{document_id}/{filename}"

        # Save document record to DB
        import psycopg2
        conn = psycopg2.connect(DB_URL)
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO documents (id, user_id, filename, s3_key, status)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (document_id, user_id, filename, s3_key, "processing")
        )
        conn.commit()
        cursor.close()
        conn.close()

        # Generate presigned URL so user uploads directly to S3
        s3 = boto3.client("s3", region_name=AWS_REGION)
        presigned_url = s3.generate_presigned_url(
            "put_object",
            Params={"Bucket": S3_BUCKET, "Key": s3_key},
            ExpiresIn=300
        )

        return build_response(200, {
            "upload_url": presigned_url,
            "document_id": document_id,
            "s3_key": s3_key
        })

    except Exception as e:
        logger.error(f"Upload error: {e}")
        return build_response(500, {"error": "Something went wrong."})


def handle_documents(event: dict, user_id: str) -> dict:
    """Handle GET /ingest/documents — list user's uploaded documents."""
    try:
        import psycopg2
        conn = psycopg2.connect(DB_URL)
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, filename, status, uploaded_at
            FROM documents
            WHERE user_id = %s
            ORDER BY uploaded_at DESC
            """,
            (user_id,)
        )
        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        documents = [
            {
                "id": str(row[0]),
                "filename": row[1],
                "status": row[2],
                "uploaded_at": str(row[3])
            }
            for row in rows
        ]

        return build_response(200, {"documents": documents})

    except Exception as e:
        logger.error(f"Documents error: {e}")
        return build_response(500, {"error": "Something went wrong."})


def handle_history(event: dict, user_id: str) -> dict:
    """Handle GET /query/history — return chat sessions and messages."""
    try:
        import psycopg2
        conn = psycopg2.connect(DB_URL)
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, title, created_at
            FROM sessions
            WHERE user_id = %s
            ORDER BY created_at DESC
            """,
            (user_id,)
        )
        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        sessions = [
            {
                "id": str(row[0]),
                "title": row[1],
                "created_at": str(row[2])
            }
            for row in rows
        ]

        return build_response(200, {"sessions": sessions})

    except Exception as e:
        logger.error(f"History error: {e}")
        return build_response(500, {"error": "Something went wrong."})

def handler(event, context):
    """
    Lambda entry point — triggered by API Gateway.
    Routes requests to the correct function based on the path.
    """
    path = event.get("path", "")
    method = event.get("httpMethod", "")

    # ── Auth routes — no token needed ─────────────────────────────
    if path == "/auth/register" and method == "POST":
        return handle_register(event)

    if path == "/auth/login" and method == "POST":
        return handle_login(event)

    # ── All other routes — token required ─────────────────────────
    try:
        headers = event.get("headers", {})
        auth_header = headers.get("Authorization") or headers.get("authorization", "")

        if not auth_header.startswith("Bearer "):
            return build_response(401, {"error": "Missing or invalid Authorization header."})

        token = auth_header.split(" ")[1]
        user_id = decode_jwt_token(token, JWT_SECRET, JWT_ALGORITHM)

    except ValueError as e:
        return build_response(401, {"error": str(e)})

    # ── Route to correct handler ───────────────────────────────────
    if path == "/query" and method == "POST":
        return handle_query(event, user_id)

    if path == "/query/history" and method == "GET":
        return handle_history(event, user_id)

    if path == "/ingest/upload" and method == "POST":
        return handle_upload(event, user_id)

    if path == "/ingest/documents" and method == "GET":
        return handle_documents(event, user_id)

    return build_response(404, {"error": "Route not found."})