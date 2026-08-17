FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY meesho_recon ./meesho_recon
COPY run_portal.py .
# portal_data/ is written at runtime; mount a volume there to keep workspaces
EXPOSE 8000
CMD ["sh", "-c", "gunicorn -w 1 --threads 8 -b 0.0.0.0:${PORT:-8000} meesho_recon.webapp:app"]
