import os
import json
from dotenv import load_dotenv

load_dotenv()

# Simulate what API Gateway sends to Lambda
def make_api_gateway_event(question: str, token: str, session_id: str = None) -> dict:
    """Build a fake API Gateway event exactly like AWS would send."""
    body = {"question": question}
    if session_id:
        body["session_id"] = session_id

    return {
        "headers": {
            "Authorization": f"Bearer {token}"
        },
        "body": json.dumps(body)
    }


print("\n========== TESTING QUERY LAMBDA ==========\n")


# ── Step 1: Login to get a real JWT token ──────────────────────────
print("STEP 1 — Login to get JWT token")
from services.auth import login_user

token = login_user(
    db_url=os.getenv("SUPABASE_DB_URL"),
    email="testuser@example.com",
    plain_password="testpassword123",
    secret_key=os.getenv("JWT_SECRET_KEY"),
    algorithm=os.getenv("JWT_ALGORITHM"),
    expiry_minutes=int(os.getenv("JWT_EXPIRY_MINUTES"))
)
print(f"✅ Got token: {token[:40]}...\n")


# ── Step 2: Test with no Authorization header ──────────────────────
print("STEP 2 — Test missing auth header (should return 401)")
from query_lambda.handler import handler

fake_event = {"headers": {}, "body": json.dumps({"question": "test"})}
response = handler(fake_event, {})
assert response["statusCode"] == 401
print(f"✅ Got 401 as expected\n")


# ── Step 3: Test with invalid token ───────────────────────────────
print("STEP 3 — Test invalid token (should return 401)")
fake_event = make_api_gateway_event("test question", "invalid-token-xyz")
response = handler(fake_event, {})
assert response["statusCode"] == 401
print(f"✅ Got 401 as expected\n")


# ── Step 4: Test with empty question ──────────────────────────────
print("STEP 4 — Test empty question (should return 400)")
fake_event = make_api_gateway_event("", token)
response = handler(fake_event, {})
assert response["statusCode"] == 400
print(f"✅ Got 400 as expected\n")


# ── Step 5: Test a real question ──────────────────────────────────
print("STEP 5 — Ask a real question")
fake_event = make_api_gateway_event(
    question="What does the document say about AWS Lambda?",
    token=token
)
response = handler(fake_event, {})
body = json.loads(response["body"])

assert response["statusCode"] == 200, f"Expected 200, got {response['statusCode']}: {body}"
assert "answer" in body
assert "session_id" in body

print(f"✅ Got answer:")
print(f"   {body['answer'][:200]}")
print(f"   Session ID: {body['session_id']}")
print(f"   Sources: {body['sources']}\n")


# ── Step 6: Ask a follow-up question in same session ──────────────
print("STEP 6 — Ask a follow-up question in same session")
session_id = body["session_id"]

fake_event = make_api_gateway_event(
    question="Can you elaborate on that?",
    token=token,
    session_id=session_id
)
response = handler(fake_event, {})
body = json.loads(response["body"])

assert response["statusCode"] == 200
assert body["session_id"] == session_id  # same session
print(f"✅ Follow-up answer:")
print(f"   {body['answer'][:200]}\n")


print("========== QUERY LAMBDA TESTS PASSED ✅ ==========\n")