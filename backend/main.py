from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
import yt_dlp
import os
import re
import glob
import json
import uuid
import threading
import shutil
import tempfile
import requests as req

# ── FFmpeg path ───────────────────────────────────────────────────────────────
_FFMPEG_EXE = shutil.which("ffmpeg")
FFMPEG_BIN = os.path.dirname(_FFMPEG_EXE) if _FFMPEG_EXE else (
    r"C:\Users\halil\AppData\Local\Microsoft\WinGet\Packages"
    r"\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
    r"\ffmpeg-8.1.1-full_build\bin"
)

# ── YouTube Cookies (fallback for yt-dlp info calls) ─────────────────────────
_COOKIE_FILE = None
_cookie_b64 = os.environ.get("YOUTUBE_COOKIES_B64", "").strip()
_cookie_raw = os.environ.get("YOUTUBE_COOKIES", "").strip()
_cookie_content = None
if _cookie_b64:
    import base64 as _b64
    try:
        _cookie_content = _b64.b64decode(_cookie_b64).decode("utf-8")
    except Exception:
        pass
elif _cookie_raw:
    _cookie_content = _cookie_raw
if _cookie_content:
    _tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8")
    _tmp.write(_cookie_content)
    _tmp.close()
    _COOKIE_FILE = _tmp.name

# ── RapidAPI YouTube Downloader ───────────────────────────────────────────────
RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY", "").strip()
RAPIDAPI_HOST = "youtube-media-downloader.p.rapidapi.com"

def is_youtube(url: str) -> bool:
    return "youtube.com" in url or "youtu.be" in url

def extract_youtube_id(url: str) -> str:
    match = re.search(r'(?:youtu\.be/|[?&]v=)([a-zA-Z0-9_-]{11})', url)
    return match.group(1) if match else None

def get_youtube_info_rapidapi(url: str, dl_type: str) -> dict:
    """Get YouTube info via RapidAPI."""
    if not RAPIDAPI_KEY:
        raise Exception("RAPIDAPI_KEY bulunamadı! Lütfen Render Dashboard'a ekleyin.")
        
    video_id = extract_youtube_id(url)
    if not video_id:
        raise Exception("Geçersiz YouTube URL'si")

    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": RAPIDAPI_HOST
    }
    
    resp = req.get(f"https://{RAPIDAPI_HOST}/v2/video/details", params={"videoId": video_id}, headers=headers, timeout=15)
    if not resp.ok:
        raise Exception(f"RapidAPI hatası: {resp.status_code} - {resp.text[:100]}")
        
    data = resp.json()
    
    formats = []
    if dl_type == "mp3":
        # Check audios
        audios = data.get("audios", {"items": []}).get("items", [])
        if audios:
            best_audio = sorted(audios, key=lambda x: int(x.get("bitrate", 0)), reverse=True)[0]
            formats.append({"format_id": best_audio["url"], "ext": "mp3", "resolution": "Yüksek Kalite", "note": "Ses"})
    else:
        # Check videos
        videos = data.get("videos", {"items": []}).get("items", [])
        if videos:
            for v in videos:
                if v.get("hasAudio"):
                    height = v.get("height", 0)
                    formats.append({
                        "format_id": v["url"],
                        "ext": "mp4",
                        "resolution": f"{height}p",
                        "note": "Video"
                    })
            if not formats:
                formats.append({"format_id": videos[0]["url"], "ext": "mp4", "resolution": "Standart", "note": "Video"})

    return {
        "title": data.get("title", "Unknown"),
        "thumbnail": data.get("thumbnails", [{"url": ""}])[0]["url"],
        "duration": data.get("lengthSeconds", 0),
        "platform": "youtube",
        "formats": formats
    }




def _base_ydl_opts() -> dict:
    opts = {
        "quiet": True,
        "no_color": True,
        "ffmpeg_location": FFMPEG_BIN,
    }
    if _COOKIE_FILE:
        opts["cookiefile"] = _COOKIE_FILE
    return opts

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="VidFetch API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

jobs: dict = {}

class VideoRequest(BaseModel):
    url: str
    type: str = "mp4"

class DownloadRequest(BaseModel):
    url: str
    format_id: str
    type: str

def cleanup_file(filepath: str):
    try:
        if filepath and os.path.exists(filepath):
            os.remove(filepath)
    except Exception:
        pass

# ── Endpoints ─────────────────────────────────────────────────────────────────
@app.get("/")
def read_root():
    return {"message": "VidFetch API is running", "ffmpeg": FFMPEG_BIN, "cookies": bool(_COOKIE_FILE)}


@app.post("/api/info")
def get_video_info(req_body: VideoRequest):
    url = req_body.url
    dl_type = req_body.type

    # YouTube: use RapidAPI
    if is_youtube(url):
        try:
            return get_youtube_info_rapidapi(url, dl_type)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # Other platforms: use yt-dlp
    ydl_opts = {**_base_ydl_opts(), "skip_download": True, "noplaylist": True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        formats = []
        if dl_type == "mp3":
            formats.append({"format_id": "mp3", "ext": "mp3", "resolution": "Yüksek Kalite", "note": "Ses"})
        else:
            max_h = max(
                (f.get("height", 0) or 0)
                for f in info.get("formats", [])
                if f.get("vcodec") != "none"
            ) if info.get("formats") else 0

            if max_h >= 1080:
                formats.append({"format_id": "bestvideo[height<=1080]+bestaudio/best[height<=1080]", "ext": "mp4", "resolution": "1080p", "note": "FHD"})
            if max_h >= 720:
                formats.append({"format_id": "bestvideo[height<=720]+bestaudio/best[height<=720]", "ext": "mp4", "resolution": "720p", "note": "HD"})
            if max_h >= 480:
                formats.append({"format_id": "bestvideo[height<=480]+bestaudio/best[height<=480]", "ext": "mp4", "resolution": "480p", "note": "SD"})
            if not formats:
                formats.append({"format_id": "best", "ext": "mp4", "resolution": "En İyi Kalite", "note": "Standart"})

        return {
            "title":     info.get("title", "Unknown"),
            "thumbnail": info.get("thumbnail", ""),
            "duration":  info.get("duration", 0),
            "platform":  info.get("extractor", "unknown"),
            "formats":   formats,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _do_download(job_id: str, url: str, format_id: str, dl_type: str):
    try:
        os.makedirs("./downloads", exist_ok=True)
        filepath = None

        # YouTube: format_id is the direct download URL from RapidAPI
        if is_youtube(url):
            jobs[job_id]["progress"] = 20
            direct_url = format_id

            ext = "mp3" if dl_type == "mp3" else "mp4"
            filename = f"vidfetch_{job_id}.{ext}"
            filepath = f"./downloads/{filename}"

            # Stream download from RapidAPI URL
            with req.get(direct_url, stream=True, timeout=120) as r:
                r.raise_for_status()
                total = int(r.headers.get("content-length", 0))
                downloaded = 0
                with open(filepath, "wb") as f:
                    for chunk in r.iter_content(chunk_size=65536):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total > 0:
                                pct = 20 + round((downloaded / total) * 75)
                                jobs[job_id]["progress"] = min(pct, 95)

            clean_name = filename.replace(f"_{job_id}", "")

        else:
            # Other platforms: use yt-dlp directly
            def progress_hook(d):
                if d["status"] == "downloading":
                    total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
                    done = d.get("downloaded_bytes", 0)
                    if total > 0:
                        jobs[job_id]["progress"] = round((done / total) * 90)
                elif d["status"] == "finished":
                    jobs[job_id]["progress"] = 95

            ydl_opts = {
                **_base_ydl_opts(),
                "format": format_id,
                "outtmpl": f"./downloads/{job_id}_%(title)s.%(ext)s",
                "noplaylist": True,
                "progress_hooks": [progress_hook],
                "merge_output_format": "mp4" if dl_type == "mp4" else None,
            }
            if dl_type == "mp3":
                ydl_opts["postprocessors"] = [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }]

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.extract_info(url, download=True)

            files = glob.glob(f"./downloads/{job_id}_*")
            if not files:
                raise Exception("Dosya bulunamadı")
            filepath = files[0]
            clean_name = os.path.basename(filepath).replace(f"{job_id}_", "")

        jobs[job_id].update({
            "status": "done", "progress": 100,
            "filepath": filepath, "filename": clean_name,
        })
    except Exception as e:
        jobs[job_id].update({"status": "error", "error": str(e)})


@app.post("/api/download/start")
def start_download(req_body: DownloadRequest):
    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status": "running", "progress": 0, "filepath": None, "filename": None, "error": None}
    threading.Thread(
        target=_do_download,
        args=(job_id, req_body.url, req_body.format_id, req_body.type),
        daemon=True
    ).start()
    return {"job_id": job_id}


@app.get("/api/download/progress/{job_id}")
def download_progress(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    def event_stream():
        import time
        while True:
            job = jobs.get(job_id, {})
            yield f"data: {json.dumps({'status': job.get('status'), 'progress': job.get('progress', 0), 'error': job.get('error')})}\n\n"
            if job.get("status") in ("done", "error"):
                break
            time.sleep(0.5)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/api/download/file/{job_id}")
def serve_file(job_id: str, background_tasks: BackgroundTasks):
    job = jobs.get(job_id)
    if not job or job.get("status") != "done":
        raise HTTPException(status_code=404, detail="File not ready")

    filepath, filename = job["filepath"], job["filename"]
    background_tasks.add_task(cleanup_file, filepath)
    jobs.pop(job_id, None)
    return FileResponse(path=filepath, filename=filename, media_type="application/octet-stream")
