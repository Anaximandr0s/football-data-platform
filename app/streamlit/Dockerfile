# Dashboard image (Streamlit + mplsoccer + DuckDB). The code is NOT copied in: docker-compose.yml mounts the repository
# read-only in /app, so an edit shows up at the next rerun and the dashboard can never change the data.
FROM python:3.15-slim
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
ENV MPLBACKEND=Agg PYTHONUNBUFFERED=1
WORKDIR /app/app/streamlit
EXPOSE 8501
CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true", "--browser.gatherUsageStats=false"]
