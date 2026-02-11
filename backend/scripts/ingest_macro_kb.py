"""
Ingest macro KB: discover PDFs at MACRO_KB_PDF_PATH, extract, chunk, embed, save to macro_kb_books + macro_kb_chunks.

Usage:
  python -m backend.scripts.ingest_macro_kb
  python -m backend.scripts.ingest_macro_kb --path /path/to/MacroEcon

Set MACRO_KB_PDF_PATH in .env or pass --path. Run once or on-demand when new PDFs are added.
"""
import argparse
import logging
import os
import sys

# Ensure project root is on path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from backend.macro.kb_ingest import run_ingest_sync

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest macro PDFs into macro_kb_books and macro_kb_chunks")
    parser.add_argument("--path", type=str, default=None, help="Path to PDF folder or file (default: MACRO_KB_PDF_PATH)")
    args = parser.parse_args()
    result = run_ingest_sync(path=args.path)
    logger.info("Ingest result: %s", result)
    if result.get("books", 0) == 0 and result.get("paths"):
        sys.exit(1)
    if not result.get("paths"):
        logger.warning("No PDFs found at path; check MACRO_KB_PDF_PATH or --path")


if __name__ == "__main__":
    main()
