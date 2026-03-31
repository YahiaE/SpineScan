from google import genai
from google.genai import types
import os
from dotenv import load_dotenv

load_dotenv()


def main(url):

    with open(url, "rb") as f:
        image_bytes = f.read()
    client = genai.Client()
    client.api_key = os.getenv("GEMINI_API_KEY")
    prompt = """
Task
Extract text from CD spine images and output standardized "Artist - Album" entries.

Workflow

OCR Extraction
Read text from CD spine image.

Cleaning
**1. Initial Filtering (Labels, Catalog Numbers, Noise):**
   *   **Aggressively remove all identified catalog numbers.** These are sequences that resemble codes like "CD-XXXX", "88697 XXXXXX", etc.
   *   **Aggressively remove all identified record label names.** This includes common labels like "July Records", "Epic", "Columbia", "BMG", "Universal Music Group", etc., and any associated branding text.
   *   Remove generic non-essential text (e.g., "Manufactured in...", "Printed in...", "All rights reserved...").
   *   Drop lines that consist solely of noise, empty strings, or identified catalog numbers/labels after the initial filtering.

**2. Structured String Analysis for Prefix Patterns:**
   *   **Analyze the remaining text on each line for the following pattern:** `[INITIAL_TEXT] - [POTENTIAL_ARTIST_NAME] / [POTENTIAL_ALBUM_NAME]`
   *   **If this pattern is detected:**
       *   **Examine `[INITIAL_TEXT]`:** Is it a recognized musical artist name? If YES, then this might be a split release or similar; proceed to Artist Verification. **If NO, and `[INITIAL_TEXT]` appears to be a compilation title, project name, or generic descriptive phrase (e.g., "Fiveman Army Rocks"), treat it as a discardable prefix.**
       *   **Examine `[POTENTIAL_ARTIST_NAME]`:** This entity is now the primary candidate for the ARTIST.
       *   **Examine `[POTENTIAL_ALBUM_NAME]`:** This entity is now the primary candidate for the ALBUM.

**3. Artist and Album Verification (Mandatory):**
   *   **For the `[POTENTIAL_ARTIST_NAME]` identified in step 2:**
       *   **Cross-reference this `[POTENTIAL_ARTIST_NAME]` with music databases (MusicBrainz, Discogs, Last.fm).**
       *   **If `[POTENTIAL_ARTIST_NAME]` IS a recognized musical artist:**
           *   **Assign `[POTENTIAL_ARTIST_NAME]` as the ARTIST.**
           *   **Assign `[POTENTIAL_ALBUM_NAME]` as the ALBUM.**
           *   **Crucially, discard `[INITIAL_TEXT]` if it was identified as a discardable prefix in step 2.**
       *   **If `[POTENTIAL_ARTIST_NAME]` is NOT a recognized musical artist:**
           *   This specific line's parsing using the `[PREFIX_ENTITY] - [ARTIST_NAME] / [ALBUM_NAME]` structure is deemed invalid. The system must then attempt to parse the line using alternative methods, or treat it as unprocessable if no recognized artist can be found.

**4. Standard Parsing (If Prefix Pattern Not Met or Invalid):**
   *   If the prefix pattern from step 2 was not detected, or if the identified `[POTENTIAL_ARTIST_NAME]` failed verification, parse the remaining clean text using standard rules (identify Artist, then Album).
   *   The absolute priority is to identify a recognized musical artist name.

Fuzzy Matching & Disambiguation
Correct OCR errors using fuzzy matching (≥85%).
Cross-check with music databases (MusicBrainz, Discogs, Last.fm).
**The fuzzy matching process must ensure that the final ARTIST assignment is to a recognized musical artist. If an initially parsed entity is not a recognized artist, it must be discarded, and the system must attempt to find a recognized artist within the remaining text.**
Prioritize matches based on:
Exact album + fuzzy artist
Exact artist + fuzzy album
If multiple matches arise, choose the one with the highest combined similarity score.
Use known artist–album pairings from databases to resolve ambiguity.

Validation
Confirm the artist–album pair exists in a music database.
If a partial match is found, infer the complete pairing using discography information or popularity rankings.

Output
Return only verified results:

Artist - Album
Artist - Album
...

No explanations, scores, or metadata.

"""

    response = client.models.generate_content(
        model="gemini-2.5-flash-lite",
        contents=[
            types.Part.from_bytes(
                data=image_bytes,
                mime_type="image/jpeg",
            ),
            prompt,
        ],
    )

    return response.text
