FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# Python, Xvfb (virtual display required by MuseScore even in CLI mode),
# and Qt/graphics runtime libraries needed by MuseScore 4
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget ca-certificates \
    xvfb \
    python3 python3-pip \
    libglib2.0-0 libgl1-mesa-glx libfontconfig1 libnss3 \
    libxcomposite1 libxdamage1 libxrandr2 libxtst6 libasound2 \
    libdbus-1-3 libxkbcommon0 libxkbcommon-x11-0 \
    libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 \
    libxcb-render-util0 libxcb-xinerama0 libxcb-xkb1 libxcb-shape0 \
    && rm -rf /var/lib/apt/lists/*

# Fetch the latest MuseScore 4 AppImage URL from GitHub, download, and extract.
# Extraction (--appimage-extract) avoids the FUSE requirement inside Docker.
# Shell variable captures Python stdout directly — no intermediate file needed.
RUN MSCORE_URL=$(python3 -c "\
import urllib.request, json; \
data = json.load(urllib.request.urlopen('https://api.github.com/repos/musescore/MuseScore/releases/latest')); \
print(next(a['browser_download_url'] for a in data['assets'] if 'x86_64.AppImage' in a['name']))") \
    && echo "Downloading: $MSCORE_URL" \
    && wget -q -O /tmp/mscore.AppImage "$MSCORE_URL" \
    && chmod +x /tmp/mscore.AppImage \
    && cd /tmp && /tmp/mscore.AppImage --appimage-extract \
    && mv /tmp/squashfs-root /opt/musescore4 \
    && rm -f /tmp/mscore.AppImage \
    && ln -s /opt/musescore4/AppRun /usr/local/bin/mscore4

WORKDIR /app
COPY requirements.txt server.py ./
RUN pip3 install --no-cache-dir -r requirements.txt

# Silence the XDG_RUNTIME_DIR warning printed by MuseScore
ENV XDG_RUNTIME_DIR=/tmp/xdg-runtime
RUN mkdir -p /tmp/xdg-runtime && chmod 700 /tmp/xdg-runtime

EXPOSE 5000

# Start a virtual display, wait for it to be ready, then launch the Flask server
CMD bash -c "Xvfb :99 -screen 0 1024x768x24 -ac +render -noreset & sleep 2 && DISPLAY=:99 python3 server.py"
