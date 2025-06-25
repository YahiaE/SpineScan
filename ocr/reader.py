import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from PIL import Image
from surya.recognition import RecognitionPredictor
from surya.detection import DetectionPredictor
import subprocess
import json
import os
from openai import OpenAI
from dotenv import load_dotenv

def main():
    url = r"D:\Projects\SpineScan\data\test2.jpg"
    music_res = ocr(url)
    print(music_res)
    
    prompt_template = """
You are given a list of mixed data including artist names, album/single titles, record labels, and catalog numbers.

Your task is to extract only valid artist name and album/single title pairs.

Rules:

Ignore catalog numbers (e.g., codes like "ESCL 3259", "JKCA-1043")
Ignore record label names (e.g., "EPIC RECORDS", "JULY RECORDS")
Any metadata that is may not seem like an artist name or a title, use your internal knowledge and understanding of patterns to classify each line as artist, title (album or single), label, or catalog number. Use context
When an album or single title appears on its own, pair it with the most recently mentioned artist

Format the output like this:

Artist Name: Album Title
Artist Name: Album Title

No extra text. No duplicates. One line per pair.

Input:
{list_input}
"""


    
    # prompt = prompt_template.format(list_input=music_res)

    # print(prompt)

    # result = generateList(prompt)
   

    # print(result)

def generateList(prompt):
    load_dotenv()
    client = OpenAI()
    OpenAI.api_key = os.getenv("OPENAI_API_KEY")
    response = client.responses.create(
    model="gpt-4.1-nano",
    input=prompt
    )

    return response



def ocr(url):
    music = []
    filename = url[url.rfind("\\") + 1 : url.rfind(".")]
    output_dir = os.path.join("D:\\", "Projects", "SpineScan", "output", filename)
    subprocess.run(["surya_ocr", url, "--output_dir", r"D:\Projects\SpineScan\output"], shell=True)
    file = f"{output_dir}\\results.json"
    with open(file, 'r', encoding='utf-8') as f:
        data = json.load(f)
        text_lines = data[filename][0]['text_lines']
        for line in text_lines:
            music.append(line['text'])
    
    return "\n".join(music)


if __name__ == "__main__":
    main()




