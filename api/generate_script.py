from flask import request, jsonify, Flask
from flask_cors import CORS
from utils import createScript
import tempfile

app = Flask(__name__)
CORS(app)

@app.route('/generate_script', methods=['POST', 'GET'])
def handler(request):
    prompt_text = request.form['prompt']
    language  = request.form.get('language')
    strNumImages = request.form['imageCount']
    numImages = int(strNumImages)
    script_text = request.form.get('script')
    uid = request.form.get('uid')
    pdfText = None

    if 'pdf' in request.files:
        pdf_file = request.files['pdf']
        pdf_file_path = f"user_pdf_{uid}.pdf"
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_pdf:
            pdf_file.save(temp_pdf.name)
            pdfText = extract_text(temp_pdf.name)

    if script_text:
        generated_text = createScript(script_text + f" Split the story into {numImages} parts like so: Part 1: text  Part 2: text and so on. Do NOT change anything else about the text at ALL. DO NOT make the part markers in headings just leave them as plain text", True)
    else:
        if language:
            language_text = f'Make the script in {language}. However, make sure to leave the Part markers in english'
        else:
            language_text = ''
        if pdfText:
            generated_text = createScript(prompt_text + f"Split the story into {numImages} parts like so: Part 1: text  Part 2: text and so on. DO NOT make the part markers in headings just leave them as plain text. Make sure to keep fairly short. Reading it should take 1 - 2 minutes. {language_text} Also, make sure to use this information: {pdfText}", False)
        else:
            generated_text = createScript(prompt_text + f"Split the story into {numImages} parts like so: Part 1: text  Part 2: text and so on. DO NOT make the part markers in headings just leave them as plain text. Make sure to keep fairly short. Reading it should take 1 - 2 minutes. {language_text}", False)

    return jsonify(generated_text=generated_text)
