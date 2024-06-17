from flask import request, send_file, jsonify
from utils import create_video_with_audio, overlay_captions_with_segments, createTranscriptions, download_from_firebase
from moviepy.editor import VideoFileClip
import tempfile

def handler(request):
    uid = request.form['uid']
    pdfVideo = request.form.get('pdf')
    strNumImages = request.form['imageCount']
    numImages = int(strNumImages)
    image_urls = request.form.getlist('imageUrls')
    audio_url = request.form.get('audioUrl')

    image_paths = []
    for index, _ in enumerate(image_urls):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as temp_img:
            download_from_firebase(f"image_{index}_{uid}.png", temp_img.name, folder='temp')
            image_paths.append(temp_img.name)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as temp_audio:
        temp_audio_path = temp_audio.name
        download_from_firebase(f"speech_{uid}.mp3", temp_audio_path, folder='temp')

    with tempfile.NamedTemporaryFile(delete=False, suffix=".mov") as temp_video:
        temp_video_path = temp_video.name
    create_video_with_audio(temp_audio_path, numImages, uid, temp_video_path)

    video_clip = VideoFileClip(temp_video_path)
    final_video_with_captions = overlay_captions_with_segments(video_clip, createTranscriptions(temp_audio_path))

    with tempfile.NamedTemporaryFile(delete=False, suffix=".mov") as final_output:
        final_output_path = final_output.name
    final_video_with_captions.write_videofile(final_output_path, fps=24, codec='libx264', preset='ultrafast')

    return send_file(final_output_path, as_attachment=True, download_name='final_video_with_captions.mov')


