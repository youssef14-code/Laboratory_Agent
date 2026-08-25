"""
utils.py
Shared helper functions for the Knowledge Pipeline.
"""

import os
import re
import unicodedata
import warnings
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# ---------------------------------------------------------------------------
# Database engine (main app database only — vectors are handled via FAISS files)
# ---------------------------------------------------------------------------
MAIN_DATABASE_URL = os.environ.get("MAIN_DATABASE_URL") or os.environ.get("SQLALCHEMY_DATABASE_URI")
if not MAIN_DATABASE_URL:
    raise RuntimeError(
        "MAIN_DATABASE_URL environment variable is not set. "
        "مثال MySQL: MAIN_DATABASE_URL=mysql+pymysql://user:pass@localhost:3306/dbname\n"
        "مثال SQLite: MAIN_DATABASE_URL=sqlite:///path/to/your.db"
    )

if MAIN_DATABASE_URL.startswith("mysql://"):
    MAIN_DATABASE_URL = MAIN_DATABASE_URL.replace("mysql://", "mysql+pymysql://", 1)

main_engine = create_engine(MAIN_DATABASE_URL, pool_pre_ping=True, future=True)
MainSession = sessionmaker(bind=main_engine, future=True)


def _in_flask_context() -> bool:
    try:
        from flask import current_app
        # current_app هو proxy بيرمي RuntimeError لو مفيش app context شغال
        return bool(current_app)
    except Exception:
        return False


@contextmanager
def main_session():
    """Yields a session بتعمل commit في الآخر سواء جوه Flask app context أو standalone script."""
    if _in_flask_context():
        from models.models import db
        try:
            yield db.session
            db.session.commit()   # <-- الإصلاح: كان بيرجع من غير commit خالص
        except Exception:
            db.session.rollback()
            raise
        return

    session = MainSession()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Text normalization (used by duplicate_checker.py)
# ---------------------------------------------------------------------------
def normalize_text(text: str) -> str:
    """Lowercases, strips accents/punctuation, and collapses whitespace."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"[إأآا]", "ا", text)
    text = re.sub(r"ى", "ي", text)
    text = re.sub(r"ة", "ه", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ---------------------------------------------------------------------------
# Gemini client helper
# ---------------------------------------------------------------------------
def get_gemini_client():
    """
    Returns a configured google.genai Client or legacy genai module.
    """
    api_key = os.environ.get("GEMINI_API_KEY", "")
    try:
        from google import genai
        if api_key:
            return genai.Client(api_key=api_key)
        return genai.Client()
    except Exception:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            return genai
