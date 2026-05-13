from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
import yt_dlp
import os
import glob
import json
import uuid
import threading
import shutil

# ── FFmpeg path ─────────────────────────────────────────────────────────────
# On Render (Linux) ffmpeg is in PATH.  On Windows dev machine use the winget
# install location as fallback.
_FFMPEG_EXE = shutil.which("ffmpeg")
if _FFMPEG_EXE:
    # Give yt-dlp the directory that contains ffmpeg / ffprobe
    FFMPEG_BIN = os.path.dirname(_FFMPEG_EXE)
else:
    # Windows local fallback (development only)
    FFMPEG_BIN = (
        r"C:\Users\halil\AppData\Local\Microsoft\WinGet\Packages"
        r"\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
        r"\ffmpeg-8.1.1-full_build\bin"
    )

# ── App ──────────────────────────────────────────────────────────────────────
app = FastAPI(title="VidFetch API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory job store  { job_id: { status, progress, filepath, filename, error } }
jobs: dict = {}

# ── Models ───────────────────────────────────────────────────────────────────
class VideoRequest(BaseModel):
    url: str
    type: str = "mp4"

class DownloadRequest(BaseModel):
    url: str
    format_id: str
    type: str

# ── Helpers ──────────────────────────────────────────────────────────────────
def cleanup_file(filepath: str):
    try:
        if filepath and os.path.exists(filepath):
            os.remove(filepath)
    except Exception:
        pass

# ── Endpoints ────────────────────────────────────────────────────────────────
@app.get("/")
def read_root():
    return {"message": "VidFetch API is running", "ffmpeg": FFMPEG_BIN}


@app.post("/api/info")
def get_video_info(req: VideoRequest):
    ydl_opts = {
        "quiet": True,
        "skip_download": True,
        "noplaylist": True,
        "no_color": True,
        "ffmpeg_location": FFMPEG_BIN,
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "web"],
            }
        },
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(req.url, download=False)

        formats = []
        if req.type == "mp3":
            formats.append({
                "format_id": "bestaudio/best",
                "ext": "mp3",
                "resolution": "Yüksek Kalite",
                "note": "Ses",
            })
        else:
            max_height = max(
                (f.get("height", 0) or 0)
                for f in info.get("formats", [])
                if f.get("vcodec") != "none"
            ) if info.get("formats") else 0

            if max_height >= 1080:
                formats.append({"format_id": "bv[height<=1080][ext=mp4]+ba[ext=m4a]/bv[height<=1080]+ba/b[height<=1080]", "ext": "mp4", "resolution": "1080p", "note": "FHD"})
            if max_height >= 720:
                formats.append({"format_id": "bv[height<=720][ext=mp4]+ba[ext=m4a]/bv[height<=720]+ba/b[height<=720]",   "ext": "mp4", "resolution": "720p",  "note": "HD"})
            if max_height >= 480:
                formats.append({"format_id": "bv[height<=480][ext=mp4]+ba[ext=m4a]/bv[height<=480]+ba/b[height<=480]",   "ext": "mp4", "resolution": "480p",  "note": "SD"})
            if not formats:
                formats.append({"format_id": "b", "ext": "mp4", "resolution": "En İyi Kalite", "note": "Standart"})

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

        def progress_hook(d):
            if d["status"] == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
                downloaded = d.get("downloaded_bytes", 0)
                if total > 0:
                    jobs[job_id]["progress"] = round((downloaded / total) * 90)
            elif d["status"] == "finished":
                jobs[job_id]["progress"] = 95

        ydl_opts = {
            "format": format_id,
            "outtmpl": f"./downloads/{job_id}_%(title)s.%(ext)s",
            "quiet": True,
            "noplaylist": True,
            "ffmpeg_location": FFMPEG_BIN,
            "progress_hooks": [progress_hook],
            "merge_output_format": "mp4" if dl_type == "mp4" else None,
            "extractor_args": {
                "youtube": {
                    "player_client": ["android", "web"],
                }
            },
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
            jobs[job_id].update({"status": "error", "error": "Dosya bulunamadı."})
            return

        filepath = files[0]
        jobs[job_id].update({
            "status":   "done",
            "progress": 100,
            "filepath": filepath,
            "filename": os.path.basename(filepath).replace(f"{job_id}_", ""),
        })
    except Exception as e:
        jobs[job_id].update({"status": "error", "error": str(e)})


@app.post("/api/download/start")
def start_download(req: DownloadRequest):
    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status": "running", "progress": 0, "filepath": None, "filename": None, "error": None}
    threading.Thread(target=_do_download, args=(job_id, req.url, req.format_id, req.type), daemon=True).start()
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
