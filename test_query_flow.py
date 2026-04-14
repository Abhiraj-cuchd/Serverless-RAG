import os
import logging
from dotenv import load_dotenv

load_dotenv()

# Setup logging so we see everything
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

DB_URL = os.getenv("SUPABASE_DB_URL")
AWS_REGION = os.getenv("AWS_REGION")
SARVAM_API_KEY = os.getenv("SARVAM_API_KEY")

# ── Use the same user_id from your DB ─────────────────────────────
# Run this in Supabase SQL editor first:
# SELECT id, email FROM users LIMIT 5;
USER_ID = "4406d38a-5809-4da3-b542-bc128b2c3310"

QUESTION = "what are Hamiltonian Graphs?"

print(f"\n{'='*60}")
print(f"Testing query flow for: '{QUESTION}'")
print(f"{'='*60}\n")


# Step 1 — Query Expansion
print("STEP 1 — Query Expansion")
from services.llm import expand_query
expanded = expand_query(QUESTION, SARVAM_API_KEY)
print(f"Original : {QUESTION}")
print(f"Expanded : {expanded}")
print(f"Type     : {type(expanded)}")
print()


# Step 2 — Embed expanded question
print("STEP 2 — Embedding")
from services.embedder import embed_text
query_embedding = embed_text(expanded, AWS_REGION)
print(f"Embedding dimensions: {len(query_embedding)}")
print()


# Step 3 — Hybrid Search
print("STEP 3 — Hybrid Search")
from services.vector_store import hybrid_search
chunks = hybrid_search(
    DB_URL,
    USER_ID,
    query_embedding,
    QUESTION,
    top_k=5
)
print(f"Total chunks returned: {len(chunks)}")
for i, chunk in enumerate(chunks):
    print(f"\nChunk {i+1}:")
    print(f"  Index     : {chunk['chunk_index']}")
    print(f"  Similarity: {chunk['similarity']}")
    print(f"  Text      : {chunk['chunk_text'][:150]}...")
print()


# Step 4 — Get Answer
print("STEP 4 — Sarvam AI Answer")
from services.llm import get_answer
if chunks:
    answer = get_answer(
        question=QUESTION,
        context_chunks=chunks,
        chat_history=[],
        sarvam_api_key=SARVAM_API_KEY,
        is_summary=False
    )
    print(f"Answer: {answer}")
else:
    print("No chunks found — skipping LLM call")

print(f"\n{'='*60}")
print("Flow complete")
print(f"{'='*60}\n")
