from flask import request, jsonify
from utils import createImages, download_image, upload_to_firebase
import tempfile

def handler(request):
    imageSize = request.form.get('imageSize')
    text = request.form.get('text')
    uid = request.form.get('uid')
    image_urls = []

    if 'images' in request.files:
        image_files = request.files.getlist('images')
        for index, image in enumerate(image_files):
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as temp_img:
                image.save(temp_img.name)
                firebase_url = upload_to_firebase(temp_img.name, f"image_{index}_{uid}.png", folder='temp')
                image_urls.append(firebase_url)
    
    if not 'images' in request.files:
        if imageSize:
            generated_image_urls = createImages(text, imageSize)
            for index, image_url in enumerate(generated_image_urls):
                with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as temp_img:
                    download_image(image_url, temp_img.name)
                    firebase_url = upload_to_firebase(temp_img.name, f"image_{index}_{uid}.png", folder='temp')
                    image_urls.append(firebase_url)

    return jsonify(image_urls=image_urls), 200

