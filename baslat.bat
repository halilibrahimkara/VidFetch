@echo off
title VidFetch Local Backend

echo.
echo  VidFetch Yerel Backend Baslatiliyor...
echo  =======================================
echo.

set "ROOT=%~dp0"
set "BACKEND=%ROOT%backend"
set "CLOUDFLARED=%ROOT%cloudflared.exe"

echo [1/3] Python bagimliliklar yukleniyor...
cd /d "%BACKEND%"
python -m pip install -r requirements.txt -q
echo       Tamam.
echo.

echo [2/3] Backend baslatiliyor (port 8000)...
start "VidFetch Backend" /min python -m uvicorn main:app --host 0.0.0.0 --port 8000
timeout /t 4 /nobreak > nul
echo       Tamam - http://localhost:8000
echo.

echo [3/3] Cloudflare tuneli aciliyor...
if not exist "%CLOUDFLARED%" (
    echo cloudflared indiriliyor...
    curl -L "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe" -o "%CLOUDFLARED%"
    if errorlevel 1 (
        echo HATA: cloudflared indirilemedi. Internet baglantinizi kontrol edin.
        pause
        exit /b 1
    )
    echo cloudflared indirildi.
    echo.
)

echo.
echo ================================================
echo  Asagidaki URL'yi kopyalayin:
echo  (https://xxxx.trycloudflare.com seklinde)
echo  Bu URL'yi Netlify'da VITE_LOCAL_API_URL
echo  olarak ekleyin.
echo ================================================
echo.

"%CLOUDFLARED%" tunnel --url http://localhost:8000

echo.
echo Backend kapatildi.
pause
