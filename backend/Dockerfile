FROM python:3.11-slim

RUN apt-get update && apt-get install -y ffmpeg tor && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p downloads

EXPOSE 8000

# Start Tor in background then launch the API
CMD tor --RunAsDaemon 1 --DataDirectory /tmp/tor && sleep 3 && uvicorn main:app --host 0.0.0.0 --port 8000
