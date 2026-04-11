import logging
import fitz

logger =  logging.getLogger(__name__)


def extract_text_from_pdf(file_path: str) -> str:
    """Extract all text from a PDF file and return it as a single string"""
    try:
        document = fitz.open(file_path)
        pages_text = [page.get_text() for page in document]
        full_text = "\n".join(pages_text)
        logger.info(f"Extracted text from PDF: {file_path} ({len(pages_text)} pages)")
        return full_text
    
    except Exception as e:
        raise RuntimeError(f"Failed to extract text from PDF: {file_path}: {e}")
    
def extract_text_from_txt(file_path: str) -> str:
    """Extract all text from a plain TXT file and return it as a string."""
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
        logger.info(f"Extracted text from TXT: {file_path}")
        return text

    except Exception as e:
        raise RuntimeError(f"Failed to extract text from TXT {file_path}: {e}")

def extract_text(file_path: str) -> str:
    """
    Detect file type and extract text accordingly.
    Supports PDF and TXT. Raises ValueError for unsupported types.
    """
    if file_path.endswith(".pdf"):
        return extract_text_from_pdf(file_path)
    elif file_path.endswith(".txt"):
        return extract_text_from_txt(file_path)
    else:
        raise ValueError(f"Unsupported file type: {file_path}. Only PDF and TXT are supported.")