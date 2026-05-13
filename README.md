# VidFetch

Çoklu platform (YouTube, Instagram, X vb.) yüksek kaliteli video ve ses indirme projesi.

## Kurulum ve Çalıştırma

### 1. Arka Yüz (Backend - FastAPI & yt-dlp)
Arka yüz için bilgisayarında Python yüklü olmalıdır.

Terminalde `backend` klasörüne gir:
```bash
cd backend
```
Gerekli kütüphaneleri kur:
```bash
pip install -r requirements.txt
```
Sunucuyu başlat:
```bash
uvicorn main:app --reload --port 8000
```
API `http://localhost:8000` adresinde çalışmaya başlayacaktır.

*(Not: Gerçek indirme işlemlerinin yapılabilmesi için bilgisayarında **FFmpeg** yüklü olmalıdır. İndirip ortam değişkenlerine (PATH) eklemeniz tavsiye edilir.)*

### 2. Ön Yüz (Frontend - React & Vite)
Ön yüz için bilgisayarında Node.js yüklü olmalıdır.

Yeni bir terminal aç ve `frontend` klasörüne gir:
```bash
cd frontend
```
Bağımlılıkları yükle:
```bash
npm install
```
Geliştirme sunucusunu başlat:
```bash
npm run dev
```
Uygulama `http://localhost:5173` adresinde açılacaktır.

## Özellikler
- Cam efekti (Glassmorphism) içeren modern karanlık tema.
- `yt-dlp` altyapısı ile binlerce siteden URL analizi yapabilme.
- İndirilebilir formatları çözümleme.
