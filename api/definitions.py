from flask import request, jsonify
from utils import createDefinitions

def handler(request):
    transcript = request.form.get('transcript')
    definitions = createDefinitions(transcript)
    return jsonify(definitions=definitions)