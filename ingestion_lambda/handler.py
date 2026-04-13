import json
import logging
import os
import tempfile
import boto3
from dotenv import load_dotenv

load_dotenv()

from services.extractor import extract_text
from services.chunker import chunk_text
from services.embedder import embed_many
from services.vector_store import store_embeddings, update_document_status
from services.cache import invalidate_user_cache


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

AWS_REGION = os.getenv("AWS_REGION")
S3_BUCKET = os.getenv("S3_BUCKET")
DB_URL = os.getenv("SUPABASE_DB_URL")

s3 = boto3.client("s3", region_name=AWS_REGION)


def download_from_s3(s3_key: str, local_path: str) -> None:
    """Download a file from S3 to a local temp path."""
    s3.download_file(S3_BUCKET, s3_key, local_path)
    logger.info(f"Downloaded s3://{S3_BUCKET}/{s3_key}")


def process_document(s3_key: str, user_id: str, document_id: str) -> None:
    """
    Full ingestion pipeline for one document.
    Download → Extract → Chunk → Embed → Store -> Invlidate Cache
    """
    file_extension = s3_key.split(".")[-1]

    with tempfile.NamedTemporaryFile(suffix=f".{file_extension}", delete=False) as tmp:
        local_path = tmp.name

    try:
        # Step 1 — Download file from S3
        download_from_s3(s3_key, local_path)

        # Step 2 — Extract text
        text = extract_text(local_path)
        if not text.strip():
            raise ValueError(f"No text could be extracted from {s3_key}")

        # Step 3 — Chunk text
        chunks = chunk_text(text)
        logger.info(f"Created {len(chunks)} chunks from {s3_key}")

        # Step 4 — Embed all chunks
        embeddings = embed_many(chunks, AWS_REGION)
        logger.info(f"Generated {len(embeddings)} embeddings")

        # Step 5 — Store in pgvector
        store_embeddings(DB_URL, user_id, document_id, chunks, embeddings)

        # Step 6 — Mark document as ready
        update_document_status(DB_URL, document_id, "ready")
        logger.info(f"Document {document_id} ingestion complete")
        invalidate_user_cache(DB_URL, user_id)
        logger.info(f"Cache invalidated for user {user_id} after new document")


    except Exception as e:
        # Mark document as failed so user knows something went wrong
        update_document_status(DB_URL, document_id, "failed")
        logger.error(f"Ingestion failed for document {document_id}: {e}")
        raise


def handler(event, context):
    """
    Lambda entry point — triggered by SQS.
    SQS wraps the S3 event inside record['body'] as a JSON string.
    We parse it out and process each document one at a time.
    """
    for sqs_record in event["Records"]:

        # SQS wraps the S3 notification as a JSON string — parse it
        s3_event = json.loads(sqs_record["body"])

        # Skip S3 test notifications — they don't have Records
        if "Records" not in s3_event:
            logger.info("Skipping non-S3 message")
            continue

        for s3_record in s3_event["Records"]:
            bucket = s3_record["s3"]["bucket"]["name"]
            s3_key = s3_record["s3"]["object"]["key"]

            logger.info(f"Processing upload: {s3_key}")

            # S3 key format: uploads/{user_id}/{document_id}/{filename}
            # Example:       uploads/abc-123/def-456/myfile.pdf
            parts = s3_key.split("/")
            if len(parts) < 4:
                logger.error(f"Unexpected S3 key format: {s3_key}")
                continue

            user_id = parts[1]
            document_id = parts[2]

            process_document(s3_key, user_id, document_id)