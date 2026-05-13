"""
Bu script cookies.txt dosyasını Base64'e çevirir.
Çıktıyı Render'da YOUTUBE_COOKIES_B64 ortam değişkeni olarak ekle.

Kullanım:
    python encode_cookies.py youtube.com_cookies.txt
"""
import sys
import base64

if len(sys.argv) < 2:
    print("Kullanım: python encode_cookies.py <cookies.txt yolu>")
    sys.exit(1)

with open(sys.argv[1], "rb") as f:
    encoded = base64.b64encode(f.read()).decode("utf-8")

print("\n=== Render'a eklenecek değer (YOUTUBE_COOKIES_B64) ===")
print(encoded)
print("\n(Tümünü kopyalayıp Render'a yapıştır)")
