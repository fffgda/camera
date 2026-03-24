FROM ultralytics/ultralytics:latest

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app.py /app/app.py

EXPOSE 5001

CMD ["python", "app.py"]