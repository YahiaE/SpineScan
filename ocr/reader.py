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
    music_res = ocr(url)
    print(music_res)
    
    prompt1_template = """
Task:
Extract and verify only valid artist names from noisy OCR-scanned text. Ignore album titles, catalog numbers, or label names.

Output:
Only output confirmed, valid artist names, one per line, in title case (e.g., Mary J. Blige). No duplicates.

Instructions and Constraints:

1. Immediate Discard Rules:
• Discard any lines that contain only catalog numbers (e.g., ESCL 3259, JKCA-1030, XQCY1041, 82796 90920 2).
• Discard lines containing record label keywords: RECORDS, LABEL, MUSIC GROUP, etc.
• Discard known label names: EPIC, JULY, SONY, RCA, COLUMBIA, VIRGIN, etc.
• Discard lines that contain only uppercase letters and digits with no lowercase.
• Remove anything inside brackets [ ] or parentheses ( ).
• Remove format tags: LP, CD, Reissue, Ltd., Remastered.

2. OCR Correction:
• Apply fuzzy matching or minor spelling correction (1–2 letter changes) to fix common OCR errors in names.
• Only correct if the result matches a real artist in trusted databases.

3. Verification:
• Confirm each artist name using trusted sources (Discogs, AllMusic, MusicBrainz, RateYourMusic, or official artist websites).
• Discard any names that cannot be verified as real musical artists.
• Do not guess or infer — only output if verified as an artist.

4. Output Formatting:
• One artist per line.
• Use title case (capitalize major words).
• No duplicates.
• No album names, catalog info, or additional text.
• No explanations or extra commentary — just valid artist names.

SUMMARY:
- Only extract valid artist names.
- Do not output unless verified against real-world music databases.
- Discard everything else.

Input:
{list_input}
"""
    
    prompt1 = prompt1_template.format(list_input=music_res)
    result1 = generateList(prompt1)

    prompt2_template = """
Task:
Using a provided list of valid artist names, scan the OCR-scanned lines again to extract and verify real album titles associated with those artists.

Only output confirmed artist/album pairs in the format:
Artist Name: Album Title

Instructions and Constraints:

Input Reference:
• Use the provided list of verified artist names.
• Assume these are the only valid artists.
• Discard all data that does not relate to one of these artists.

Matching Album Titles:
• If a line contains one of the valid artist names followed by other words, treat the remaining words as a possible album title.
• If the artist name appears on one line and the next line appears to be a title (contains lowercase or mixed case), associate it using the artist as context.
• If a line uses separators like slash, dash, or colon, split and match the artist to the corresponding title.

Fuzzy Correction (only if needed):
• Fix common OCR errors in album names, such as misspellings or punctuation mistakes, only if the corrected artist-album pair is verified in trusted databases.

Strict Verification:
• Check that each artist and album pair exists as a real release in trusted sources such as Discogs, MusicBrainz, AllMusic, RateYourMusic, or official artist sites.
• Discard any unverified pairings; do not guess or substitute.
• Do not assume a generic or random album title belongs to an artist unless confirmed.

Formatting:
• Output artist name, colon, album title (Artist Name: Album Title).
• Use title case for both artist and album.
• One verified pair per line.
• No duplicates, no commentary, no album-only lines.

Summary:

Use only previously verified artists.

Only output artist and album pairs that exist as real, published releases.

Do not hallucinate or guess. If not confirmed, discard.


Input Of Artists:
{list_input}

Original Data:
{data}
"""
    prompt2 = prompt2_template.format(list_input=result1.output[0].content[0].text, data=music_res)
    result2 = generateList(prompt2)
   
    print(result2.output[0].content[0].text)

def generateList(prompt):
    load_dotenv()
    client = OpenAI()
    OpenAI.api_key = os.getenv("OPENAI_API_KEY")
    response = client.responses.create(
    model="gpt-4.1",
    input=prompt
    )

    return response



def ocr(url):
    results = []
    subscription_key = os.getenv("VISION_KEY")
    endpoint = os.getenv("VISION_ENDPOINT")
    computervision_client = ComputerVisionClient(endpoint, CognitiveServicesCredentials(subscription_key))
    
    with open(url, "rb") as image_stream: # Using in_stream due to using local file
        read_response = computervision_client.read_in_stream(image_stream, raw=True)

    read_operation_location = read_response.headers["Operation-Location"] # URL to check the results of reading the image
    operation_id = read_operation_location.split("/")[-1] # ID apart of the URL, passed into a function to check the status and output of our results

    while True:

        read_result = computervision_client.get_read_result(operation_id) # Check if the azure OCR service has gotten the results from the ID
        if read_result.status not in ['notStarted', 'running']: # If the status is completed (not in progress), exit the loop
            break
        time.sleep(1) # Wait for 1 second before checking again

    if read_result.status == OperationStatusCodes.succeeded: # If the status of getting the results is complete 
        for text_result in read_result.analyze_result.read_results: 
            for line in text_result.lines: # Read and print through each line of the results
                results.append(line.text)
    
    return "\n".join(results)


    








    
    # with open(file, 'r', encoding='utf-8') as f:
    #     data = json.load(f)
    #     text_lines = data[filename][0]['text_lines']
    #     for line in text_lines:
    #         music.append(line['text'])
    
    # return "\n".join(music)


if __name__ == "__main__":
    main()




