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

# ── Cobalt API ────────────────────────────────────────────────────────────────
COBALT_API = "https://api.cobalt.tools/"
COBALT_HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (compatible; VidFetch/1.0)",
}

def is_youtube(url: str) -> bool:
    return "youtube.com" in url or "youtu.be" in url

def clean_youtube_url(url: str) -> str:
    """Extract clean video URL, removing playlist/tracking params."""
    match = re.search(r'(?:youtu\.be/|[?&]v=)([a-zA-Z0-9_-]{11})', url)
    if match:
        return f"https://www.youtube.com/watch?v={match.group(1)}"
    return url

def get_youtube_info_oembed(url: str, dl_type: str) -> dict:
    """Get YouTube info via oEmbed (no auth, no bot detection)."""
    oembed = req.get(
        f"https://www.youtube.com/oembed?url={url}&format=json",
        timeout=10
    )
    if not oembed.ok:
        raise Exception("YouTube video bilgisi alınamadı (oEmbed)")
    data = oembed.json()

    if dl_type == "mp3":
        formats = [{"format_id": "mp3", "ext": "mp3", "resolution": "Yüksek Kalite", "note": "Ses"}]
    else:
        formats = [
            {"format_id": "1080", "ext": "mp4", "resolution": "1080p", "note": "FHD"},
            {"format_id": "720",  "ext": "mp4", "resolution": "720p",  "note": "HD"},
            {"format_id": "480",  "ext": "mp4", "resolution": "480p",  "note": "SD"},
        ]
    return {
        "title":     data.get("title", "Unknown"),
        "thumbnail": data.get("thumbnail_url", ""),
        "duration":  0,
        "platform":  "youtube",
        "formats":   formats,
    }

def get_cobalt_url(url: str, quality: str, dl_type: str) -> str:
    """Call Cobalt API to get a direct download URL."""
    # Clean YouTube URLs (remove playlist params that break Cobalt)
    if is_youtube(url):
        url = clean_youtube_url(url)

    if dl_type == "mp3":
        payload = {
            "url": url,
            "downloadMode": "audio",
            "audioFormat": "mp3",
            "audioQuality": "320",
        }
    else:
        payload = {
            "url": url,
            "downloadMode": "auto",
            "videoQuality": quality,
            "filenameStyle": "basic",
        }

    resp = req.post(COBALT_API, json=payload, headers=COBALT_HEADERS, timeout=30)
    if not resp.ok:
        raise Exception(f"Cobalt API hatası: {resp.status_code} – {resp.text[:200]}")
    data = resp.json()
    status = data.get("status")

    if status in ("redirect", "tunnel"):
        return data["url"]
    elif status == "picker":
        return data["picker"][0]["url"]
    else:
        err = data.get("error", {})
        raise Exception(f"Cobalt hatası: {err.get('code', str(data))}")

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

    # YouTube: use oEmbed to avoid bot detection
    if is_youtube(url):
        try:
            return get_youtube_info_oembed(url, dl_type)
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

        # YouTube & Cobalt-compatible: use Cobalt API
        cobalt_quality = format_id if format_id in ("mp3", "1080", "720", "480") else None

        if cobalt_quality or is_youtube(url):
            quality = cobalt_quality or ("mp3" if dl_type == "mp3" else "1080")
            jobs[job_id]["progress"] = 10
            cobalt_url = get_cobalt_url(url, quality, dl_type)
            jobs[job_id]["progress"] = 20

            ext = "mp3" if dl_type == "mp3" else "mp4"
            filename = f"vidfetch_{job_id}.{ext}"
            filepath = f"./downloads/{filename}"

            # Stream download from Cobalt URL
            with req.get(cobalt_url, stream=True, timeout=120) as r:
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
