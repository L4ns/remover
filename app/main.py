import json
import os
import cv2
import numpy as np
import subprocess
import requests
from fastapi import FastAPI, File, UploadFile, Form, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2 import service_account
from dotenv import load_dotenv
from loguru import logger
from tempfile import NamedTemporaryFile
from shutil import copyfileobj
from concurrent.futures import ThreadPoolExecutor
import yt_dlp
import threading

# Load .env for Google Credentials
load_dotenv()
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON")
if not GOOGLE_CREDENTIALS_JSON:
    raise ValueError("GOOGLE_CREDENTIALS_JSON tidak ditemukan di file .env")

# Initialize FastAPI app
app = FastAPI()
logger.add("app.log", rotation="5 MB", retention="10 days", level="INFO")

# CORS for frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Set this to a specific frontend URL in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_RESCALE_WIDTH = 640

# ---------- Video Processing Utilities ----------

def download_video(url, output_dir="downloads", cookies=None):
    os.makedirs(output_dir, exist_ok=True)
    ydl_opts = {
        'outtmpl': os.path.join(output_dir, '%(title)s.%(ext)s'),
        'format': 'bestvideo+bestaudio/best',
        'merge_output_format': 'mp4',
        'quiet': True,
    }
    if cookies:
        ydl_opts['cookiefile'] = cookies

    try:
        logger.info(f"Downloading video from URL: {url}")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            if not filename.endswith('.mp4'):
                filename = filename.rsplit('.', 1)[0] + '.mp4'
            logger.info(f"Video downloaded: {filename}")
            return filename, info
    except Exception as e:
        logger.error(f"Failed to download video: {e}")
        raise e

def extract_frames(video_path, downscale=True):
    logger.info(f"Extracting frames from video: {video_path}")
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
    logger.info(f"Extracted {len(frames)} frames.")
    return np.stack(frames)

def detect_watermark_mask(frames, threshold=10, min_area=50):
    logger.info("Detecting watermark mask from frames.")
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
    logger.info("Watermark mask detection complete.")
    return final_mask

def process_frame(frame, mask):
    if mask.shape != frame.shape[:2]:
        mask_resized = cv2.resize(mask, (frame.shape[1], frame.shape[0]))
    else:
        mask_resized = mask
    return cv2.inpaint(frame, mask_resized, 3, cv2.INPAINT_TELEA)

def remove_watermark(input_path, output_path, mask):
    logger.info(f"Removing watermark from video: {input_path}")
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
    logger.info(f"Watermark removal complete. Output saved to: {output_path}")

def merge_audio(original, processed, output):
    logger.info(f"Merging audio from {original} with processed video {processed} into {output}.")
    cmd = [
        'ffmpeg', '-y', '-i', processed, '-i', original,
        '-c:v', 'libx264', '-c:a', 'aac',
        '-map', '0:v:0', '-map', '1:a:0', '-shortest',
        output
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    logger.info(f"Audio merge complete. Output saved to: {output}")

def upload_to_gdrive(file_path, creds_json, folder_id=None):
    logger.info(f"Uploading file {file_path} to Google Drive.")
    SCOPES = ['https://www.googleapis.com/auth/drive']
    creds_dict = json.loads(creds_json)
    creds = service_account.Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    service = build('drive', 'v3', credentials=creds)

    file_metadata = {'name': os.path.basename(file_path)}
    if folder_id:
        file_metadata['parents'] = [folder_id]

    media = MediaFileUpload(file_path, mimetype='video/mp4', resumable=True)
    file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()

    file_id = file.get('id')
    service.permissions().create(fileId=file_id, body={'role': 'reader', 'type': 'anyone'}).execute()
    logger.info(f"File uploaded to Google Drive with file ID: {file_id}")
    return file_id, f"https://drive.google.com/uc?export=download&id={file_id}"

# ---------- File Removal after Delay ----------

# Fungsi untuk menghapus file setelah delay
def remove_file_after_delay(file_path, delay_seconds):
    def remove_file():
        if os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f"File {file_path} berhasil dihapus setelah {delay_seconds} detik.")
        else:
            logger.warning(f"File {file_path} tidak ditemukan saat penghapusan.")
    
    # Menjadwalkan penghapusan setelah 'delay_seconds'
    timer = threading.Timer(delay_seconds, remove_file)
    timer.start()

# ---------- FastAPI Routes ----------
@app.post("/process")
async def process(request: Request):
    data = await request.json()
    url = data.get("url")
    if not url:
        logger.error("URL tidak diberikan.")
        return JSONResponse(status_code=400, content={"error": "URL tidak diberikan"})

    try:
        logger.info(f"Processing video with URL: {url}")
        filename, _ = download_video(url)
        frames = extract_frames(filename)
        mask = detect_watermark_mask(frames)

        processed = filename.replace(".mp4", "_processed.mp4")
        final = filename.replace(".mp4", "_final.mp4")

        remove_watermark(filename, processed, mask)
        merge_audio(filename, processed, final)

        file_id, stream_url = upload_to_gdrive(final, GOOGLE_CREDENTIALS_JSON)

        # Menjadwalkan penghapusan file setelah 30 menit (1800 detik)
        remove_file_after_delay(filename, 1800)  # 30 menit
        remove_file_after_delay(processed, 1800)  # 30 menit
        remove_file_after_delay(final, 1800)  # 30 menit

        os.remove(filename)
        os.remove(processed)
        os.remove(final)

        logger.info(f"Processing complete. File ID: {file_id}")
        return {"result_url": f"/stream/{file_id}", "file_id": file_id}
    except Exception as e:
        logger.error(f"Process error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    if not file.filename.endswith(".mp4"):
        logger.error("Invalid file type. Only .mp4 files are supported.")
        return JSONResponse(status_code=400, content={"error": "Hanya file .mp4 yang didukung"})

    try:
        logger.info(f"Uploading file: {file.filename}")
        temp_input = NamedTemporaryFile(delete=False, suffix=".mp4")
        with temp_input as f:
            copyfileobj(file.file, f)
        input_path = temp_input.name

        processed = input_path.replace(".mp4", "_processed.mp4")
        final = input_path.replace(".mp4", "_final.mp4")

        frames = extract_frames(input_path)
        mask = detect_watermark_mask(frames)

        remove_watermark(input_path, processed, mask)
        merge_audio(input_path, processed, final)

        file_id, stream_url = upload_to_gdrive(final, GOOGLE_CREDENTIALS_JSON)

        # Menjadwalkan penghapusan file setelah 30 menit (1800 detik)
        remove_file_after_delay(input_path, 1800)  # 30 menit
        remove_file_after_delay(processed, 1800)  # 30 menit
        remove_file_after_delay(final, 1800)  # 30 menit

        os.remove(input_path)
        os.remove(processed)
        os.remove(final)

        logger.info(f"File upload and processing complete. File ID: {file_id}")
        return {"result_url": f"/stream/{file_id}", "file_id": file_id}

    except Exception as e:
        logger.error(f"Upload error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/stream/{file_id}")
async def stream_video(file_id: str, request: Request):
    range_header = request.headers.get("range")
    url = f"https://drive.google.com/uc?export=download&id={file_id}"
    headers = {"Range": range_header} if range_header else {}
    r = requests.get(url, stream=True, headers=headers)
    logger.info(f"Streaming video for file ID: {file_id}")
    return StreamingResponse(r.iter_content(chunk_size=8192), status_code=r.status_code, headers=dict(r.headers))
