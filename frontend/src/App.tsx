import { useState } from 'react'
import './index.css'

const API = import.meta.env.VITE_API_URL ?? 'http://127.0.0.1:8000'
const LOCAL_API = import.meta.env.VITE_LOCAL_API_URL ?? ''  // Local backend for YouTube MP4

function isYouTube(url: string) {
  return url.includes('youtube.com') || url.includes('youtu.be')
}

function getApiBase(url: string, type: string) {
  // YouTube video → use local backend if configured
  if (isYouTube(url) && type === 'mp4' && LOCAL_API) return LOCAL_API
  return API
}

interface VideoFormat {
  format_id: string
  ext: string
  resolution: string
  note: string
}

interface VideoInfo {
  title: string
  thumbnail: string
  duration: number
  platform: string
  formats: VideoFormat[]
}

// SVG Platform Icons
const YoutubeIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="#ef4444">
    <path d="M23.5 6.2a3 3 0 0 0-2.1-2.1C19.5 3.5 12 3.5 12 3.5s-7.5 0-9.4.6A3 3 0 0 0 .5 6.2C0 8.1 0 12 0 12s0 3.9.5 5.8a3 3 0 0 0 2.1 2.1C4.5 20.5 12 20.5 12 20.5s7.5 0 9.4-.6a3 3 0 0 0 2.1-2.1C24 15.9 24 12 24 12s0-3.9-.5-5.8zM9.7 15.5v-7l6.3 3.5-6.3 3.5z"/>
  </svg>
)

const InstagramIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="url(#ig-grad)">
    <defs>
      <linearGradient id="ig-grad" x1="0%" y1="100%" x2="100%" y2="0%">
        <stop offset="0%" stopColor="#f09433"/>
        <stop offset="25%" stopColor="#e6683c"/>
        <stop offset="50%" stopColor="#dc2743"/>
        <stop offset="75%" stopColor="#cc2366"/>
        <stop offset="100%" stopColor="#bc1888"/>
      </linearGradient>
    </defs>
    <path d="M12 2.2c3.2 0 3.6 0 4.9.1 3.3.1 4.8 1.7 4.9 4.9.1 1.3.1 1.6.1 4.8 0 3.2 0 3.6-.1 4.8-.1 3.2-1.7 4.8-4.9 4.9-1.3.1-1.6.1-4.9.1-3.2 0-3.6 0-4.8-.1-3.3-.1-4.8-1.7-4.9-4.9C2.2 15.6 2.2 15.3 2.2 12c0-3.2 0-3.6.1-4.8C2.4 3.9 4 2.3 7.2 2.2c1.3-.1 1.6-.1 4.8-.1zM12 0C8.7 0 8.3 0 7.1.1 2.7.3.3 2.7.1 7.1.0 8.3 0 8.7 0 12c0 3.3 0 3.7.1 4.9.2 4.4 2.6 6.8 7 7C8.3 24 8.7 24 12 24c3.3 0 3.7 0 4.9-.1 4.4-.2 6.8-2.6 7-7 .1-1.2.1-1.6.1-4.9 0-3.3 0-3.7-.1-4.9C23.7 2.7 21.3.3 16.9.1 15.7 0 15.3 0 12 0zm0 5.8a6.2 6.2 0 1 0 0 12.4A6.2 6.2 0 0 0 12 5.8zM12 16a4 4 0 1 1 0-8 4 4 0 0 1 0 8zm6.4-11.8a1.44 1.44 0 1 0 0 2.88 1.44 1.44 0 0 0 0-2.88z"/>
  </svg>
)

const XIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="white">
    <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-4.714-6.231-5.401 6.231H2.744l7.73-8.835L1.254 2.25H8.08l4.261 5.636 5.903-5.636zm-1.161 17.52h1.833L7.084 4.126H5.117z"/>
  </svg>
)

const TikTokIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="white">
    <path d="M19.59 6.69a4.83 4.83 0 0 1-3.77-4.25V2h-3.45v13.67a2.89 2.89 0 0 1-2.88 2.5 2.89 2.89 0 0 1-2.89-2.89 2.89 2.89 0 0 1 2.89-2.89c.28 0 .54.04.79.1V9.01a6.33 6.33 0 0 0-.79-.05A6.34 6.34 0 0 0 3.15 15.3a6.34 6.34 0 0 0 6.34 6.34 6.34 6.34 0 0 0 6.34-6.34V8.69a8.18 8.18 0 0 0 4.79 1.52V6.78a4.85 4.85 0 0 1-1.03-.09z"/>
  </svg>
)

const FacebookIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="#1877f2">
    <path d="M24 12.07C24 5.41 18.63 0 12 0S0 5.41 0 12.07C0 18.1 4.39 23.1 10.13 24v-8.44H7.08v-3.49h3.04V9.41c0-3.02 1.8-4.7 4.54-4.7 1.31 0 2.68.24 2.68.24v2.97h-1.51c-1.49 0-1.95.93-1.95 1.88v2.27h3.32l-.53 3.49h-2.79V24C19.61 23.1 24 18.1 24 12.07z"/>
  </svg>
)

const VideoIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <rect x="2" y="3" width="20" height="14" rx="2" />
    <polygon points="8 21 16 21 12 17" />
  </svg>
)

const MusicIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M9 18V5l12-2v13" />
    <circle cx="6" cy="18" r="3" />
    <circle cx="18" cy="16" r="3" />
  </svg>
)

const PLATFORMS = [
  { name: 'YouTube',    Icon: YoutubeIcon },
  { name: 'Instagram',  Icon: InstagramIcon },
  { name: 'X (Twitter)',Icon: XIcon },
  { name: 'TikTok',    Icon: TikTokIcon },
  { name: 'Facebook',  Icon: FacebookIcon },
]

function formatDuration(seconds: number) {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = seconds % 60
  if (h > 0) return `${h}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`
  return `${m}:${String(s).padStart(2,'0')}`
}

function App() {
  const [url, setUrl] = useState('')
  const [downloadType, setDownloadType] = useState<'mp4' | 'mp3'>('mp4')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [info, setInfo] = useState<VideoInfo | null>(null)
  const [downloading, setDownloading] = useState(false)
  const [downloadProgress, setDownloadProgress] = useState(0)
  const [downloadStatus, setDownloadStatus] = useState('')

  const handleFetch = async () => {
    if (!url.trim()) return
    setLoading(true); setError(''); setInfo(null)
    try {
      const apiBase = getApiBase(url, downloadType)
      const res = await fetch(`${apiBase}/api/info`, {
        method: 'POST',
        headers: { 
          'Content-Type': 'application/json',
          'Bypass-Tunnel-Reminder': 'true'
        },
        body: JSON.stringify({ url, type: downloadType }),
      })
      if (!res.ok) { const e = await res.json(); throw new Error(e.detail || 'Video bilgisi alınamadı') }
      setInfo(await res.json())
    } catch (err: any) {
      // If YouTube MP4 + local backend not reachable, show helpful message
      if (isYouTube(url) && downloadType === 'mp4' && LOCAL_API) {
        setError('Yerel backend çalışmıyor. baslat.bat dosyasını çalıştırın, sonra tekrar deneyin.')
      } else {
        setError(err.message)
      }
    }
    finally { setLoading(false) }
  }

  const handleDownload = async (format_id: string) => {
    setDownloading(true); setDownloadProgress(0); setDownloadStatus('Başlatılıyor...')
    const apiBase = getApiBase(url, downloadType)
    try {
      const startRes = await fetch(`${apiBase}/api/download/start`, {
        method: 'POST',
        headers: { 
          'Content-Type': 'application/json',
          'Bypass-Tunnel-Reminder': 'true'
        },
        body: JSON.stringify({ url, format_id, type: downloadType }),
      })
      if (!startRes.ok) throw new Error('İndirme başlatılamadı')
      const { job_id } = await startRes.json()

      await new Promise<void>((resolve, reject) => {
        const es = new EventSource(`${apiBase}/api/download/progress/${job_id}`)
        es.onmessage = (e) => {
          const d = JSON.parse(e.data)
          setDownloadProgress(d.progress)
          if (d.progress < 90) setDownloadStatus(`İndiriliyor... %${d.progress}`)
          else if (d.progress < 100) setDownloadStatus('Birleştiriliyor...')
          else setDownloadStatus('Tamamlandı!')
          if (d.status === 'done') { es.close(); resolve() }
          else if (d.status === 'error') { es.close(); reject(new Error(d.error)) }
        }
        es.onerror = () => { es.close(); reject(new Error('Sunucu bağlantısı kesildi')) }
      })

      window.location.href = `${apiBase}/api/download/file/${job_id}`
      setTimeout(() => { setDownloading(false); setDownloadProgress(0); setDownloadStatus('') }, 2000)
    } catch (err: any) {
      setError(err.message); setDownloading(false); setDownloadProgress(0); setDownloadStatus('')
    }
  }

  return (
    <>
      <div className="bg-canvas" aria-hidden="true">
        <div className="bg-blob bg-blob-1" />
        <div className="bg-blob bg-blob-2" />
        <div className="bg-blob bg-blob-3" />
      </div>

      <div className="page-wrapper">
        <header className="site-header">
          <a href="/" className="logo-link">
            <div className="logo-icon">
              <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 14.5v-9l6 4.5-6 4.5z"/>
              </svg>
            </div>
            <span className="logo-text">VidFetch</span>
          </a>
        </header>

        <main className="app-container">
          {/* Hero */}
          <section className="hero">
            <div className="hero-badge">
              <svg width="10" height="10" viewBox="0 0 10 10"><circle cx="5" cy="5" r="5" fill="#22c55e"/></svg>
              Ücretsiz &amp; Reklamsız
            </div>
            <h1>Videoları <span>Yüksek Kalitede</span><br />İndir</h1>
            <p className="hero-sub">
              Binlerce platformdan MP4 ve MP3 formatında,<br/>gerçek çözünürlükte indir. Kayıt yok. Limit yok.
            </p>
            <div className="platform-badges">
              {PLATFORMS.map(({ name, Icon }) => (
                <div key={name} className="platform-badge">
                  <Icon />
                  <span>{name}</span>
                </div>
              ))}
            </div>
          </section>

          {/* Type Selector */}
          <div className="type-selector">
            <label className={`type-label ${downloadType === 'mp4' ? 'active' : ''}`}>
              <input type="radio" name="type" value="mp4"
                checked={downloadType === 'mp4'}
                onChange={() => { setDownloadType('mp4'); setInfo(null) }}
              />
              <VideoIcon />
              <span>MP4 <em>Video</em></span>
            </label>
            <label className={`type-label ${downloadType === 'mp3' ? 'active' : ''}`}>
              <input type="radio" name="type" value="mp3"
                checked={downloadType === 'mp3'}
                onChange={() => { setDownloadType('mp3'); setInfo(null) }}
              />
              <MusicIcon />
              <span>MP3 <em>Ses</em></span>
            </label>
          </div>

          {/* Search */}
          <div className="search-box">
            <div className="search-input-wrap">
              <svg className="search-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/>
                <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>
              </svg>
              <input
                type="text" className="search-input"
                placeholder="Video linkini buraya yapıştır..."
                value={url}
                onChange={e => setUrl(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && handleFetch()}
              />
            </div>
            <button className="fetch-btn" onClick={handleFetch} disabled={loading || !url.trim() || downloading}>
              {loading ? <div className="spinner" /> : (
                <>
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                    <circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>
                  </svg>
                  Getir
                </>
              )}
            </button>
          </div>

          {/* Error */}
          {error && (
            <div className="error-box">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
              <span>{error}</span>
            </div>
          )}

          {/* Progress */}
          {downloading && (
            <div className="progress-card">
              <div className="progress-header">
                <div className={`progress-icon-wrap ${downloadProgress >= 100 ? 'done' : ''}`}>
                  {downloadProgress >= 100
                    ? <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="20 6 9 17 4 12"/></svg>
                    : <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 2v8M12 22v-4M4.93 4.93l5.66 5.66M18.36 18.36l-2.83-2.83M2 12h8M22 12h-4M4.93 19.07l5.66-5.66M18.36 5.64l-2.83 2.83"/></svg>
                  }
                </div>
                <span className="progress-label">{downloadStatus}</span>
                <span className="progress-pct">{downloadProgress}%</span>
              </div>
              <div className="progress-bar-track">
                <div className="progress-bar-fill" style={{ width: `${downloadProgress}%` }} />
              </div>
            </div>
          )}

          {/* Result */}
          {info && !downloading && (
            <div className="result-card">
              <div className="result-header">
                {info.thumbnail && <img src={info.thumbnail} alt="thumbnail" className="thumbnail" />}
                <div className="video-info">
                  <h2 className="video-title">{info.title}</h2>
                  <div className="video-meta">
                    <span className="meta-chip">
                      <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 14.5v-9l6 4.5-6 4.5z"/></svg>
                      {info.platform}
                    </span>
                    <span className="meta-chip">
                      <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
                      {formatDuration(info.duration)}
                    </span>
                    <span className="meta-chip">
                      {downloadType === 'mp4' ? '🎬 Video' : '🎵 Ses'}
                    </span>
                  </div>
                </div>
              </div>
              <div className="format-section">
                <p className="format-section-title">
                  {downloadType === 'mp4' ? 'Çözünürlük Seç' : 'Kalite Seç'}
                </p>
                <div className="format-options">
                  {info.formats.map((fmt, i) => (
                    <button key={i} className="format-btn" onClick={() => handleDownload(fmt.format_id)}>
                      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                      <span className="format-res">{fmt.resolution}</span>
                      <span className="format-ext">{fmt.ext.toUpperCase()} · {fmt.note}</span>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}
        </main>

        <footer className="site-footer">
          <div className="footer-links">
            <a href="#">Gizlilik Politikası</a>
            <a href="#">Kullanım Koşulları</a>
            <a href="#">İletişim</a>
          </div>
          <p>© 2025 VidFetch · Yalnızca kişisel kullanım amaçlıdır.</p>
        </footer>
      </div>
    </>
  )
}

export default App
