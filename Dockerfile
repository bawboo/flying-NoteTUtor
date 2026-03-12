FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# Python, Xvfb, Qt 6 runtime libs for MuseScore 4, squashfs-tools as backup extractor
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget ca-certificates squashfs-tools \
    xvfb \
    python3 python3-pip \
    libglib2.0-0 \
    # GL/EGL: mscore4portable requires libEGL.so.1 (libegl1) and libOpenGL.so.0 (libopengl0)
    # libgl1-mesa-dri provides the Mesa software rasterizer for LIBGL_ALWAYS_SOFTWARE=1
    libgl1-mesa-dri libgl1-mesa-glx libglx-mesa0 libopengl0 libglu1-mesa libegl1 libegl-mesa0 \
    libfontconfig1 libnss3 \
    libxcomposite1 libxdamage1 libxrandr2 libxtst6 libasound2 \
    libdbus-1-3 libxkbcommon0 libxkbcommon-x11-0 \
    # Qt 6 on Linux still probes Wayland/XCB runtime libraries even when running via xcb
    libwayland-client0 libwayland-cursor0 libwayland-egl1 libx11-xcb1 libxcb-cursor0 \
    libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 \
    libxcb-render-util0 libxcb-xinerama0 libxcb-xkb1 libxcb-shape0 \
    # JACK audio (libjack.so.0) — MuseScore 4 tries to load this for audio init
    libjack-jackd2-0 \
    # PulseAudio with null sink — gives MuseScore a virtual audio device in Docker
    libpulse0 pulseaudio pulseaudio-utils \
    && rm -rf /var/lib/apt/lists/*

RUN set -ex \
    && for lib in libOpenGL.so.0 libjack.so.0 libnss3.so libwayland-client.so.0; do \
        resolved="$(ldconfig -p | awk -v name="$lib" '$1 == name { print $NF; exit }')"; \
        test -n "$resolved"; \
        mkdir -p /lib/x86_64-linux-gnu; \
        ln -sf "$resolved" "/lib/x86_64-linux-gnu/$lib"; \
    done

# Configure PulseAudio to use a null sink (no real audio hardware needed)
RUN echo "load-module module-null-sink\nload-module module-native-protocol-unix" \
    > /etc/pulse/default.pa

# --- Step 1: Download AppImage (separate RUN so build log shows this step clearly) ---
COPY download_musescore.py /tmp/
RUN python3 /tmp/download_musescore.py

# --- Step 2: Extract AppImage and create symlink ---
# --appimage-extract avoids FUSE; squashfs-root is created in the working directory.
COPY musescore-wrapper.sh /usr/local/bin/mscore4
RUN set -ex \
    && chmod +x /tmp/mscore.AppImage \
    && cd /tmp && /tmp/mscore.AppImage --appimage-extract \
    && mv /tmp/squashfs-root /opt/musescore4 \
    && rm -f /tmp/mscore.AppImage /tmp/download_musescore.py \
    && chmod +x /usr/local/bin/mscore4

# --- Step 3: Install Python deps ---
WORKDIR /app
COPY requirements.txt server.py start-render-backend.sh ./
RUN pip3 install --no-cache-dir -r requirements.txt

ENV XDG_RUNTIME_DIR=/tmp/xdg-runtime
RUN mkdir -p /tmp/xdg-runtime && chmod 700 /tmp/xdg-runtime

# Pre-create MuseScore 4 config dirs to avoid first-run setup failures
RUN mkdir -p /root/.config/MuseScore \
             /root/.local/share/MuseScore/MuseScore4 \
    && printf '[application]\nhasCompletedFirstLaunchSetup=true\n' \
       > /root/.config/MuseScore/MuseScore4.ini

# Use Mesa software rendering (libgl1-mesa-dri provides the rasterizer)
ENV LIBGL_ALWAYS_SOFTWARE=1
ENV QT_OPENGL=software
ENV QTWEBENGINE_DISABLE_SANDBOX=1
ENV QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox --disable-gpu --disable-dev-shm-usage"
ENV SKIP_LIBJACK=1
ENV DISPLAY=:99

EXPOSE 5000

# Start PulseAudio (null sink) + Xvfb, wait, then run server
RUN chmod +x /app/start-render-backend.sh
CMD ["/app/start-render-backend.sh"]
