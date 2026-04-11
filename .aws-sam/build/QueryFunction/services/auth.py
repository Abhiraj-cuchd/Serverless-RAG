import logging
from datetime import datetime, timedelta
from jose import JWTError, jwt
from passlib.context import CryptContext
import psycopg2

logger = logging.getLogger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def get_connection(db_url: str):
    """Create and return a PostgreSQL connection."""
    return psycopg2.connect(db_url)


# ── Password Helpers ───────────────────────────────────────────────


def hash_password(plain_password: str) -> str:
    """Hash a plain text password using bcrypt."""
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Check if a plain password matches the stored hash."""
    return pwd_context.verify(plain_password, hashed_password)


# ── JWT Helpers ────────────────────────────────────────────────────


def create_jwt_token(user_id: str, secret_key: str, algorithm: str, expiry_minutes: int) -> str:
    """
    Create a signed JWT token containing the user_id.
    Token expires after the given number of minutes.
    """
    expiry = datetime.utcnow() + timedelta(minutes=expiry_minutes)
    payload = {"sub": user_id, "exp": expiry}
    token = jwt.encode(payload, secret_key, algorithm=algorithm)
    logger.info(f"Created JWT token for user {user_id}")
    return token


def decode_jwt_token(token: str, secret_key: str, algorithm: str) -> str:
    """
    Decode and verify a JWT token.
    Returns the user_id if valid, raises an error if expired or tampered.
    """
    try:
        payload = jwt.decode(token, secret_key, algorithms=[algorithm])
        user_id = payload.get("sub")
        if user_id is None:
            raise ValueError("Token is missing user identity.")
        return user_id
    except JWTError as e:
        raise ValueError(f"Invalid or expired token: {e}")


# ── Database Operations ────────────────────────────────────────────


def create_user(db_url: str, email: str, plain_password: str) -> dict:
    """
    Register a new user in the database.
    Returns the created user's id and email.
    Raises an error if the email is already registered.
    """
    try:
        conn = get_connection(db_url)
        cursor = conn.cursor()

        hashed = hash_password(plain_password)

        cursor.execute(
            """
            INSERT INTO users (email, hashed_password)
            VALUES (%s, %s)
            RETURNING id, email, created_at
            """,
            (email, hashed)
        )

        row = cursor.fetchone()
        conn.commit()
        cursor.close()
        conn.close()

        logger.info(f"Created new user: {email}")
        return {"id": str(row[0]), "email": row[1], "created_at": str(row[2])}

    except psycopg2.errors.UniqueViolation:
        raise ValueError(f"Email '{email}' is already registered.")
    except Exception as e:
        raise RuntimeError(f"Failed to create user: {e}")


def get_user_by_email(db_url: str, email: str) -> dict | None:
    """
    Fetch a user record by email.
    Returns user dict if found, None if not found.
    """
    try:
        conn = get_connection(db_url)
        cursor = conn.cursor()

        cursor.execute(
            "SELECT id, email, hashed_password FROM users WHERE email = %s",
            (email,)
        )

        row = cursor.fetchone()
        cursor.close()
        conn.close()

        if row is None:
            return None

        return {"id": str(row[0]), "email": row[1], "hashed_password": row[2]}

    except Exception as e:
        raise RuntimeError(f"Failed to fetch user: {e}")


def login_user(
    db_url: str,
    email: str,
    plain_password: str,
    secret_key: str,
    algorithm: str,
    expiry_minutes: int
) -> str:
    """
    Verify credentials and return a JWT token if valid.
    Raises ValueError if email not found or password is wrong.
    """
    user = get_user_by_email(db_url, email)

    if user is None:
        raise ValueError("No account found with this email.")

    if not verify_password(plain_password, user["hashed_password"]):
        raise ValueError("Incorrect password.")

    token = create_jwt_token(user["id"], secret_key, algorithm, expiry_minutes)
    logger.info(f"User logged in: {email}")
    return token