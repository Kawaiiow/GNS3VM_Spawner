FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# main.py ใช้ path แบบสัมพัทธ์ ("static", "template") จึงต้องรันจากโฟลเดอร์ app
COPY app/ ./app/
WORKDIR /srv/app

EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
