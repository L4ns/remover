import os
import json
import cv2
import numpy as np
import subprocess
import yt_dlp
import requests
from flask import Flask, request, jsonify, Response
from flask_cors import CORS
from werkzeug.utils import secure_filename
from loguru import logger
from concurrent.futures import ThreadPoolExecutor
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2 import service_account
from dotenv import load_dotenv

# Memuat variabel lingkungan dari file .env
load_dotenv()

# Mengambil kredensial JSON dari environment variable
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON")
if not GOOGLE_CREDENTIALS_JSON:
    raise ValueError("GOOGLE_CREDENTIALS_JSON tidak ditemukan di file .env")

app = Flask(__name__)
CORS(app)
logger.add("app.log", rotation="5 MB", retention="10 days", level="INFO")

MAX_RESCALE_WIDTH = 640

def download_video(url, output_dir="downloads", cookies=None):
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    ydl_opts = {
        'outtmpl': os.path.join(output_dir, '%(title)s.%(ext)s'),
        'format': 'bestvideo+bestaudio/best',
        'merge_output_format': 'mp4',
        'quiet': True,
    }
    if cookies:
        ydl_opts['cookiefile'] = cookies

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)
        if not filename.endswith('.mp4'):
            filename = filename.rsplit('.', 1)[0] + '.mp4'
        return filename, info

def extract_frames(video_path, downscale=True):
    cap = cv2.VideoCapture(video_path)
    frames = []
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if downscale:
            h, w = frame.shape[:2]
            if w > MAX_RESCALE_WIDTH:
                ratio = MAX_RESCALE_WIDTH / w
                frame = cv2.resize(frame, (int(w * ratio), int(h * ratio)))
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        frames.append(gray)
    cap.release()
    return np.stack(frames)

def detect_watermark_mask(frames, threshold=10, min_area=50):
    min_frame = np.min(frames, axis=0)
    max_frame = np.max(frames, axis=0)
    diff = cv2.absdiff(min_frame.astype(np.uint8), max_frame.astype(np.uint8))
    _, mask = cv2.threshold(diff, threshold, 255, cv2.THRESH_BINARY)

    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5,5), np.uint8))
    mask = cv2.medianBlur(mask, 5)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    final_mask = np.zeros_like(mask)
    for cnt in contours:
        if cv2.contourArea(cnt) > min_area:
            cv2.drawContours(final_mask, [cnt], -1, 255, -1)
    return final_mask

def process_frame(frame, mask):
    if mask.shape != frame.shape[:2]:
        mask_resized = cv2.resize(mask, (frame.shape[1], frame.shape[0]))
    else:
        mask_resized = mask
    return cv2.inpaint(frame, mask_resized, 3, cv2.INPAINT_TELEA)

def remove_watermark(input_path, output_path, mask):
    cap = cv2.VideoCapture(input_path)
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    fps = cap.get(cv2.CAP_PROP_FPS)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    out = cv2.VideoWriter(output_path, fourcc, fps, (w, h))

    with ThreadPoolExecutor() as executor:
        futures = []
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            futures.append(executor.submit(process_frame, frame, mask))

        for future in futures:
            result = future.result()
            out.write(result)

    cap.release()
    out.release()

def merge_audio(original, processed, output):
    cmd = [
        'ffmpeg', '-y', '-i', processed, '-i', original,
        '-c:v', 'libx264', '-c:a', 'aac',
        '-map', '0:v:0', '-map', '1:a:0', '-shortest',
        output
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

def upload_to_gdrive(file_path, creds_json, folder_id=None):
    SCOPES = ['https://www.googleapis.com/auth/drive']
    creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
    creds = service_account.Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    service = build('drive', 'v3', credentials=creds)

    file_metadata = {'name': os.path.basename(file_path)}
    if folder_id:
        file_metadata['parents'] = [folder_id]

    media = MediaFileUpload(file_path, mimetype='video/mp4', resumable=True)
    file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()

    file_id = file.get('id')
    service.permissions().create(fileId=file_id, body={'role': 'reader', 'type': 'anyone'}).execute()
    return file_id, f"https://drive.google.com/uc?export=download&id={file_id}"

@app.route("/stream/<file_id>")
def stream(file_id):
    range_header = request.headers.get('Range', None)
    url = f"https://drive.google.com/uc?export=download&id={file_id}"
    headers = {'Range': range_header} if range_header else {}
    r = requests.get(url, stream=True, headers=headers)
    return Response(r.iter_content(chunk_size=8192), status=r.status_code, headers=dict(r.headers))

@app.route('/process', methods=['POST'])
def process():
    url = request.json.get('url')
    if not url:
        return jsonify({'error': 'URL tidak diberikan'}), 400

    filename, _ = download_video(url)
    frames = extract_frames(filename)
    mask = detect_watermark_mask(frames)

    processed = filename.replace(".mp4", "_processed.mp4")
    final = filename.replace(".mp4", "_final.mp4")
    remove_watermark(filename, processed, mask)
    merge_audio(filename, processed, final)

    file_id, stream_url = upload_to_gdrive(final, "credentials.json")
    os.remove(filename)
    os.remove(processed)
    os.remove(final)

    return jsonify({'stream_url': f"/stream/{file_id}", 'file_id': file_id})

if __name__ == "__main__":
    logger.info("Server berjalan di http://0.0.0.0:5000")
    app.run(host="0.0.0.0", port=5000)
