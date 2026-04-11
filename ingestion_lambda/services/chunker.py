import logging

logger = logging.getLogger(__name__)

CHUNK_SIZE = 512    # number of words per chunk
CHUNK_OVERLAP = 50  # number of words repeated between chunks


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """
    Split a large text into overlapping chunks of words.
    Overlap preserves context at the boundary between chunks.
    """
    if not text.strip():
        raise ValueError("Cannot chunk empty text.")

    words = text.split()
    chunks = []
    start = 0

    while start < len(words):
        end = start + chunk_size
        chunk = " ".join(words[start:end])
        chunks.append(chunk)
        start += chunk_size - overlap

    logger.info(f"Split text into {len(chunks)} chunks (size={chunk_size}, overlap={overlap})")
    return chunks