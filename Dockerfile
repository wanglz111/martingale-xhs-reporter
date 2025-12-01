# Minimal image for xhs reporter
FROM python:3.12-slim

WORKDIR /app

# System deps (none heavy), then install python deps
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy source (state/secrets are mounted at runtime)
COPY analyze.py xhs_summary.py README.md docker-entrypoint.sh ./ 
RUN chmod +x /app/docker-entrypoint.sh

# Default command can be overridden by docker run / compose
CMD ["/app/docker-entrypoint.sh"]
