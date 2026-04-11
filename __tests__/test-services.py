import os
import tempfile
from dotenv import load_dotenv

load_dotenv()

DB_URL = os.getenv("SUPABASE_DB_URL")
AWS_REGION = os.getenv("AWS_REGION")
SARVAM_API_KEY = os.getenv("SARVAM_API_KEY")
JWT_SECRET = os.getenv("JWT_SECRET_KEY")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM")
JWT_EXPIRY = int(os.getenv("JWT_EXPIRY_MINUTES"))

print("\n========== TESTING ALL SERVICES ==========\n")


# ── Test 1: Extractor ──────────────────────────────────────────────
print("TEST 1 — extractor.py")
from services.extractor import extract_text

# Create a temporary txt file to test with
with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False) as f:
    f.write("This is a test document. It talks about AWS Lambda and RAG systems.")
    temp_path = f.name

text = extract_text(temp_path)
assert len(text) > 0, "Extractor returned empty text"
print(f"✅ Extracted {len(text)} characters\n")


# ── Test 2: Chunker ────────────────────────────────────────────────
print("TEST 2 — chunker.py")
from services.chunker import chunk_text

chunks = chunk_text(text)
assert len(chunks) > 0, "Chunker returned no chunks"
print(f"✅ Created {len(chunks)} chunks\n")


# ── Test 3: Embedder ───────────────────────────────────────────────
print("TEST 3 — embedder.py")
from services.embedder import embed_text

embedding = embed_text(chunks[0], AWS_REGION)
assert len(embedding) == 1024, f"Expected 1024 dimensions, got {len(embedding)}"
print(f"✅ Got embedding with {len(embedding)} dimensions\n")


# ── Test 4: Auth — Register ────────────────────────────────────────
print("TEST 4 — auth.py (register)")
from services.auth import create_user, login_user, decode_jwt_token

test_email = "testuser@example.com"
test_password = "testpassword123"

try:
    user = create_user(DB_URL, test_email, test_password)
    print(f"✅ Created user: {user['email']} with id: {user['id']}\n")
    user_id = user["id"]
except ValueError as e:
    # User already exists from a previous test run — just log in
    print(f"⚠️  User already exists, skipping register: {e}\n")
    user_id = None


# ── Test 5: Auth — Login ───────────────────────────────────────────
print("TEST 5 — auth.py (login)")

token = login_user(DB_URL, test_email, test_password, JWT_SECRET, JWT_ALGORITHM, JWT_EXPIRY)
decoded_user_id = decode_jwt_token(token, JWT_SECRET, JWT_ALGORITHM)

if user_id is None:
    user_id = decoded_user_id  # use the id from login if register was skipped

assert decoded_user_id is not None, "Could not decode user_id from token"
print(f"✅ Logged in. Token decoded to user_id: {decoded_user_id}\n")


# ── Test 6: Vector Store — Save ────────────────────────────────────
print("TEST 6 — vector_store.py (store embeddings)")
from services.vector_store import store_embeddings, search_similar_chunks
import psycopg2

# Create a dummy document row first so we have a document_id
conn = psycopg2.connect(DB_URL)
cursor = conn.cursor()
cursor.execute(
    """
    INSERT INTO documents (user_id, filename, s3_key, status)
    VALUES (%s, %s, %s, %s)
    RETURNING id
    """,
    (user_id, "test.txt", "uploads/test.txt", "processing")
)
document_id = str(cursor.fetchone()[0])
conn.commit()
cursor.close()
conn.close()

embeddings = [embedding]
store_embeddings(DB_URL, user_id, document_id, chunks, embeddings)
print(f"✅ Stored {len(chunks)} embeddings for document {document_id}\n")


# ── Test 7: Vector Store — Search ─────────────────────────────────
print("TEST 7 — vector_store.py (search)")

query_embedding = embed_text("tell me about AWS Lambda", AWS_REGION)
results = search_similar_chunks(DB_URL, user_id, query_embedding, top_k=3)

assert len(results) > 0, "Search returned no results"
print(f"✅ Found {len(results)} similar chunks")
print(f"   Top result: {results[0]['chunk_text'][:80]}...\n")


# ── Test 8: LLM ────────────────────────────────────────────────────
print("TEST 8 — llm.py (Sarvam AI)")
from services.llm import get_answer

answer = get_answer(
    question="What does this document talk about?",
    context_chunks=results,
    chat_history=[],
    sarvam_api_key=SARVAM_API_KEY
)

assert len(answer) > 0, "Sarvam AI returned empty answer"
print(f"✅ Got answer from Sarvam AI:")
print(f"   {answer[:150]}...\n")


print("========== ALL TESTS PASSED ✅ ==========\n")