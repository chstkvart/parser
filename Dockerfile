FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8000 \
    MAX_BROWSER_PAGES=4

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chrome \
    && useradd --create-home --uid 10001 app

COPY app ./app
COPY run.py .

# Chrome renders third-party pages; without root a browser exploit can't take over the container.
USER app

EXPOSE 8000
CMD ["python", "run.py"]
