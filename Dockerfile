FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# Python, Xvfb, Qt 6 runtime libs for MuseScore 4, squashfs-tools as backup extractor
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget ca-certificates squashfs-tools \
    xvfb \
    python3 python3-pip \
    libglib2.0-0 \
    # Qt 6 needs libopengl0 (libOpenGL.so.0) — different from libgl1-mesa-glx
    libgl1-mesa-glx libopengl0 libglu1-mesa \
    libfontconfig1 libnss3 \
    libxcomposite1 libxdamage1 libxrandr2 libxtst6 libasound2 \
    libdbus-1-3 libxkbcommon0 libxkbcommon-x11-0 \
    libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 \
    libxcb-render-util0 libxcb-xinerama0 libxcb-xkb1 libxcb-shape0 \
    && rm -rf /var/lib/apt/lists/*

# --- Step 1: Download AppImage (separate RUN so build log shows this step clearly) ---
COPY download_musescore.py /tmp/
RUN python3 /tmp/download_musescore.py

# --- Step 2: Extract AppImage and create symlink ---
# --appimage-extract avoids FUSE; squashfs-root is created in the working directory.
RUN set -ex \
    && chmod +x /tmp/mscore.AppImage \
    && cd /tmp && /tmp/mscore.AppImage --appimage-extract \
    && mv /tmp/squashfs-root /opt/musescore4 \
    && rm -f /tmp/mscore.AppImage /tmp/download_musescore.py \
    && ln -s /opt/musescore4/AppRun /usr/local/bin/mscore4

# --- Step 3: Install Python deps ---
WORKDIR /app
COPY requirements.txt server.py ./
RUN pip3 install --no-cache-dir -r requirements.txt

# Silence the XDG_RUNTIME_DIR warning from MuseScore
ENV XDG_RUNTIME_DIR=/tmp/xdg-runtime
RUN mkdir -p /tmp/xdg-runtime && chmod 700 /tmp/xdg-runtime

# Force Mesa software rendering — Docker containers have no GPU.
# Without this Qt 6 fails to initialize OpenGL and exits with code 127.
ENV LIBGL_ALWAYS_SOFTWARE=1
ENV QT_XCB_GL_INTEGRATION=none

EXPOSE 5000

# Start virtual display then launch Flask
CMD bash -c "Xvfb :99 -screen 0 1024x768x24 -ac +render -noreset & sleep 2 && DISPLAY=:99 python3 server.py"
