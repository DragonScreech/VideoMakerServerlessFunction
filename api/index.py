from openai import OpenAI
import re
from moviepy.editor import ImageClip, concatenate_videoclips, AudioFileClip, CompositeVideoClip, TextClip, VideoFileClip, ColorClip, ImageSequenceClip
import os
import requests
import textwrap
from flask import Flask, request, send_file, jsonify
from flask_cors import CORS
import tempfile
from dotenv import load_dotenv
from pdfminer.high_level import extract_text
import time
import firebase_admin
from firebase_admin import credentials, storage
load_dotenv()

app = Flask(__name__)
CORS(app)

client = OpenAI(api_key=os.getenv('OPEN_AI_API_KEY'))


def createScript(prompt, textReplaced):
  if not textReplaced:
    rewrittenPrompt = client.chat.completions.create(
      model="gpt-4-turbo",
      messages=[{
        "role": 'user',
        "content": """Rewrite the following prompt in a way that reads 'tell me about ___" rather than make a video about ___

  Ex: Make a video about bees. Split the story into 5 parts like so: Part 1: text  Part 2: text and so on. DO NOT make the part markers in headings just leave them as plain text. Make sure to keep fairly short. Reading it should take 1 - 2 minutes.  -> Tell me about bees. Split the story into 5 parts like so: Part 1: text  Part 2: text and so on. DO NOT make the part markers in headings just leave them as plain text. Make sure to keep fairly short. Reading it should take 1 - 2 minutes.

  Make sure to only change the first sentence. It is crucial that you do not change the other sentences describing the formatting. Also, even if it says to make the script in another lanuage, leave this rewritten prompt in english

  Here is the text: """ + prompt
      }]
    )

    promptText = rewrittenPrompt.choices[0].message.content
    print(promptText)
  else:
    promptText = prompt

  response = client.chat.completions.create(
      model="gpt-4-turbo",
      messages=[{
         "role": 'system',
         "content": 'You are an ai assisant that users depend on to make video scripts. However, when people say to make a video, just ignore that and move on like they just asked you to tell them about something. DO NOT include any headings and leave the entire thing as plain text.'
      }, {
          "role": 'user',
          "content": promptText
      },],
      max_tokens=500,
  )
  print(response.choices[0].message.content)
  return response.choices[0].message.content


def createAudio(text, uid):
  speech_file_path = f"speech_{uid}.mp3"
  cleaned_text = re.sub(r'Part \d+:', '', text)
  response = client.audio.speech.create(model="tts-1",
                                        voice="alloy",
                                        input=cleaned_text)

  response.stream_to_file(speech_file_path)


def createImages(textPrompt, imageSize, retries=3, delay=2):
    images = []
    parts = re.split(r'Part \d+:', textPrompt)

    # Remove the first element if it's empty (which happens if the text starts with "Part 1:")
    if parts[0] == '':
        parts.pop(0)

    # Strip leading and trailing whitespace from each part
    parts = [part.strip() for part in parts]
    print(parts)
    for x in range(len(parts)):
        attempt = 0
        while attempt < retries:
            try:
                response = client.images.generate(
                    model="dall-e-3",
                    prompt=parts[x],
                    size=imageSize,
                    quality="standard",
                    n=1,
                )
                # Assuming response structure matches your API's design
                images.append(response.data[0].url)
                break  # Exit the retry loop on success
            except Exception as e:
                print(f"Error generating image for part {x+1}, attempt {attempt+1}: {e}")
                attempt += 1
                if attempt < retries:
                    time.sleep(delay)  # Wait before retrying
    print(images)
    return images


def download_image(url, path):
  """Download an image from a URL to a local path."""
  response = requests.get(url)
  if response.status_code == 200:
    with open(path, 'wb') as file:
      file.write(response.content)
  else:
    print(f"Failed to download {url}")


def create_video_with_audio(audio_path, num_images, uid, output_path="final_video.mov"):
    audio_clip = AudioFileClip(audio_path)
    audio_duration = audio_clip.duration  # Get audio duration in seconds

    # Calculate display duration for each image
    image_display_duration = audio_duration / num_images

    # Generate list of image paths
    image_paths = [f'image_{index}_{uid}.png' for index in range(num_images)]

    # Create ImageSequenceClip
    video_clip = ImageSequenceClip(image_paths, durations=[image_display_duration] * num_images)
    video_clip = video_clip.set_audio(audio_clip)

    # Write the final video to file
    video_clip.write_videofile(output_path, fps=24, codec='libx264', preset='ultrafast')

def createTranscriptions(audio_path):
    with open(audio_path, "rb") as audio_file:
        transcript = client.audio.transcriptions.create(
            file=audio_file,
            model="whisper-1",
            response_format="verbose_json",
        )

    print(transcript.segments)
    return transcript.segments


def wrap_text(text, max_width):
  """Wrap text to ensure each line is no longer than max_width."""
  # Use textwrap to wrap text. This returns a list of wrapped lines.
  wrapped_lines = textwrap.wrap(text, width=max_width)

  # Join the list of lines into a single string with line breaks.
  wrapped_text = '\n'.join(wrapped_lines)
  return wrapped_text


def overlay_captions_with_segments(video_clip, segments):
  caption_clips = []
  bar_height = 160  # Adjust this value as needed for the background bar height
  background_bar = ColorClip(size=(video_clip.size[0], bar_height),
                             color=(0, 0, 0, 128),
                             duration=video_clip.duration).set_position(
                                 ("bottom"))

  for segment in segments:
    start_time = segment['start']
    end_time = segment['end']
    text = segment['text']
    duration = end_time - start_time

    # Wrap text to fit a certain width
    wrapped_text = wrap_text(text, max_width=60)  # Adjust max_width as needed

    # Create a text clip for the wrapped text
    text_clip = TextClip(wrapped_text,
                         fontsize=36,
                         color='white',
                         font='Arial-Bold',
                         stroke_color='black',
                         stroke_width=1,
                         align="South",
                         method='caption',
                         size=(video_clip.w,
                               bar_height)).set_start(start_time).set_duration(
                                   duration).set_position('bottom')

    caption_clips.append(text_clip)

  final_video = CompositeVideoClip([video_clip, background_bar] +
                                   caption_clips,
                                   size=video_clip.size)
  return final_video

def delete_file_with_retry(file_path, max_attempts=3, sleep_interval=1):
    for attempt in range(max_attempts):
        try:
            os.remove(file_path)
            print(f"Successfully deleted {file_path}")
            break
        except PermissionError as e:
            print(f"Attempt {attempt + 1} failed: {e}")
            time.sleep(sleep_interval)
        except Exception as e:
            print(f"Unexpected error: {e}")
            break
        
def createKeyPoints(prompt):
  response = client.chat.completions.create(
      model="gpt-4-turbo",
      messages=[{
         "role": 'system',
         "content": 'You are an ai assisant that makes a list of keypoints from a text that the user will give you. Make sure to format the keypoints like this: 1. Keypoint 1 2. Keypoint 2 and so on. Leave it all as plain text and dont include any bold or heading text'
      }, {
          "role": 'user',
          "content": prompt
      },],
      max_tokens=500,
  )
  text = response.choices[0].message.content
  lines = text.split('\n')

  # Create a list to store the values
  values = []

  # Process each line individually
  for line in lines:
    # Strip leading and trailing whitespace
    line = line.strip()

    # Find the first space after the number, marking the start of the value
    first_space_index = line.find(" ")
    if first_space_index == -1:
      # If no space is found, skip this line
      continue

    # Extract the value after the first space
    value = line[first_space_index + 1:].strip()

    # Add to the list
    values.append(value)
  
  print(values)
  return values



def createDefinitions(prompt):
  response = client.chat.completions.create(
      model="gpt-4-turbo",
      messages=[{
         "role": 'system',
         "content": 'You are an ai assisant that makes a list of vocab words and their definitions using the text the user will provide. Format it like this: 1. Vocab word - Definition 2. Vocab word - Definition and so on. Leave it all as plain text and dont include any bold or heading text'
      }, {
          "role": 'user',
          "content": prompt
      },],
      max_tokens=500,
  )
  text = response.choices[0].message.content
  word_def_dict = {}

    # Split the input text into lines
  lines = text.split('\n')

    # Process each line individually
  for line in lines:
    # Strip leading and trailing whitespace
    line = line.strip()

    # Find the first occurrence of " - " which separates word and definition
    split_index = line.find(" - ")
    if split_index == -1:
      # If no " - " is found, skip this line
      continue

    # Extract the word and definition
    word = line[line.find(" ") + 1:split_index].strip()
    definition = line[split_index + 3:].strip()

    # Add to the dictionary
    word_def_dict[word] = definition

  print(word_def_dict)
  return word_def_dict

def createQuestions(prompt):
  response = client.chat.completions.create(
      model="gpt-4-turbo",
      messages=[{
         "role": 'system',
         "content": """You are an ai assisant that makes a list of questions pertaining to the text the user gives you. Format them like this. 
         Q1: Question
         A: answer
         B: answer - correct
         C: answer
         D: answer
         Q2: Question
         and so on"""
      }, {
          "role": 'user',
          "content": prompt
      },],
      max_tokens=500,
  )
  print(response.choices[0].message.content)
  return(response.choices[0].message.content)


def createFlashcards(prompt):
  response = client.chat.completions.create(
    model="gpt-4-turbo",
    messages=[{
       "role": 'system',
       "content": """You are an ai assistant that makes different informational flashcards relating to the prompt the user has given. You will format the flashcards like this:
       Flashcard 1
       Front of card: Question about topic
       Back of card: Answer

       Flashcard 2
        Front of card: Question about topic
        Back of card: Answer

      Flashcard 3
       Front of card: Question about topic
       Back of card: Answer

      Flashcard 4
       Front of card: Question about topic
       Back of card: Answer

      Flashcard 5
       Front of card: Question about topic
       Back of card: Answer
       """    
      }, {
        "role": 'user',
        "content": prompt
      },],
      max_tokens=500,
)

  print(response.choices[0].message.content)
  return(response.choices[0].message.content)


@app.route('/heartbeat')
def heartbeat():
    return 'OK', 200

@app.route('/generate-script', methods=['POST', 'GET'])
def genScript():
    if 'prompt' not in request.form:
        return jsonify({"error": "Prompt is required"}), 400

    # Extract prompt and (optional) script text
    prompt_text = request.form['prompt']
    language  = request.form.get('language')
    strNumImages = request.form['imageCount']
    numImages = int(strNumImages)
    script_text = request.form.get('script')
    uid = request.form.get('uid')

    if 'pdf' in request.files:
      pdf_file = request.files['pdf']
      pdf_file.save(f'user_pdf_{uid}.pdf')
      pdfText = extract_text(f'user_pdf_{uid}.pdf')
      print(pdfText)

    if script_text:
        generated_text = createScript(script_text + f" Split the story into {numImages} parts like so: Part 1: text  Part 2: text and so on. Do NOT change anything else about the text at ALL. DO NOT make the part markers in headings just leave them as plain text", True)
    else:
        if language:
           language_text = f'Make the script in {language}. However, make sure to leave the Part markers in english'
        else:
           language_text = ''
        if 'pdf' in request.files:
            generated_text = createScript(prompt_text + f"Split the story into {numImages} parts like so: Part 1: text  Part 2: text and so on. DO NOT make the part markers in headings just leave them as plain text. Make sure to keep fairly short. Reading it should take 1 - 2 minutes. {language_text} Also, make sure to use this information: {pdfText}", False)
        else: 
            generated_text = createScript(prompt_text + f"Split the story into {numImages} parts like so: Part 1: text  Part 2: text and so on. DO NOT make the part markers in headings just leave them as plain text. Make sure to keep fairly short. Reading it should take 1 - 2 minutes. {language_text}", False)

    return generated_text
   

@app.route('/generate-images', methods=['POST', 'GET'])
def genImages():
    imageSize = request.form.get('imageSize')
    text = request.form.get('text')
    uid = request.form.get('uid')
    image_paths = []
    image_urls = []
    
    if 'images' in request.files:
        image_files = request.files.getlist('images')
        for index, image in enumerate(image_files):
            img_temp_path = f'image_{index}_{uid}.png'
            image.save(img_temp_path)
            image_paths.append(img_temp_path)
    
    if not 'images' in request.files:
        if imageSize:
            image_urls = createImages(text, imageSize)
            for index, image_url in enumerate(image_urls):
                img_temp_path = f'image_{index}_{uid}.png'
                download_image(image_url, img_temp_path)
                image_paths.append(img_temp_path)

    if image_urls:
      return jsonify(image_urls=image_urls, image_paths=image_paths), 200
    else:
      return jsonify(message='OK'), 200

@app.route('/generate-replacement', methods=['POST', 'GET'])
def replaceImages():
  uid = request.form['uid']
  imageIndex = request.form['index']
  imageFile = request.files['image']
  imageFile.save(f'image_{imageIndex}_{uid}.png')
  return 'OK', 200


@app.route('/generate-audio', methods=['POST', 'GET'])
def genAudio():
  uid = request.form['uid']
  text = request.form['text']
  createAudio(text, uid)
  return 'OK', 200


@app.route('/generate-video', methods=['POST', 'GET'])
def genVideo():
  uid = request.form['uid']
  pdfVideo = request.form.get('pdf')
  strNumImages = request.form['imageCount']
  numImages = int(strNumImages)

  temp_video_path = tempfile.mktemp(suffix=".mov")
  create_video_with_audio(f'speech_{uid}.mp3', numImages, uid, temp_video_path)

  # Load the generated video and overlay captions generated from the audio
  video_clip = VideoFileClip(temp_video_path)
  final_video_with_captions = overlay_captions_with_segments(video_clip, createTranscriptions(f'speech_{uid}.mp3'))

  # Save the final video with captions
  final_output_path = tempfile.mktemp(suffix=".mov")
  final_video_with_captions.write_videofile(final_output_path,
                                            fps=24,
                                            codec='libx264',
                                            preset='ultrafast')
  
  time.sleep(1)

  delete_file_with_retry(f'speech_{uid}.mp3')

  if pdfVideo == 'true':
      delete_file_with_retry(f'user_pdf_{uid}.pdf')

  for i in range(numImages):  # Assuming numImages is the correct count for image files
      delete_file_with_retry(f'image_{i}_{uid}.png')
  
  return send_file(final_output_path, as_attachment=True, download_name='final_video_with_captions.mov')

@app.route('/definitions', methods = ['POST', 'GET'])
def Server_Def():
    transcript = request.form.get('transcript')
    return createDefinitions(transcript)

@app.route('/questions', methods = ['POST', 'GET'])
def Server_Questions():
    transcript = request.form.get('transcript')
    return createQuestions(transcript)

@app.route('/keypoints', methods = ['POST', 'GET'])
def Server_Keys():
    transcript = request.form.get('transcript')
    return createKeyPoints(transcript)

@app.route('/flashcards', methods = ['POST', 'GET'])
def Server_FlashCards():
    transcript = request.form.get('transcript')
    return createFlashcards(transcript)