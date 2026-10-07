FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8000 \
    TRUST_PROXY=1 \
    MAX_BROWSER_PAGES=4

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chrome

COPY app ./app
COPY run.py .

EXPOSE 8000
CMD ["python", "run.py"]
