FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/

RUN useradd -r -u 1001 -g root appuser
USER appuser

CMD ["python", "-u", "src/main.py"]
