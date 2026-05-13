FROM python:3.11-slim

# System deps: ffmpeg + Node.js (for bgutil PO token provider)
RUN apt-get update && \
    apt-get install -y ffmpeg curl gnupg && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install bgutil PO token provider (yt-dlp plugin)
RUN pip install --no-cache-dir yt-dlp-get-pot
RUN npm install -g @ybd-project/bgutil-ytdlp-pot-provider

# Pre-download the bgutil driver
RUN node /usr/lib/node_modules/@ybd-project/bgutil-ytdlp-pot-provider/dist/cli.js download-driver || true

COPY . .
RUN mkdir -p downloads

EXPOSE 8000

CMD ["bash", "start.sh"]
