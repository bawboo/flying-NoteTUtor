"""
server.py — lightweight backend for .mscz → MusicXML + audio conversion.

Usage:
    pip install flask flask-cors
    python server.py

Then open index.html in a browser; the .mscz upload section will call
http://127.0.0.1:5000/convert automatically.
"""

import base64
import os
import platform
import shutil
import subprocess
import tempfile

from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
# Allow all origins so GitHub Pages (and local file://) can call this backend.
# Restrict via ALLOWED_ORIGINS env var if needed (comma-separated list).
_allowed = os.environ.get("ALLOWED_ORIGINS", "*")
CORS(app, origins=_allowed.split(",") if _allowed != "*" else "*")

TIMEOUT_SECONDS = 60  # per MuseScore CLI call


# ---------------------------------------------------------------------------
# MuseScore discovery
# ---------------------------------------------------------------------------

def find_musescore() -> str | None:
    """Return path to MuseScore CLI executable, or None if not found."""
    system = platform.system()

    candidates: list[str] = []
    if system == "Windows":
        candidates = [
            r"C:\Program Files\MuseScore 4\bin\MuseScore4.exe",
            r"C:\Program Files\MuseScore 3\bin\MuseScore3.exe",
            r"C:\Program Files (x86)\MuseScore 4\bin\MuseScore4.exe",
            r"C:\Program Files (x86)\MuseScore 3\bin\MuseScore3.exe",
        ]
    elif system == "Darwin":  # macOS
        candidates = [
            "/Applications/MuseScore 4.app/Contents/MacOS/mscore",
            "/Applications/MuseScore 3.app/Contents/MacOS/mscore",
        ]
    # Linux: no hard-coded paths — rely on PATH below

    for path in candidates:
        if os.path.isfile(path):
            return path

    # Fall back to PATH search (works on Linux / macOS / custom installs)
    for name in ["mscore4", "mscore3", "mscore", "MuseScore4", "MuseScore3", "musescore"]:
        found = shutil.which(name)
        if found:
            return found

    return None


MUSESCORE_PATH = find_musescore()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def run_musescore(args: list[str]) -> tuple[int, str, str]:
    """
    Run MuseScore CLI with *args* and return (returncode, stdout, stderr).

    Uses Qt's offscreen platform — no X server or Xvfb required.
    Forces Mesa software rasterizer for GPU-less Docker containers.
    Raises TimeoutError or RuntimeError on failure.
    """
    cmd = [MUSESCORE_PATH] + args

    env = os.environ.copy()
    # Qt offscreen platform: renders into memory, no display required
    env["QT_QPA_PLATFORM"] = "offscreen"
    # Force Mesa software renderer (no GPU in Docker)
    env["LIBGL_ALWAYS_SOFTWARE"] = "1"
    env["QT_OPENGL"] = "software"
    # Suppress Qt warnings about missing audio/GPU drivers
    env["QT_LOGGING_RULES"] = "*.debug=false;qt.qpa.*=false"

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            env=env,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        raise TimeoutError(f"MuseScore timed out after {TIMEOUT_SECONDS}s")
    except FileNotFoundError:
        raise RuntimeError(f"MuseScore executable not found: {MUSESCORE_PATH}")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/health", methods=["GET"])
def health():
    """Quick health check — also reveals whether MuseScore was found."""
    return jsonify({
        "status": "ok",
        "musescore": MUSESCORE_PATH or "not found",
    })


@app.route("/convert", methods=["POST"])
def convert():
    """
    Accept a .mscz/.mscx file, convert via MuseScore CLI, and return:
      {
        "musicxml": "<xml string>",
        "audio":    "<base64 string | null>",
        "audio_type": "audio/ogg" | "audio/wav" | null,
        "filename": "original.mscz"
      }
    """
    # --- Guard: MuseScore availability ---
    if not MUSESCORE_PATH:
        return jsonify({
            "error": (
                "MuseScore CLI not found on this machine. "
                "Please install MuseScore 3 or 4 and make sure it is "
                "accessible (e.g. added to PATH)."
            )
        }), 503

    # --- Guard: file presence ---
    if "file" not in request.files:
        return jsonify({"error": "No file provided. Use field name 'file'."}), 400

    upload = request.files["file"]
    original_name: str = upload.filename or "score.mscz"

    if not original_name.lower().endswith((".mscz", ".mscx")):
        return jsonify({"error": "Only .mscz and .mscx files are accepted."}), 400

    # --- Work inside a temporary directory ---
    with tempfile.TemporaryDirectory() as tmpdir:
        input_path = os.path.join(tmpdir, original_name)
        xml_path   = os.path.join(tmpdir, "output.musicxml")

        upload.save(input_path)

        if os.path.getsize(input_path) == 0:
            return jsonify({"error": "Uploaded file is empty or corrupt."}), 400

        # ----- Export MusicXML (required) -----
        try:
            rc, _, err = run_musescore(["-o", xml_path, input_path])
        except TimeoutError as exc:
            return jsonify({"error": str(exc)}), 504
        except RuntimeError as exc:
            return jsonify({"error": str(exc)}), 503

        if rc != 0 or not os.path.exists(xml_path):
            excerpt = err[:500] if err else "(no stderr)"
            return jsonify({
                "error": f"MusicXML export failed (exit code {rc}). Details: {excerpt}"
            }), 500

        with open(xml_path, "r", encoding="utf-8", errors="replace") as fp:
            musicxml_text = fp.read()

        # ----- Export Audio (optional — try OGG then WAV) -----
        audio_b64: str | None = None
        audio_mime: str | None = None

        for ext, mime in [(".ogg", "audio/ogg"), (".wav", "audio/wav")]:
            audio_path = os.path.join(tmpdir, f"output{ext}")
            try:
                rc_a, _, _ = run_musescore(["-o", audio_path, input_path])
                if rc_a == 0 and os.path.exists(audio_path):
                    with open(audio_path, "rb") as fp:
                        audio_b64 = base64.b64encode(fp.read()).decode()
                    audio_mime = mime
                    break  # success — stop trying other formats
            except (TimeoutError, RuntimeError):
                continue  # try next format

        return jsonify({
            "musicxml":   musicxml_text,
            "audio":      audio_b64,
            "audio_type": audio_mime,
            "filename":   original_name,
        })


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if MUSESCORE_PATH:
        print(f"[INFO] MuseScore found: {MUSESCORE_PATH}", flush=True)
    else:
        print("[WARN] MuseScore not found — /convert will return HTTP 503.", flush=True)
    port = int(os.environ.get("PORT", 5000))
    print(f"[INFO] Backend listening on 0.0.0.0:{port}", flush=True)
    app.run(host="0.0.0.0", port=port, debug=False)
