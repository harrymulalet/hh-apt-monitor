# Local-run fallback if GitHub Actions IPs get bot-detected.
# Runs the monitor in a loop every 10 minutes from your home network.
#
# Build:  docker build -t apt-monitor .
# Run:    docker run -d --name apt-monitor --restart unless-stopped \
#             -e NTFY_TOPIC=your-topic-here \
#             -v "$(pwd)/seen.json:/app/seen.json" \
#             apt-monitor

FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY monitor.py .

# Run every 10 minutes
CMD ["sh", "-c", "while true; do python monitor.py; sleep 600; done"]
