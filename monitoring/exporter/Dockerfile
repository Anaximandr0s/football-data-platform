# Pipeline exporter image. The code is NOT copied in: docker-compose.yml mounts the repository read-only in /app, and
# the exporter imports app/streamlit/quality.py from there, so it uses the Data quality page's rules.
FROM python:3.11-slim
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app/monitoring/exporter:/app/app/streamlit
EXPOSE 9110
CMD ["python", "-m", "pipeline_exporter"]
