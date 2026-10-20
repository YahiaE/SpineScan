import os
from dotenv import load_dotenv
from google.genai import types
from pydantic import BaseModel
from services.lazy_loader import get_gemini_client

load_dotenv()


# Define Pydantic schema for fast, structured JSON output
class AlbumEntry(BaseModel):
    artist: str
    album: str


class SpineScanResult(BaseModel):
    items: list[AlbumEntry]


def main(url):
    with open(url, "rb") as f:
        image_bytes = f.read()

    client = get_gemini_client()

    prompt = """
Extract artist and album titles from CD spine images or CD front cover images.

Guidelines:
1. **Visual & Conceptual Identification:** If text is absent, obscured, handwritten, or embedded in abstract/found-object photography, perform visual matching. Analyze cover artwork, distinctive typography, band logos, and iconic imagery just like a reverse-image search to identify the album and artist.
2. Strip out catalog numbers, record labels, and legal boilerplate.
3. Ignore generic text or promotional taglines unless part of the primary artist or album name.
4. Clean up minor OCR defects and standard capitalization.
5. Handle multiple items in a single image or batch, and output each distinct album found.

Output format:
Artist - Album
Artist - Album
...

No explanations, scores, or metadata.
"""

    # Configure Gemini for lowest possible latency
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=SpineScanResult,
        # Disable automatic function calling overhead
        tools=[],
        temperature=0.1,  # Low temperature for deterministic speed
    )

    response = client.models.generate_content(
        model="gemini-2.5-flash-lite",
        contents=[
            types.Part.from_bytes(
                data=image_bytes,
                mime_type="image/jpeg",
            ),
            prompt,
        ],
        config=config,
    )

    # Parse structured JSON result directly
    try:
        parsed: SpineScanResult = response.parsed
        if not parsed or not parsed.items:
            return ""

        formatted_lines = [
            f"{item.artist} - {item.album}"
            for item in parsed.items
            if item.artist and item.album
        ]
        return "\n".join(formatted_lines)
    except Exception:
        # Fallback if raw text parsing is needed
        return response.text or ""