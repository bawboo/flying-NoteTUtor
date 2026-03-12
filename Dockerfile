FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# Install MuseScore 3 (has stable headless CLI), Xvfb (virtual display), Python
RUN apt-get update && apt-get install -y --no-install-recommends \
    musescore3 \
    xvfb \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt server.py ./
RUN pip3 install --no-cache-dir -r requirements.txt

EXPOSE 5000

# Xvfb provides a virtual display (MuseScore requires one even in CLI mode)
CMD bash -c "Xvfb :99 -screen 0 1024x768x24 -ac +render -noreset & sleep 2 && DISPLAY=:99 python3 server.py"
