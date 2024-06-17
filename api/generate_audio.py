from flask import request, jsonify
from utils import createAudio

def handler(request):
    uid = request.form['uid']
    text = request.form['text']
    audio_url = createAudio(text, uid)
    return jsonify(audio_url=audio_url), 200
