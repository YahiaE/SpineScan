"""
Lazy loader for heavy dependencies to reduce cold-start time.
Modules are imported on first use, not at application startup.
"""

import logging


logger = logging.getLogger(__name__)

_loaded_modules = {}


def get_gemini_client():
    """
    Lazily load and return the Google Gemini client.
    Gemini client initialization can be expensive; defer until first use.
    """
    if "gemini_client" not in _loaded_modules:
        try:
            from google import genai
            import os
            from dotenv import load_dotenv

            load_dotenv()
            client = genai.Client()
            client.api_key = os.getenv("GEMINI_API_KEY")
            _loaded_modules["gemini_client"] = client
            logger.info("Gemini client lazily loaded")
        except Exception as error:
            logger.error(f"Failed to load Gemini client: {error}", exc_info=True)
            raise

    return _loaded_modules["gemini_client"]


def get_discogs_client_class():
    """
    Lazily load and return the Discogs client class.
    discogs_client library can be heavy; defer import until first use.
    """
    if "discogs_client_class" not in _loaded_modules:
        try:
            import discogs_client

            _loaded_modules["discogs_client_class"] = discogs_client
            _loaded_modules["discogs_client_Client"] = discogs_client.Client
            logger.info("Discogs client library lazily loaded")
        except Exception as error:
            logger.error(f"Failed to load Discogs client: {error}", exc_info=True)
            raise

    return _loaded_modules["discogs_client_class"]


def get_discogs_Client():
    """
    Lazily load and return the Discogs Client class directly.
    Used for isinstance checks.
    """
    if "discogs_client_Client" not in _loaded_modules:
        get_discogs_client_class()  # Ensure module is loaded

    return _loaded_modules["discogs_client_Client"]


def get_ocr_process_image_main():
    """
    Lazily load and return the OCR process_image main function.
    OCR initialization can be expensive; defer until first use.
    """
    if "ocr_process_image_main" not in _loaded_modules:
        try:
            from ocr_functions.process_image import main

            _loaded_modules["ocr_process_image_main"] = main
            logger.info("OCR process_image function lazily loaded")
        except Exception as error:
            logger.error(f"Failed to load OCR process_image: {error}", exc_info=True)
            raise

    return _loaded_modules["ocr_process_image_main"]


def clear_cache():
    """Clear the lazy-loaded module cache. Useful for testing."""
    global _loaded_modules
    _loaded_modules.clear()
    logger.info("Lazy loader cache cleared")
