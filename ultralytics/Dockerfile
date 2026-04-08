FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 libgomp1 wget \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN wget -q https://github.com/ultralytics/assets/releases/download/v8.4.0/yolov8n.pt -O /app/yolov8n.pt

COPY app.py .
COPY counting.py .
COPY alerts.py .

CMD ["python", "app.py"]
