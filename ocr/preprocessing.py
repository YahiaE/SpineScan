import cv2
import os
from PIL import Image

def preprocess_image(image_path, output_path="preprocessed_image.jpg"):

    image = cv2.imread(image_path, cv2.IMREAD_COLOR)

    # grayscale
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # gaussian blur to reduce noise
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)

    # morphological operations
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    cleaned = cv2.morphologyEx(blurred, cv2.MORPH_CLOSE, kernel)

    # resize the image to a fixed size if it is too large
    height, width = cleaned.shape
    if max(height, width) > 1600:
        scale_factor = 1600 / max(height, width)
        cleaned = cv2.resize(cleaned, (int(width * scale_factor), int(height * scale_factor)))

    # save the preprocessed image
    cv2.imwrite(output_path, cleaned)

    # return its abs path
    return os.path.abspath(output_path)