# Tiny image: Alpine + Python 3.12, runs the animated dashboard.
FROM python:3.12-alpine

WORKDIR /app
COPY app.py .

# Unbuffered so ANSI frames stream live into the Unified Base log panel.
ENV PYTHONUNBUFFERED=1

CMD ["python", "app.py"]
