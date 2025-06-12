FROM python:3.11-slim

RUN apt-get update && \
    apt-get install -y graphviz && \
    pip install --no-cache-dir gunicorn && \
    pip install --no-cache-dir -r requirements.txt

COPY . /app
WORKDIR /app

CMD ["gunicorn", "Website.main:app"]
