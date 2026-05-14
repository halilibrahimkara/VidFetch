@echo off
chcp 65001 > nul
title VidFetch - Yerel Backend

echo.
echo  ╔══════════════════════════════════════════╗
echo  ║     VidFetch Yerel Backend               ║
echo  ║     YouTube MP4 indirme modu             ║
echo  ╚══════════════════════════════════════════╝
echo.

:: Python kontrol
python --version > nul 2>&1
if errorlevel 1 (
    echo  [HATA] Python bulunamadi! python.org'dan yukleyin.
    pause
    exit /b 1
)

:: Bağımlılıkları yükle
echo  [1/3] Python bagimliliklar kontrol ediliyor...
cd /d "%~dp0backend"
pip install -r requirements.txt -q
if errorlevel 1 (
    echo  [HATA] Bagimliliklar yuklenemedi!
    pause
    exit /b 1
)
echo        Tamam!
echo.

:: Backend başlat
echo  [2/3] Backend baslatiliyor (port 8000)...
start /min "VidFetch Backend" cmd /c "cd /d "%~dp0backend" && python -m uvicorn main:app --host 0.0.0.0 --port 8000 && pause"
timeout /t 3 /nobreak > nul
echo        Backend calisiyor: http://localhost:8000
echo.

:: cloudflared indir ve başlat
echo  [3/3] Cloudflare tuneli aciliyor...
echo.

:: cloudflared.exe var mı kontrol et
if not exist "%~dp0cloudflared.exe" (
    echo  cloudflared indiriliyor...
    curl -L "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe" -o "%~dp0cloudflared.exe" --silent
    if errorlevel 1 (
        echo.
        echo  [HATA] cloudflared indirilemedi. Manuel olarak:
        echo  https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe
        echo  adresinden indirip baslat.bat ile ayni klasore koyun.
        echo.
        echo  Alternatif: Sadece lokal kullanmak icin tarayicida:
        echo  http://localhost:8000
        pause
        exit /b 1
    )
    echo  cloudflared indirildi!
    echo.
)

echo  ════════════════════════════════════════════
echo   Tünel aciliyor, URL asagida gorunecek...
echo   Bu URL'yi Netlify'da VITE_LOCAL_API_URL
echo   olarak ekleyin (tek seferlik).
echo  ════════════════════════════════════════════
echo.

"%~dp0cloudflared.exe" tunnel --url http://localhost:8000

echo.
echo  Backend kapatildi.
pause
