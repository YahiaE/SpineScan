import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from PIL import Image
import subprocess
import json
import os
from openai import OpenAI
from dotenv import load_dotenv
load_dotenv()
from azure.cognitiveservices.vision.computervision import ComputerVisionClient
from azure.cognitiveservices.vision.computervision.models import OperationStatusCodes
from azure.cognitiveservices.vision.computervision.models import VisualFeatureTypes
from msrest.authentication import CognitiveServicesCredentials
from array import array
import os
from PIL import Image
import sys
import time


def main():
    url = r"D:\Projects\SpineScan\data\test2.jpg"
    ocr_data = ocr(url)
    music_res = group_text_by_rows(ocr_data, threshold=35)
    print(music_res)
    prompt_template = """
Objective
Process raw OCR text lines from CD spines and covers to produce accurate, standardized "Artist - Album" format. The process should handle data cleaning, fuzzy error correction, disambiguation, and verification against a trusted music database, applicable to any artist or album.

Workflow Steps

Data Cleaning

Remove catalog numbers, label names, and non-essential text.

Discard lines that contain only identifiers or non-informative content.

Extraction

Parse remaining lines to extract possible artist and album names.

If only one name is confidently extracted, assign "Self-Titled" as the album.

Fuzzy Correction & Disambiguation

Use fuzzy string matching to correct OCR errors in artist and album names.

Cross-reference with trusted music databases (e.g., Last.fm, MusicBrainz, Discogs).

For each candidate name:

Find the closest artist and album matches in the database using ≥85% similarity threshold.

Prioritize matches where:

Album name is exact, and artist name is similar in spelling or phonetics (e.g., "Kutt" ≈ "Kurt").

Or vice versa — if the artist name is exact, but album name is fuzzy-match to a known album by that artist.

If multiple potential matches exist:

Select the pairing with the highest overall confidence (combined artist and album similarity).

Use artist discography or known album pairings to resolve ambiguity.

Validation Against Music Database

Confirm that the "Artist - Album" pairing exists as a valid combination.

If only one (artist or album) exists independently:

Infer the most likely matching pair using artist discographies or popular album data.

Use contextual logic: for instance, if album title is known and unique, prioritize artists with similar spelling.

Final Output

Output only verified "Artist - Album" results.

Include uncertain entries only if the pairing is verified across multiple databases or the most likely combination is well-supported (e.g., popular on Last.fm).

ONLY OUTPUT THE FINAL RESULT IN THE FOLLOWING FORMAT:
Artist - Album
...

Do not include any intermediate logs, scores, or metadata — just the final cleaned and verified list.


Input:
{list_input}
"""
    
    prompt = prompt_template.format(list_input=music_res)
    result = generateList(prompt)
    print(result.output[0].content[0].text)

def group_text_by_rows(ocr_results, threshold=35):
    rows = []

    for result in ocr_results:
        text = result["text"]
        bounding_box = result["bounding_box"]
        avg_y = sum(bounding_box[1::2]) / 4  # Calculate the average vertical position of the bounding box

        # Check if the text belongs to an existing row
        for row in rows:
            if abs(avg_y - row["avg_y"]) <= threshold:  # Compare vertical position with existing rows
                row["texts"].append(text)
                row["avg_y"] = (row["avg_y"] * len(row["texts"]) + avg_y) / (len(row["texts"]) + 1)  # Update average y
                break
        else:
            # Create a new row if no existing row matches
            rows.append({"texts": [text], "avg_y": avg_y})

    # Convert rows into a single formatted string
    result = "\n".join([", ".join(row["texts"]) for row in rows])
    return result

def generateList(prompt):
    load_dotenv()
    client = OpenAI()
    OpenAI.api_key = os.getenv("OPENAI_API_KEY")
    response = client.responses.create(
    model="gpt-4.1",
    input=prompt
    )

    return response



def ocr(url, timeout=60):
    """
    Perform OCR on the given image URL with a timeout mechanism.

    Args:
        url (str): Path to the image file.
        timeout (int): Maximum time (in seconds) to wait for the OCR operation to complete.

    Returns:
        list: OCR results containing text and bounding boxes.

    Raises:
        TimeoutError: If the OCR operation exceeds the timeout limit.
        Exception: If the OCR operation fails.
    """
    results = []
    subscription_key = os.getenv("VISION_KEY")
    endpoint = os.getenv("VISION_ENDPOINT")
    
    if not subscription_key or not endpoint:
        raise ValueError("VISION_KEY or VISION_ENDPOINT is not set in the environment variables.")
    
    if not os.path.exists(url):
        raise FileNotFoundError(f"Image file not found: {url}")
    
    computervision_client = ComputerVisionClient(endpoint, CognitiveServicesCredentials(subscription_key))
    
    with open(url, "rb") as image_stream:
        read_response = computervision_client.read_in_stream(image_stream, raw=True)

    read_operation_location = read_response.headers["Operation-Location"]
    operation_id = read_operation_location.split("/")[-1]

    start_time = time.time()  # Record the start time

    while True:
        read_result = computervision_client.get_read_result(operation_id)
        if read_result.status not in ['notStarted', 'running']:
            break
        if time.time() - start_time > timeout:  # Check if the timeout limit is exceeded
            raise TimeoutError("OCR operation timed out.")
        time.sleep(1)  # Wait for 1 second before checking again

    if read_result.status == OperationStatusCodes.succeeded:
        for text_result in read_result.analyze_result.read_results:
            for line in text_result.lines:
                results.append({
                    "text": line.text,
                    "bounding_box": line.bounding_box
                })
    else:
        raise Exception(f"OCR operation failed with status: {read_result.status}")
    
    return results


if __name__ == "__main__":
    main()




