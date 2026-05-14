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
import base64 as _cookie_b64mod
import logging

_log = logging.getLogger("uvicorn.error")

# ── FFmpeg path ───────────────────────────────────────────────────────────────
_FFMPEG_EXE = shutil.which("ffmpeg")
FFMPEG_BIN = os.path.dirname(_FFMPEG_EXE) if _FFMPEG_EXE else ""

# ── Cookies (YouTube bot / giriş ekranı için) ─────────────────────────────────
_COOKIE_FILE = None
_COOKIES_FROM_BROWSER = None


def _decoded_bytes_from_screen_pasted_b64(raw: str) -> bytes | None:
    """Render / pano yapıştırmalarında boşluk ve url-safe karakter için."""
    compact = "".join((raw or "").split())
    if not compact:
        return None
    pad = (-len(compact)) % 4
    padded = compact + ("=" * pad if pad else "")
    for dec in (_cookie_b64mod.urlsafe_b64decode, _cookie_b64mod.b64decode):
        try:
            return dec(padded, validate=False)
        except Exception:
            continue
    return None


_cookie_path = os.environ.get("YOUTUBE_COOKIES_FILE", "").strip()
if _cookie_path:
    _cp = os.path.expanduser(os.path.expandvars(_cookie_path))
    if os.path.isfile(_cp):
        _COOKIE_FILE = os.path.abspath(_cp)

_browser = os.environ.get("YOUTUBE_COOKIES_FROM_BROWSER", "").strip()
if _browser:
    parts = [p.strip() for p in _browser.split(",") if p.strip()]
    if parts:
        _COOKIES_FROM_BROWSER = tuple(parts)

if not _COOKIE_FILE and not _COOKIES_FROM_BROWSER:
    _cookie_b64 = os.environ.get("YOUTUBE_COOKIES_B64", "").strip()
    if _cookie_b64:
        _bin = _decoded_bytes_from_screen_pasted_b64(_cookie_b64)
        try:
            if _bin:
                _cc = _bin.decode("utf-8")
                if "# Netscape" not in _cc and ".youtube.com" not in _cc:
                    _log.warning(
                        "YOUTUBE_COOKIES_B64 decodes but looks unlike a Netscape cookie file;"
                        " export youtube.com cookies again."
                    )
                _tmp = tempfile.NamedTemporaryFile(
                    mode="w", suffix=".txt", delete=False, encoding="utf-8"
                )
                _tmp.write(_cc)
                _tmp.close()
                _COOKIE_FILE = _tmp.name
        except Exception as ex:
            _log.warning("YOUTUBE_COOKIES_B64 could not be decoded: %s", ex)

_HAS_YT_COOKIES = bool(_COOKIE_FILE or _COOKIES_FROM_BROWSER)
if os.environ.get("YOUTUBE_COOKIES_B64", "").strip() and not _HAS_YT_COOKIES:
    _log.warning("YOUTUBE_COOKIES_B64 set but decoding failed — YouTube bot errors likely.")

# ── RapidAPI (MP3 only via youtube-mp36) ─────────────────────────────────────
RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY", "").strip()

def is_youtube(url: str) -> bool:
    return "youtube.com" in url or "youtu.be" in url

def extract_youtube_id(url: str) -> str:
    m = re.search(r'(?:youtu\.be/|[?&]v=)([a-zA-Z0-9_-]{11})', url)
    return m.group(1) if m else None

# ── YouTube MP3 via youtube-mp36 (CDN-hosted) ─────────────────────────────────

# ── yt-dlp helpers ────────────────────────────────────────────────────────────
# android_vr: birçok müzik klibinde GVS için PO şartı yok · web_safari: bazı akışlar HLS (wiki karşılaştırması)
# NOT: VPS IP'de sırayı "web" ile başlatmak LOGIN_REQUIRED ("bot doğrula") daha sık tetikliyor — çerez doğru da olsa
_YT_PLAYERS_ENV = os.environ.get("YOUTUBE_PLAYER_CLIENTS", "").strip()
_YT_PO_TOKEN = os.environ.get("YOUTUBE_PO_TOKEN", "").strip()


def _youtube_player_clients() -> list:
    if _YT_PLAYERS_ENV:
        return [
            p.strip()
            for p in re.split(r"[\s,]+", _YT_PLAYERS_ENV)
            if p.strip()
        ]
    return ["android_vr", "android", "ios", "web_creator", "web_safari", "web"]


def _yt_merge_format(cap_h: int) -> str:
    """yükseklik tavanı için birleştirme; storyboard/format uyuşmazlığına karşı sıkı + gevşek yedek."""
    return "/".join(
        [
            f"bestvideo[height<={cap_h}][vcodec!=none]+bestaudio[acodec!=none]",
            f"bestvideo[height<={cap_h}]+bestaudio",
            f"best[height<={cap_h}][vcodec!=none][acodec!=none]",
            f"best[height<={cap_h}]",
            "bestvideo[vcodec!=none]+bestaudio[acodec!=none]",
            "bestvideo+bestaudio",
            "best",
        ]
    )


def _yt_opts(extra: dict = None) -> dict:
    """yt-dlp options for YouTube with mobile client fallbacks."""
    ext_yt = {
        "player_client": _youtube_player_clients(),
        "skip": ["translated_subs"],
    }
    if _YT_PO_TOKEN:
        ext_yt["po_token"] = _YT_PO_TOKEN
    opts = {
        "quiet": True,
        "no_color": True,
        "noplaylist": True,
        "extractor_args": {
            "youtube": ext_yt,
        },
    }
    if FFMPEG_BIN:
        opts["ffmpeg_location"] = FFMPEG_BIN
    if _COOKIES_FROM_BROWSER:
        opts["cookiesfrombrowser"] = _COOKIES_FROM_BROWSER
    elif _COOKIE_FILE:
        opts["cookiefile"] = _COOKIE_FILE
    if extra:
        opts.update(extra)
    return opts

def _base_ydl_opts() -> dict:
    """For non-YouTube platforms (no special client args needed)."""
    opts = {"quiet": True, "no_color": True, "noplaylist": True}
    if FFMPEG_BIN:
        opts["ffmpeg_location"] = FFMPEG_BIN
    if _COOKIES_FROM_BROWSER:
        opts["cookiesfrombrowser"] = _COOKIES_FROM_BROWSER
    elif _COOKIE_FILE:
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
    return {
        "status": "ok",
        "ffmpeg": FFMPEG_BIN,
        "youtube_auth_cookies": _HAS_YT_COOKIES,
        "youtube_player_clients_override": bool(_YT_PLAYERS_ENV),
        "youtube_po_token_set": bool(_YT_PO_TOKEN),
    }

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

            for h, note in [
                (1080, "FHD"),
                (720, "HD"),
                (480, "SD"),
                (360, "SD"),
            ]:
                if max_h >= h:
                    formats.append({"format_id": _yt_merge_format(h), "ext": "mp4",
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
            for h, note in [(1080,"FHD"),(720,"HD"),(480,"SD"),(360,"SD")]:
                if max_h >= h:
                    formats.append({
                        "format_id": _yt_merge_format(h),
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

        if is_youtube(url) and format_id.startswith("mp3::"):
            # YouTube MP3 via our own yt-dlp (uses iOS bypass)
            def hook(d):
                if d["status"] == "downloading":
                    tot = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
                    dn = d.get("downloaded_bytes", 0)
                    if tot > 0:
                        jobs[job_id]["progress"] = round((dn / tot) * 90)
                elif d["status"] == "finished":
                    jobs[job_id]["progress"] = 95

            ydl_opts = {
                **_yt_opts(),
                "format": "bestaudio[ext=m4a]/bestaudio/ba/b",
                "outtmpl": f"./downloads/{job_id}_%(title)s.%(ext)s",
                "progress_hooks": [hook],
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }]
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.extract_info(url, download=True)

            files = glob.glob(f"./downloads/{job_id}_*")
            if not files:
                raise Exception("Dosya indirilemedi")
            filepath = files[0]
            clean_name = os.path.basename(filepath).replace(f"{job_id}_", "")


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
