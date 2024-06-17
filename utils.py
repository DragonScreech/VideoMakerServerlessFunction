import firebase_admin
from firebase_admin import credentials, storage
import os
import re
import requests
import textwrap
import time
from openai import OpenAI
from moviepy.editor import AudioFileClip, ColorClip, CompositeVideoClip, ImageSequenceClip, TextClip, VideoFileClip
from pdfminer.high_level import extract_text
import tempfile
from dotenv import load_dotenv

load_dotenv()

# Initialize the Firebase Admin SDK
cred = credentials.Certificate({
    "type": "service_account",
    "project_id": os.getenv('FIREBASE_PROJECT_ID'),
    "private_key_id": os.getenv('FIREBASE_PRIVATE_KEY_ID'),
    "private_key": os.getenv('FIREBASE_PRIVATE_KEY').replace('\\n', '\n'),
    "client_email": os.getenv('FIREBASE_CLIENT_EMAIL'),
    "client_id": os.getenv('FIREBASE_CLIENT_ID'),
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    "client_x509_cert_url": os.getenv('FIREBASE_CLIENT_X509_CERT_URL')
})
firebase_admin.initialize_app(cred, {
    'storageBucket': os.getenv('FIREBASE_PROJECT_ID') + '.appspot.com'
})


client = OpenAI(api_key=os.getenv('OPEN_AI_API_KEY'))

def upload_to_firebase(file_path, destination_blob_name, folder='temp'):
    bucket = storage.bucket()
    full_blob_name = f"{folder}/{destination_blob_name}"
    blob = bucket.blob(full_blob_name)
    blob.upload_from_filename(file_path)
    return blob.public_url

def download_from_firebase(source_blob_name, destination_file_path, folder='temp'):
    bucket = storage.bucket()
    full_blob_name = f"{folder}/{source_blob_name}"
    blob = bucket.blob(full_blob_name)
    blob.download_to_filename(destination_file_path)

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
        }],
        max_tokens=500,
    )
    return response.choices[0].message.content

def createAudio(text, uid):
    speech_file_path = f"speech_{uid}.mp3"
    cleaned_text = re.sub(r'Part \d+:', '', text)
    response = client.audio.speech.create(model="tts-1", voice="alloy", input=cleaned_text)
    response.stream_to_file(speech_file_path)
    firebase_url = upload_to_firebase(speech_file_path, f"speech_{uid}.mp3", folder='temp')
    return firebase_url

def createImages(textPrompt, imageSize, retries=3, delay=2):
    images = []
    parts = re.split(r'Part \d+:', textPrompt)

    if parts[0] == '':
        parts.pop(0)

    parts = [part.strip() for part in parts]
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
                images.append(response.data[0].url)
                break
            except Exception as e:
                attempt += 1
                if attempt < retries:
                    time.sleep(delay)
    return images

def download_image(url, path):
    response = requests.get(url)
    if response.status_code == 200:
        with open(path, 'wb') as file:
            file.write(response.content)

def create_video_with_audio(audio_path, num_images, uid, output_path="final_video.mov"):
    audio_clip = AudioFileClip(audio_path)
    audio_duration = audio_clip.duration

    image_display_duration = audio_duration / num_images

    image_paths = [f'image_{index}_{uid}.png' for index in range(num_images)]

    video_clip = ImageSequenceClip(image_paths, durations=[image_display_duration] * num_images)
    video_clip = video_clip.set_audio(audio_clip)

    video_clip.write_videofile(output_path, fps=24, codec='libx264', preset='ultrafast')

def createTranscriptions(audio_path):
    with open(audio_path, "rb") as audio_file:
        transcript = client.audio.transcriptions.create(
            file=audio_file,
            model="whisper-1",
            response_format="verbose_json",
        )
    return transcript.segments

def wrap_text(text, max_width):
    wrapped_lines = textwrap.wrap(text, width=max_width)
    wrapped_text = '\n'.join(wrapped_lines)
    return wrapped_text

def overlay_captions_with_segments(video_clip, segments):
    caption_clips = []
    bar_height = 160
    background_bar = ColorClip(size=(video_clip.size[0], bar_height), color=(0, 0, 0, 128), duration=video_clip.duration).set_position("bottom")

    for segment in segments:
        start_time = segment['start']
        end_time = segment['end']
        text = segment['text']
        duration = end_time - start_time

        wrapped_text = wrap_text(text, max_width=60)

        text_clip = TextClip(wrapped_text, fontsize=36, color='white', font='Arial-Bold', stroke_color='black', stroke_width=1, align="South", method='caption', size=(video_clip.w, bar_height)).set_start(start_time).set_duration(duration).set_position('bottom')

        caption_clips.append(text_clip)

    final_video = CompositeVideoClip([video_clip, background_bar] + caption_clips, size=video_clip.size)
    return final_video

def delete_file_with_retry(file_path, max_attempts=3, sleep_interval=1):
    for attempt in range(max_attempts):
        try:
            os.remove(file_path)
            break
        except PermissionError as e:
            time.sleep(sleep_interval)
        except Exception as e:
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
        }],
        max_tokens=500,
    )
    text = response.choices[0].message.content
    lines = text.split('\n')

    values = []
    for line in lines:
        line = line.strip()
        first_space_index = line.find(" ")
        if first_space_index == -1:
            continue
        value = line[first_space_index + 1:].strip()
        values.append(value)
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
        }],
        max_tokens=500,
    )
    text = response.choices[0].message.content
    word_def_dict = {}
    lines = text.split('\n')
    for line in lines:
        line = line.strip()
        split_index = line.find(" - ")
        if split_index == -1:
            continue
        word = line[line.find(" ") + 1:split_index].strip()
        definition = line[split_index + 3:].strip()
        word_def_dict[word] = definition
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
        }],
        max_tokens=500,
    )
    return response.choices[0].message.content

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
        }],
        max_tokens=500,
    )
    return response.choices[0].message.content

