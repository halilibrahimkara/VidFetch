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

# Çıkış proxy (Render/VPS IP sık kalıcı bloklanır; çerez yetmeyebilir)
_YTDLP_PROXY = (
    os.environ.get("YTDLP_PROXY", "").strip()
    or os.environ.get("ALL_PROXY", "").strip()
    or os.environ.get("HTTPS_PROXY", "").strip()
    or os.environ.get("HTTP_PROXY", "").strip()
)

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

# yt-dlp: is_authenticated için LOGIN_INFO + (SAPISID veya Secure-*PAPISID) gerekli (_base.py)
_YT_COOKIE_AUDIT = {"bytes": None, "has_login_info": False, "has_sapisid_family": False}
if _COOKIE_FILE and os.path.isfile(_COOKIE_FILE):
    try:
        _YT_COOKIE_AUDIT["bytes"] = os.path.getsize(_COOKIE_FILE)
        _blob = open(_COOKIE_FILE, encoding="utf-8", errors="replace").read()
        _YT_COOKIE_AUDIT["has_login_info"] = "LOGIN_INFO" in _blob and ".youtube.com" in _blob
        _YT_COOKIE_AUDIT["has_sapisid_family"] = any(
            p in _blob
            for p in ("\tSAPISID\t", "\t__Secure-1PAPISID\t", "\t__Secure-3PAPISID\t")
        )
    except OSError:
        pass

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
_YT_PLAYER_SKIP_ENV = os.environ.get("YOUTUBE_PLAYER_SKIP", "").strip()


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


def _youtube_jobs_error_hint(msg: str) -> str:
    low = msg.lower()
    if "youtube" not in low:
        return msg
    if "sign in" not in low and "not a bot" not in low:
        return msg
    if _YTDLP_PROXY:
        return msg
    return (
        f"{msg} | YouTube sık sık VPS/DC çıkış IP'sini bloklar (çerez doğru da olsa). "
        "Render'da HTTPS_PROXY/YTDLP_PROXY ile rezidans proxy deneyin veya "
        "https://github.com/yt-dlp/yt-dlp/wiki/PO-Token-Guide"
    )


def _youtube_err_recoverable(msg: str) -> bool:
    s = msg.lower()
    needles = ("sign in", "not a bot", "login required", "--cookies-from-browser", "authentication")
    return any(n in s for n in needles)


def _default_youtube_extractor_dict() -> dict:
    ext_yt = {
        "player_client": _youtube_player_clients(),
        "skip": ["translated_subs"],
    }
    if _YT_PLAYER_SKIP_ENV:
        ext_yt["player_skip"] = [
            x.strip()
            for x in re.split(r"[\s,]+", _YT_PLAYER_SKIP_ENV)
            if x.strip()
        ]
    elif _HAS_YT_COOKIES:
        ext_yt["player_skip"] = ["webpage"]
    if _YT_PO_TOKEN:
        ext_yt["po_token"] = _YT_PO_TOKEN
    return ext_yt


def _youtube_extractor_retry_chain() -> list[tuple[dict, bool]]:
    """
    (youtube extractor kwargs, pass_cookies) — datacenter blokları için sırayla dene.
    """
    po_kw = {}
    if _YT_PO_TOKEN:
        po_kw = {"po_token": _YT_PO_TOKEN}

    clients = list(_youtube_player_clients())
    out: list[tuple[dict, bool]] = []
    seen_sig: set[tuple[str, bool]] = set()

    def _add(ext: dict, cookies: bool) -> None:
        sig = (json.dumps(ext, sort_keys=True), cookies)
        if sig in seen_sig:
            return
        seen_sig.add(sig)
        out.append((dict(ext), cookies))

    # 1) Ortam değişkenlerine göre varsayılan (çerez + player_skip vb.)
    _add(_default_youtube_extractor_dict(), True)

    # 2) Çerezliyken tam watch sayfası (player_skip kapalı — bazı oturumlarda VPS'te gerekebiliyor)
    if _HAS_YT_COOKIES and not _YT_PLAYER_SKIP_ENV:
        _add({"player_client": clients, "skip": ["translated_subs"], **po_kw}, True)

    # 3–6) android_vr + çeşitli cookie kombinasyonları
    vr_base = {"player_client": ["android_vr"], "skip": ["translated_subs"], **po_kw}
    _add({**vr_base, "player_skip": ["webpage"]}, True)
    _add({**vr_base}, True)

    vr_guest_page = {"player_client": ["android_vr"], "skip": ["translated_subs"], **po_kw, "player_skip": ["webpage"]}
    _add(vr_guest_page, False)
    _add(dict(vr_base), False)

    return out


def _yt_opts(
    extra: dict | None = None,
    *,
    youtube_extractor: dict | None = None,
    pass_cookies: bool = True,
):
    """yt-dlp seçenekleri; youtube_extractor verilirse varsayılan YouTube blok yerine kullanılır."""
    ext_yt = (
        youtube_extractor
        if youtube_extractor is not None
        else _default_youtube_extractor_dict()
    )
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
    if _YTDLP_PROXY:
        opts["proxy"] = _YTDLP_PROXY
    if pass_cookies:
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
    if _YTDLP_PROXY:
        opts["proxy"] = _YTDLP_PROXY
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

if _HAS_YT_COOKIES and _COOKIE_FILE:
    if not (
        _YT_COOKIE_AUDIT.get("has_login_info")
        and _YT_COOKIE_AUDIT.get("has_sapisid_family")
    ):
        _log.warning(
            "YouTube cookies lack LOGIN_INFO/SAPISID pair yt-dlp needs; re-export cookies on youtube.com "
            "(Get cookies.txt LOCALLY)."
        )


@app.get("/")
def root():
    sid_ok = (
        None
        if _COOKIES_FROM_BROWSER and not (_COOKIE_FILE and os.path.isfile(_COOKIE_FILE))
        else bool(
            _YT_COOKIE_AUDIT.get("has_login_info")
            and _YT_COOKIE_AUDIT.get("has_sapisid_family")
        )
    )
    return {
        "status": "ok",
        "ffmpeg": FFMPEG_BIN,
        "youtube_auth_cookies": _HAS_YT_COOKIES,
        "youtube_sid_cookies_complete": sid_ok,
        "youtube_cookie_file_bytes": _YT_COOKIE_AUDIT.get("bytes"),
        "youtube_player_clients_override": bool(_YT_PLAYERS_ENV),
        "youtube_po_token_set": bool(_YT_PO_TOKEN),
        "youtube_player_skip": (
            [x.strip() for x in re.split(r"[\s,]+", _YT_PLAYER_SKIP_ENV) if x.strip()]
            if _YT_PLAYER_SKIP_ENV
            else (["webpage"] if _HAS_YT_COOKIES else [])
        ),
        "youtube_extractor_retry_attempts": len(_youtube_extractor_retry_chain()),
        "youtube_downstream_proxy": bool(_YTDLP_PROXY),
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

        # Video: extract info with yt-dlp ( sırayla farklı istemci/çerez kombinasyonu )
        try:
            info = None
            last_err = None
            for yt_ext, cookie_ok in _youtube_extractor_retry_chain():
                try:
                    with yt_dlp.YoutubeDL(
                        _yt_opts(
                            {"skip_download": True},
                            youtube_extractor=yt_ext,
                            pass_cookies=cookie_ok,
                        )
                    ) as ydl:
                        info = ydl.extract_info(url, download=False)
                    break
                except Exception as ei:
                    last_err = ei
                    if _youtube_err_recoverable(str(ei)):
                        continue
                    raise HTTPException(status_code=500, detail=str(ei)) from ei
            if info is None:
                raise HTTPException(
                    status_code=500,
                    detail=str(last_err) if last_err else "YouTube bilgisi alinamadi",
                )

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

            last_exc = None
            for yt_ext, cookie_ok in _youtube_extractor_retry_chain():
                try:
                    ydl_opts = {
                        **_yt_opts(
                            youtube_extractor=yt_ext,
                            pass_cookies=cookie_ok,
                        ),
                        "format": "bestaudio[ext=m4a]/bestaudio/ba/b",
                        "outtmpl": f"./downloads/{job_id}_%(title)s.%(ext)s",
                        "progress_hooks": [hook],
                        "postprocessors": [{
                            "key": "FFmpegExtractAudio",
                            "preferredcodec": "mp3",
                            "preferredquality": "192",
                        }],
                    }
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        ydl.extract_info(url, download=True)
                    break
                except Exception as ei:
                    last_exc = ei
                    if _youtube_err_recoverable(str(ei)):
                        continue
                    raise
            else:
                if last_exc:
                    raise last_exc

            files = glob.glob(f"./downloads/{job_id}_*")
            if not files:
                raise Exception("Dosya indirilemedi")
            filepath = files[0]
            clean_name = os.path.basename(filepath).replace(f"{job_id}_", "")


        # ── YouTube mp4/other veya diğer platformlar ──────────────────────────
        else:
            def hook(d):
                if d["status"] == "downloading":
                    tot = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
                    dn = d.get("downloaded_bytes", 0)
                    if tot > 0:
                        jobs[job_id]["progress"] = round((dn / tot) * 90)
                elif d["status"] == "finished":
                    jobs[job_id]["progress"] = 95

            if is_youtube(url):
                last_exc = None
                for yt_ext, cookie_ok in _youtube_extractor_retry_chain():
                    try:
                        base = _yt_opts(
                            youtube_extractor=yt_ext,
                            pass_cookies=cookie_ok,
                        )
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
                        break
                    except Exception as ei:
                        last_exc = ei
                        if _youtube_err_recoverable(str(ei)):
                            continue
                        raise
                else:
                    if last_exc:
                        raise last_exc
            else:
                ydl_opts = {
                    **_base_ydl_opts(),
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
        jobs[job_id].update({"status": "error", "error": _youtube_jobs_error_hint(str(e))})


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
