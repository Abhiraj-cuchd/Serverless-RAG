import streamlit as st
import requests
import time

API_URL = "https://ws4wxtdv6f.execute-api.ap-south-1.amazonaws.com/Prod"

st.set_page_config(
    page_title="RAG Knowledge Assistant",
    page_icon="📚",
    layout="centered"
)

# ── Session state ──────────────────────────────────────────────────
if "token" not in st.session_state:
    st.session_state.token = None
if "email" not in st.session_state:
    st.session_state.email = None
if "session_id" not in st.session_state:
    st.session_state.session_id = None
if "messages" not in st.session_state:
    st.session_state.messages = []


# ── API Helpers ────────────────────────────────────────────────────

def auth_headers() -> dict:
    """Return authorization headers for authenticated requests."""
    return {"Authorization": f"Bearer {st.session_state.token}"}


def register(email: str, password: str) -> str | None:
    """Call /auth/register. Returns error string or None on success."""
    response = requests.post(
        f"{API_URL}/auth/register",
        json={"email": email, "password": password}
    )
    if response.status_code == 201:
        return None
    return response.json().get("error", "Registration failed.")


def login(email: str, password: str) -> str | None:
    """Call /auth/login and store token. Returns error string or None."""
    response = requests.post(
        f"{API_URL}/auth/login",
        json={"email": email, "password": password}
    )
    if response.status_code == 200:
        st.session_state.token = response.json()["token"]
        st.session_state.email = email
        return None
    return response.json().get("error", "Login failed.")


def get_documents() -> list:
    """Fetch list of user's uploaded documents."""
    response = requests.get(
        f"{API_URL}/ingest/documents",
        headers=auth_headers()
    )
    if response.status_code == 200:
        return response.json().get("documents", [])
    return []


def upload_document(file) -> str | None:
    """Get presigned URL then upload file directly to S3."""
    # Step 1 — get presigned URL
    response = requests.post(
        f"{API_URL}/ingest/upload",
        headers=auth_headers(),
        json={"filename": file.name}
    )
    if response.status_code != 200:
        return response.json().get("error", "Failed to get upload URL.")

    upload_url = response.json()["upload_url"]

    # Step 2 — upload file directly to S3
    upload_response = requests.put(
        upload_url,
        data=file.getvalue(),
        headers={"Content-Type": file.type or "text/plain"}
    )
    if upload_response.status_code != 200:
        return "Failed to upload file to S3."

    return None


def ask_question(question: str) -> dict | None:
    """Send question to /query and return response."""
    payload = {"question": question}
    if st.session_state.session_id:
        payload["session_id"] = st.session_state.session_id

    response = requests.post(
        f"{API_URL}/query",
        headers={**auth_headers(), "Content-Type": "application/json"},
        json=payload
    )
    if response.status_code == 200:
        return response.json()
    return None


def get_history() -> list:
    """Fetch user's chat sessions."""
    response = requests.get(
        f"{API_URL}/query/history",
        headers=auth_headers()
    )
    if response.status_code == 200:
        return response.json().get("sessions", [])
    return []


# ── Auth Page ──────────────────────────────────────────────────────
if st.session_state.token is None:
    st.title("📚 RAG Knowledge Assistant")
    st.write("Upload your documents and ask questions about them.")
    st.divider()

    tab1, tab2 = st.tabs(["Login", "Register"])

    with tab1:
        st.subheader("Login")
        email = st.text_input("Email", key="login_email")
        password = st.text_input("Password", type="password", key="login_password")

        if st.button("Login", use_container_width=True):
            if not email or not password:
                st.error("Please fill in both fields.")
            else:
                with st.spinner("Logging in..."):
                    error = login(email, password)
                if error:
                    st.error(error)
                else:
                    st.success("Logged in!")
                    st.rerun()

    with tab2:
        st.subheader("Create Account")
        email = st.text_input("Email", key="register_email")
        password = st.text_input("Password", type="password", key="register_password")

        if st.button("Register", use_container_width=True):
            if not email or not password:
                st.error("Please fill in both fields.")
            else:
                with st.spinner("Creating account..."):
                    error = register(email, password)
                if error:
                    st.error(error)
                else:
                    st.success("Account created! Please log in.")


# ── Main App ───────────────────────────────────────────────────────
else:
    # Sidebar
    st.sidebar.title("📚 RAG Assistant")
    st.sidebar.write(f"Logged in as **{st.session_state.email}**")
    st.sidebar.divider()

    page = st.sidebar.radio(
        "Navigate",
        ["💬 Chat", "📁 My Documents", "🕓 History"]
    )

    if st.sidebar.button("Logout", use_container_width=True):
        st.session_state.token = None
        st.session_state.email = None
        st.session_state.session_id = None
        st.session_state.messages = []
        st.rerun()

    # ── Chat Page ──────────────────────────────────────────────────
    if page == "💬 Chat":
        st.title("💬 Ask Your Documents")

        if st.button("➕ New Chat"):
            st.session_state.session_id = None
            st.session_state.messages = []
            st.rerun()

        st.divider()

        # Show existing messages
        for msg in st.session_state.messages:
            with st.chat_message("user"):
                st.write(msg["question"])
            with st.chat_message("assistant"):
                st.write(msg["answer"])
                if msg.get("sources"):
                    st.caption(f"Sources: {', '.join(msg['sources'])}")

        # Question input
        question = st.chat_input("Ask a question about your documents...")

        if question:
            with st.chat_message("user"):
                st.write(question)

            with st.chat_message("assistant"):
                with st.spinner("Thinking..."):
                    result = ask_question(question)

                if result:
                    st.session_state.session_id = result["session_id"]
                    answer = result["answer"]
                    sources = result.get("sources", [])

                    # Typewriter effect — stream words one by one
                    placeholder = st.empty()
                    displayed = ""
                    for word in answer.split(" "):
                        displayed += word + " "
                        placeholder.markdown(displayed + "▌")
                        time.sleep(0.05)
                    placeholder.markdown(displayed.strip())

                    if sources:
                        st.caption(f"Sources: {', '.join(sources)}")
                else:
                    st.error("Something went wrong. Please try again.")

    # ── Documents Page ─────────────────────────────────────────────
    elif page == "📁 My Documents":
        st.title("📁 My Documents")

        # Upload section
        st.subheader("Upload a Document")
        uploaded_file = st.file_uploader(
            "Choose a PDF or TXT file",
            type=["pdf", "txt"]
        )

        if uploaded_file:
            if st.button("Upload", use_container_width=True):
                with st.spinner("Uploading..."):
                    error = upload_document(uploaded_file)
                if error:
                    st.error(error)
                else:
                    st.success("Uploaded! Processing will begin shortly.")
                    time.sleep(1)
                    st.rerun()

        st.divider()

        # Documents list
        st.subheader("Your Documents")
        with st.spinner("Loading..."):
            documents = get_documents()

        if not documents:
            st.info("No documents yet. Upload one above to get started.")
        else:
            for doc in documents:
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.write(f"📄 **{doc['filename']}**")
                    st.caption(f"Uploaded: {doc['uploaded_at'][:19]}")
                with col2:
                    status = doc["status"]
                    if status == "ready":
                        st.success("Ready")
                    elif status == "processing":
                        st.warning("Processing")
                    else:
                        st.error("Failed")
                st.divider()

    # ── History Page ───────────────────────────────────────────────
    elif page == "🕓 History":
        st.title("🕓 Chat History")

        with st.spinner("Loading sessions..."):
            sessions = get_history()

        if not sessions:
            st.info("No chat sessions yet. Start a conversation in the Chat page.")
        else:
            for session in sessions:
                with st.expander(f"💬 {session['title'] or 'Untitled'} — {session['created_at'][:19]}"):
                    st.write(f"Session ID: `{session['id']}`")
                    if st.button("Continue this chat", key=session["id"]):
                        st.session_state.session_id = session["id"]
                        st.session_state.messages = []
                        st.switch_page("💬 Chat")