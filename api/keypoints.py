from flask import request, jsonify
from utils import createKeyPoints

def handler(request):
    transcript = request.form.get('transcript')
    keypoints = createKeyPoints(transcript)
    return jsonify(keypoints=keypoints)
