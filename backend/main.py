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
import subprocess
import tempfile
import requests as req

# ── FFmpeg path ───────────────────────────────────────────────────────────────
_FFMPEG_EXE = shutil.which("ffmpeg")
FFMPEG_BIN = os.path.dirname(_FFMPEG_EXE) if _FFMPEG_EXE else ""

# ── Cookies (yt-dlp fallback for non-YT) ─────────────────────────────────────
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

# ── Invidious instances (video proxy, no IP lock) ────────────────────────────
INVIDIOUS_INSTANCES = [
    "https://inv.thepixora.com",
    "https://inv.nadeko.net",
    "https://invidious.nerdvpn.de",
]

def is_youtube(url: str) -> bool:
    return "youtube.com" in url or "youtu.be" in url

def extract_youtube_id(url: str) -> str:
    m = re.search(r'(?:youtu\.be/|[?&]v=)([a-zA-Z0-9_-]{11})', url)
    return m.group(1) if m else None

# ── YouTube MP3 via youtube-mp36 (CDN-hosted, no IP lock) ────────────────────
def get_youtube_mp3_url(video_id: str) -> str:
    if not RAPIDAPI_KEY:
        raise Exception("RAPIDAPI_KEY eksik! Render Environment'a ekleyin.")
    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": "youtube-mp36.p.rapidapi.com",
    }
    for attempt in range(40):  # poll up to ~2 min
        try:
            r = req.get("https://youtube-mp36.p.rapidapi.com/dl",
                        params={"id": video_id}, headers=headers, timeout=30)
            if r.ok:
                d = r.json()
                if d.get("status") == "ok":
                    return d["link"]
                if d.get("status") == "fail":
                    raise Exception(f"MP3 hatasi: {d.get('msg','')}")
                # status == "processing" — keep polling
        except Exception as e:
            if "hatasi" in str(e):
                raise
        time.sleep(3)
    raise Exception("MP3 donusumu zaman asimina ugradi (2dk). youtube-mp36 API'sine RapidAPI'den abone oldugunuzdan emin olun.")

# ── YouTube video info via Invidious (proxied URLs) ───────────────────────────
def get_youtube_info_invidious(video_id: str, dl_type: str) -> dict:
    last_err = "Invidious instance bulunamadi"
    for instance in INVIDIOUS_INSTANCES:
        try:
            r = req.get(f"{instance}/api/v1/videos/{video_id}",
                        params={"local": "true"}, timeout=15)
            if not r.ok:
                last_err = f"{instance}: HTTP {r.status_code}"
                continue
            data = r.json()
            formats = []

            if dl_type == "mp3":
                formats.append({
                    "format_id": f"mp3::{video_id}",
                    "ext": "mp3", "resolution": "Yuksek Kalite", "note": "Ses"
                })
            else:
                # Progressive streams (video+audio merged) — simpler, no mux needed
                for f in sorted(data.get("formatStreams", []),
                                key=lambda x: x.get("height", 0), reverse=True):
                    if f.get("url"):
                        h = f.get("height", 0) or f.get("qualityLabel", "?")
                        label = f"{h}p" if isinstance(h, int) else str(h)
                        formats.append({
                            "format_id": f["url"] + "|",
                            "ext": "mp4", "resolution": label, "note": "Video"
                        })

                # Adaptive formats for higher quality (needs mux)
                ad_videos = sorted(
                    [f for f in data.get("adaptiveFormats", [])
                     if f.get("type", "").startswith("video/mp4") and f.get("url")],
                    key=lambda x: x.get("height", 0), reverse=True
                )
                ad_audios = [f for f in data.get("adaptiveFormats", [])
                             if f.get("type", "").startswith("audio/") and f.get("url")]
                best_audio_url = ad_audios[0]["url"] if ad_audios else ""

                seen = {f["resolution"] for f in formats}
                for v in ad_videos:
                    h = v.get("height", 0)
                    label = f"{h}p"
                    if label not in seen and h:
                        seen.add(label)
                        formats.append({
                            "format_id": f"{v['url']}|{best_audio_url}",
                            "ext": "mp4", "resolution": label, "note": "Video"
                        })

                if not formats:
                    formats.append({"format_id": "best|", "ext": "mp4",
                                    "resolution": "360p", "note": "Video"})

            thumbnails = data.get("videoThumbnails", [])
            thumb = thumbnails[0]["url"] if thumbnails else f"{instance}/vi/{video_id}/hqdefault.jpg"

            return {
                "title": data.get("title", "Unknown"),
                "thumbnail": thumb,
                "duration": data.get("lengthSeconds", 0),
                "platform": "youtube",
                "formats": formats,
            }
        except Exception as e:
            last_err = str(e)
            continue
    raise Exception(f"YouTube bilgisi alinamadi: {last_err}")

def get_youtube_info(url: str, dl_type: str) -> dict:
    video_id = extract_youtube_id(url)
    if not video_id:
        raise Exception("Gecersiz YouTube URL'si")
    return get_youtube_info_invidious(video_id, dl_type)

# ── yt-dlp base options ───────────────────────────────────────────────────────
def _base_ydl_opts() -> dict:
    opts = {"quiet": True, "no_color": True}
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
    if is_youtube(url):
        try:
            return get_youtube_info(url, dl_type)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # Other platforms: yt-dlp
    try:
        with yt_dlp.YoutubeDL({**_base_ydl_opts(), "skip_download": True, "noplaylist": True}) as ydl:
            info = ydl.extract_info(url, download=False)
        formats = []
        if dl_type == "mp3":
            formats.append({"format_id": "mp3", "ext": "mp3", "resolution": "Yuksek Kalite", "note": "Ses"})
        else:
            max_h = max((f.get("height", 0) or 0) for f in info.get("formats", [])
                        if f.get("vcodec") != "none") if info.get("formats") else 0
            for h, note in [(1080,"FHD"),(720,"HD"),(480,"SD")]:
                if max_h >= h:
                    formats.append({"format_id": f"bestvideo[height<={h}]+bestaudio/best[height<={h}]",
                                    "ext": "mp4", "resolution": f"{h}p", "note": note})
            if not formats:
                formats.append({"format_id": "best", "ext": "mp4", "resolution": "En Iyi", "note": "Standart"})
        return {"title": info.get("title","Unknown"), "thumbnail": info.get("thumbnail",""),
                "duration": info.get("duration",0), "platform": info.get("extractor","unknown"),
                "formats": formats}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def _stream_download(url: str, filepath: str, job_id: str, progress_range: tuple):
    """Stream a URL to a file, updating job progress."""
    start_pct, end_pct = progress_range
    dl_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.youtube.com/",
    }
    with req.get(url, stream=True, timeout=300, headers=dl_headers) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        done = 0
        with open(filepath, "wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)
                    done += len(chunk)
                    if total > 0:
                        pct = start_pct + round((done / total) * (end_pct - start_pct))
                        jobs[job_id]["progress"] = min(pct, end_pct)

def _do_download(job_id: str, url: str, format_id: str, dl_type: str):
    try:
        os.makedirs("./downloads", exist_ok=True)
        filepath = None

        if is_youtube(url):
            # MP3 via youtube-mp36
            if format_id.startswith("mp3::"):
                video_id = format_id.split("::")[1]
                jobs[job_id]["progress"] = 5
                mp3_url = get_youtube_mp3_url(video_id)
                jobs[job_id]["progress"] = 50
                filename = f"vidfetch_{job_id}.mp3"
                filepath = f"./downloads/{filename}"
                _stream_download(mp3_url, filepath, job_id, (50, 95))
                clean_name = filename.replace(f"_{job_id}", "")

            else:
                # Video: format_id = "video_url|audio_url"
                parts = format_id.split("|", 1)
                video_url, audio_url = parts[0], (parts[1] if len(parts) > 1 else "")

                filename = f"vidfetch_{job_id}.mp4"
                filepath = f"./downloads/{filename}"
                vid_path = f"./downloads/{job_id}_v.mp4"

                _stream_download(video_url, vid_path, job_id, (10, 55))

                if audio_url:
                    aud_path = f"./downloads/{job_id}_a.m4a"
                    jobs[job_id]["progress"] = 60
                    _stream_download(audio_url, aud_path, job_id, (60, 80))
                    jobs[job_id]["progress"] = 85
                    ffmpeg = shutil.which("ffmpeg") or os.path.join(FFMPEG_BIN, "ffmpeg")
                    result = subprocess.run(
                        [ffmpeg, "-y", "-i", vid_path, "-i", aud_path, "-c", "copy", filepath],
                        capture_output=True, timeout=300)
                    os.remove(vid_path); os.remove(aud_path)
                    if result.returncode != 0:
                        raise Exception(f"ffmpeg hatasi: {result.stderr.decode()[:200]}")
                else:
                    shutil.move(vid_path, filepath)

                clean_name = filename.replace(f"_{job_id}", "")

        else:
            def hook(d):
                if d["status"] == "downloading":
                    tot = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
                    dn = d.get("downloaded_bytes", 0)
                    if tot > 0:
                        jobs[job_id]["progress"] = round((dn/tot)*90)
                elif d["status"] == "finished":
                    jobs[job_id]["progress"] = 95

            opts = {**_base_ydl_opts(), "format": format_id,
                    "outtmpl": f"./downloads/{job_id}_%(title)s.%(ext)s",
                    "noplaylist": True, "progress_hooks": [hook],
                    "merge_output_format": "mp4" if dl_type == "mp4" else None}
            if dl_type == "mp3":
                opts["postprocessors"] = [{"key": "FFmpegExtractAudio",
                                           "preferredcodec": "mp3", "preferredquality": "192"}]
            with yt_dlp.YoutubeDL(opts) as ydl:
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
    jobs[job_id] = {"status": "running", "progress": 0, "filepath": None, "filename": None, "error": None}
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
            yield f"data: {json.dumps({'status': job.get('status'), 'progress': job.get('progress',0), 'error': job.get('error')})}\n\n"
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
