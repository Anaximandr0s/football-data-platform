# MatchLens Control Center (make demo). The code is NOT copied in: docker-compose.yml mounts the repository read-only in
# /app; the Control Center runs the project's own producer and reads the app's clock and quality code from there.
FROM python:3.11-slim
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app/app/api:/app/app/streamlit:/app/scripts:/app PROJECT_ROOT=/app
WORKDIR /app/app/api
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
