from flask import request, jsonify
from utils import createFlashcards

def handler(request):
    transcript = request.form.get('transcript')
    flashcards = createFlashcards(transcript)
    return jsonify(flashcards=flashcards)
