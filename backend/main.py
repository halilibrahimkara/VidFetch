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
import time
import threading
import shutil
import tempfile
import requests as req

# ── FFmpeg path ───────────────────────────────────────────────────────────────
_FFMPEG_EXE = shutil.which("ffmpeg")
FFMPEG_BIN = os.path.dirname(_FFMPEG_EXE) if _FFMPEG_EXE else ""

# ── Cookies (yt-dlp fallback) ─────────────────────────────────────────────────
_COOKIE_FILE = None
_cookie_b64 = os.environ.get("YOUTUBE_COOKIES_B64", "").strip()
if _cookie_b64:
    import base64 as _b64
    try:
        _cc = _b64.b64decode(_cookie_b64).decode("utf-8")
        _tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8")
        _tmp.write(_cc); _tmp.close()
        _COOKIE_FILE = _tmp.name
    except Exception:
        pass

# ── RapidAPI (MP3 only via youtube-mp36) ─────────────────────────────────────
RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY", "").strip()

def is_youtube(url: str) -> bool:
    return "youtube.com" in url or "youtu.be" in url

def extract_youtube_id(url: str) -> str:
    m = re.search(r'(?:youtu\.be/|[?&]v=)([a-zA-Z0-9_-]{11})', url)
    return m.group(1) if m else None

# ── YouTube MP3 via youtube-mp36 (CDN-hosted) ─────────────────────────────────
def get_youtube_mp3_url(video_id: str) -> str:
    if not RAPIDAPI_KEY:
        raise Exception("RAPIDAPI_KEY eksik! Render Environment'a ekleyin.")
    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": "youtube-mp36.p.rapidapi.com",
    }
    for _ in range(40):  # poll ~2 min
        try:
            r = req.get("https://youtube-mp36.p.rapidapi.com/dl",
                        params={"id": video_id}, headers=headers, timeout=30)
            if r.ok:
                d = r.json()
                if d.get("status") == "ok":
                    return d["link"]
                if d.get("status") == "fail":
                    raise Exception(f"MP3 hatasi: {d.get('msg','bilinmiyor')}")
        except Exception as e:
            if "hatasi" in str(e):
                raise
        time.sleep(3)
    raise Exception("MP3 donusumu zaman asimina ugradi (2dk)")

# ── yt-dlp helpers ────────────────────────────────────────────────────────────
# YouTube player clients to try in order (mobile/TV clients bypass bot detection better)
YT_CLIENTS = ["ios", "android_vr", "tv_embedded", "web_creator"]

def _yt_opts(extra: dict = None) -> dict:
    """Base yt-dlp options, tries mobile clients to avoid bot detection."""
    opts = {
        "quiet": True,
        "no_color": True,
        "noplaylist": True,
        "extractor_args": {
            "youtube": {
                "player_client": YT_CLIENTS,
                "skip": ["dash", "translated_subs"],
            }
        },
    }
    if FFMPEG_BIN:
        opts["ffmpeg_location"] = FFMPEG_BIN
    if _COOKIE_FILE:
        opts["cookiefile"] = _COOKIE_FILE
    if extra:
        opts.update(extra)
    return opts

def _base_ydl_opts() -> dict:
    """For non-YouTube platforms (no special client args needed)."""
    opts = {"quiet": True, "no_color": True, "noplaylist": True}
    if FFMPEG_BIN:
        opts["ffmpeg_location"] = FFMPEG_BIN
    if _COOKIE_FILE:
        opts["cookiefile"] = _COOKIE_FILE
    return opts

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="VidFetch API")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_credentials=False, allow_methods=["*"], allow_headers=["*"])
jobs: dict = {}

class VideoRequest(BaseModel):
    url: str
    type: str = "mp4"

class DownloadRequest(BaseModel):
    url: str
    format_id: str
    type: str

def cleanup_file(fp: str):
    try:
        if fp and os.path.exists(fp):
            os.remove(fp)
    except Exception:
        pass

@app.get("/")
def root():
    return {"status": "ok", "ffmpeg": FFMPEG_BIN}

@app.post("/api/info")
def get_video_info(req_body: VideoRequest):
    url, dl_type = req_body.url, req_body.type

    # YouTube: use mobile client via yt-dlp
    if is_youtube(url):
        if dl_type == "mp3":
            video_id = extract_youtube_id(url)
            if not video_id:
                raise HTTPException(status_code=400, detail="Gecersiz YouTube URL'si")
            # Get title/thumbnail via oEmbed (fast, no bot detection)
            try:
                oe = req.get(f"https://www.youtube.com/oembed?url={url}&format=json", timeout=10)
                oe_data = oe.json() if oe.ok else {}
            except Exception:
                oe_data = {}
            return {
                "title": oe_data.get("title", "YouTube Video"),
                "thumbnail": oe_data.get("thumbnail_url", ""),
                "duration": 0,
                "platform": "youtube",
                "formats": [{"format_id": f"mp3::{video_id}", "ext": "mp3",
                              "resolution": "Yuksek Kalite", "note": "Ses"}]
            }

        # Video: extract info with mobile client
        try:
            with yt_dlp.YoutubeDL(_yt_opts({"skip_download": True})) as ydl:
                info = ydl.extract_info(url, download=False)

            formats = []
            max_h = max(
                (f.get("height", 0) or 0) for f in info.get("formats", [])
                if f.get("vcodec") != "none"
            ) if info.get("formats") else 0

            for h, note, fid in [
                (1080, "FHD", "bestvideo[height<=1080]+bestaudio/best[height<=1080]"),
                (720,  "HD",  "bestvideo[height<=720]+bestaudio/best[height<=720]"),
                (480,  "SD",  "bestvideo[height<=480]+bestaudio/best[height<=480]"),
                (360,  "SD",  "bestvideo[height<=360]+bestaudio/best[height<=360]"),
            ]:
                if max_h >= h:
                    formats.append({"format_id": fid, "ext": "mp4",
                                    "resolution": f"{h}p", "note": note})
            if not formats:
                formats.append({"format_id": "best", "ext": "mp4",
                                 "resolution": "En Iyi", "note": "Standart"})

            return {
                "title": info.get("title", "Unknown"),
                "thumbnail": info.get("thumbnail", ""),
                "duration": info.get("duration", 0),
                "platform": "youtube",
                "formats": formats,
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # Other platforms: yt-dlp direct
    try:
        with yt_dlp.YoutubeDL({**_base_ydl_opts(), "skip_download": True}) as ydl:
            info = ydl.extract_info(url, download=False)
        formats = []
        if dl_type == "mp3":
            formats.append({"format_id": "mp3", "ext": "mp3",
                             "resolution": "Yuksek Kalite", "note": "Ses"})
        else:
            max_h = max(
                (f.get("height", 0) or 0) for f in info.get("formats", [])
                if f.get("vcodec") != "none"
            ) if info.get("formats") else 0
            for h, note in [(1080,"FHD"),(720,"HD"),(480,"SD")]:
                if max_h >= h:
                    formats.append({
                        "format_id": f"bestvideo[height<={h}]+bestaudio/best[height<={h}]",
                        "ext": "mp4", "resolution": f"{h}p", "note": note})
            if not formats:
                formats.append({"format_id": "best", "ext": "mp4",
                                 "resolution": "En Iyi", "note": "Standart"})
        return {"title": info.get("title","Unknown"), "thumbnail": info.get("thumbnail",""),
                "duration": info.get("duration",0), "platform": info.get("extractor","unknown"),
                "formats": formats}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _do_download(job_id: str, url: str, format_id: str, dl_type: str):
    try:
        os.makedirs("./downloads", exist_ok=True)
        filepath = None

        # ── YouTube MP3 via youtube-mp36 ─────────────────────────────────────
        if is_youtube(url) and format_id.startswith("mp3::"):
            video_id = format_id.split("::")[1]
            jobs[job_id]["progress"] = 5
            mp3_url = get_youtube_mp3_url(video_id)
            jobs[job_id]["progress"] = 50
            filename = f"vidfetch_{job_id}.mp3"
            filepath = f"./downloads/{filename}"
            dl_headers = {"User-Agent": "Mozilla/5.0"}
            with req.get(mp3_url, stream=True, timeout=300, headers=dl_headers) as r:
                r.raise_for_status()
                total = int(r.headers.get("content-length", 0))
                done = 0
                with open(filepath, "wb") as f:
                    for chunk in r.iter_content(chunk_size=65536):
                        if chunk:
                            f.write(chunk)
                            done += len(chunk)
                            if total > 0:
                                pct = 50 + round((done / total) * 45)
                                jobs[job_id]["progress"] = min(pct, 95)
            clean_name = filename.replace(f"_{job_id}", "")

        # ── YouTube/Other video via yt-dlp (mobile client for YouTube) ────────
        else:
            def hook(d):
                if d["status"] == "downloading":
                    tot = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
                    dn = d.get("downloaded_bytes", 0)
                    if tot > 0:
                        jobs[job_id]["progress"] = round((dn / tot) * 90)
                elif d["status"] == "finished":
                    jobs[job_id]["progress"] = 95

            base = _yt_opts() if is_youtube(url) else _base_ydl_opts()
            ydl_opts = {
                **base,
                "format": format_id,
                "outtmpl": f"./downloads/{job_id}_%(title)s.%(ext)s",
                "progress_hooks": [hook],
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
                raise Exception("Dosya bulunamadi")
            filepath = files[0]
            clean_name = os.path.basename(filepath).replace(f"{job_id}_", "")

        jobs[job_id].update({"status": "done", "progress": 100,
                              "filepath": filepath, "filename": clean_name})
    except Exception as e:
        jobs[job_id].update({"status": "error", "error": str(e)})


@app.post("/api/download/start")
def start_download(req_body: DownloadRequest):
    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status": "running", "progress": 0, "filepath": None,
                    "filename": None, "error": None}
    threading.Thread(target=_do_download,
                     args=(job_id, req_body.url, req_body.format_id, req_body.type),
                     daemon=True).start()
    return {"job_id": job_id}


@app.get("/api/download/progress/{job_id}")
def download_progress(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    def stream():
        while True:
            job = jobs.get(job_id, {})
            yield f"data: {json.dumps({'status': job.get('status'), 'progress': job.get('progress', 0), 'error': job.get('error')})}\n\n"
            if job.get("status") in ("done", "error"):
                break
            time.sleep(0.5)
    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/api/download/file/{job_id}")
def serve_file(job_id: str, background_tasks: BackgroundTasks):
    job = jobs.get(job_id)
    if not job or job.get("status") != "done":
        raise HTTPException(status_code=404, detail="File not ready")
    fp, fn = job["filepath"], job["filename"]
    background_tasks.add_task(cleanup_file, fp)
    jobs.pop(job_id, None)
    return FileResponse(path=fp, filename=fn, media_type="application/octet-stream")
