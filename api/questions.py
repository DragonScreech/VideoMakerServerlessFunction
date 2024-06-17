from flask import request, jsonify
from utils import createQuestions

def handler(request):
    transcript = request.form.get('transcript')
    questions = createQuestions(transcript)
    return jsonify(questions=questions)
