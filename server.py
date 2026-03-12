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
import re
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
QT_LOGGING_RULES = "*.debug=false;qt.qpa.*=false;qt.qml.*=false"
SHARED_LIBRARY_PACKAGE_HINTS = {
    "libOpenGL.so.0": "libopengl0",
    "libjack.so.0": "libjack-jackd2-0",
    "libnss3.so": "libnss3",
    "libwayland-client.so.0": "libwayland-client0",
    "libwayland-cursor.so.0": "libwayland-cursor0",
    "libwayland-egl.so.1": "libwayland-egl1",
}
DISPLAY_ERROR_MARKERS = (
    "could not connect to display",
    "could not load the qt platform plugin",
    "no qt platform plugin could be initialized",
    "qt.qpa.xcb",
    "could not connect to any x display",
    "qeventloop: cannot be used without qapplication",
)


# ---------------------------------------------------------------------------
# MuseScore discovery
# ---------------------------------------------------------------------------

def find_musescore() -> str | None:
    """Return path to MuseScore CLI executable, or None if not found."""
    system = platform.system()
    configured = os.environ.get("MUSESCORE_PATH") or os.environ.get("MUSESCORE_BIN")

    if configured:
        resolved = configured if os.path.isabs(configured) else shutil.which(configured)
        if resolved and os.path.isfile(resolved):
            return resolved

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

def build_musescore_env() -> dict[str, str]:
    """Return environment variables required for headless MuseScore 4 runs."""
    env = os.environ.copy()
    # MuseScore 4 needs a real X display in headless Linux, so keep xcb + Xvfb.
    env.setdefault("QT_QPA_PLATFORM", "xcb")
    env.setdefault("LIBGL_ALWAYS_SOFTWARE", "1")
    env.setdefault("QT_OPENGL", "software")
    env.setdefault("QT_QUICK_BACKEND", "software")
    env.setdefault("QSG_RENDER_LOOP", "basic")
    env["QT_LOGGING_RULES"] = QT_LOGGING_RULES
    return env


def build_musescore_cmd(args: list[str]) -> list[str]:
    """Wrap MuseScore with xvfb-run when Linux has no DISPLAY but xvfb-run exists."""
    base_cmd = [MUSESCORE_PATH] + args
    if platform.system() == "Linux" and not os.environ.get("DISPLAY"):
        xvfb_run = shutil.which("xvfb-run")
        if xvfb_run:
            return [
                xvfb_run,
                "-a",
                "--server-args=-screen 0 1280x1024x24 -ac +render -noreset",
                *base_cmd,
            ]
    return base_cmd


def filter_qt_noise(text: str) -> str:
    """Remove noisy Qt/QML registration lines from stderr/stdout excerpts."""
    return "\n".join(
        line for line in (text or "").splitlines()
        if "qt.qml.typeregistration" not in line
    ).strip()


def extract_missing_shared_libraries(text: str) -> list[str]:
    """Extract missing shared library names from MuseScore stderr."""
    found: list[str] = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if "not found" not in stripped.lower() and not stripped.startswith(("/", "lib")):
            continue
        for match in re.findall(r"lib[\w.+-]+\.so(?:\.\d+)*", stripped):
            if match not in found:
                found.append(match)
    return found


def diagnose_musescore_failure(returncode: int, stderr: str, stdout: str = "") -> dict:
    """Classify common MuseScore failures into deployment-friendly categories."""
    combined = filter_qt_noise("\n".join(part for part in [stderr, stdout] if part))
    lowered = combined.lower()
    missing_libs = extract_missing_shared_libraries(combined)

    category = "cli_export_failed"
    hint = (
        "MuseScore CLI started but did not complete the export. "
        "Check the backend logs for the full stderr."
    )
    status_code = 500

    if missing_libs:
        category = "missing_shared_libraries"
        packages = [
            SHARED_LIBRARY_PACKAGE_HINTS[lib]
            for lib in missing_libs
            if lib in SHARED_LIBRARY_PACKAGE_HINTS
        ]
        package_hint = f" Install: {', '.join(sorted(set(packages)))}." if packages else ""
        hint = (
            "The server is missing MuseScore runtime libraries."
            f"{package_hint} On Render, deploy this backend with the Docker runtime so "
            "the Dockerfile apt packages are actually present."
        )
        status_code = 503
    elif any(marker in lowered for marker in DISPLAY_ERROR_MARKERS):
        category = "headless_display_setup"
        hint = (
            "MuseScore 4 needs an X display in headless Linux. "
            "Run it under Xvfb (or xvfb-run) and keep QT_QPA_PLATFORM=xcb."
        )
        status_code = 503
    elif "permission denied" in lowered:
        category = "filesystem_permission"
        hint = (
            "MuseScore could not read or write a temporary file. "
            "Check the upload temp directory and file permissions."
        )
        status_code = 500

    return {
        "category": category,
        "hint": hint,
        "missing_libraries": missing_libs,
        "excerpt": combined[:4000] or "(no stderr — full log in server stdout)",
        "status_code": status_code,
        "exit_code": returncode,
    }


def musescore_error_response(summary: str, diagnostic: dict, *, stage: str) -> tuple:
    """Build a structured error payload for frontend and deployment debugging."""
    payload = {
        "error": summary,
        "hint": diagnostic["hint"],
        "details": diagnostic["excerpt"],
        "category": diagnostic["category"],
        "stage": stage,
        "exit_code": diagnostic["exit_code"],
    }
    if diagnostic["missing_libraries"]:
        payload["missing_libraries"] = diagnostic["missing_libraries"]
    return jsonify(payload), diagnostic["status_code"]


def run_musescore(args: list[str]) -> tuple[int, str, str]:
    """
    Run MuseScore CLI with *args* and return (returncode, stdout, stderr).

    Uses xcb + Xvfb for headless Linux and software rendering in containers.
    Raises TimeoutError or RuntimeError on failure.
    """
    cmd = build_musescore_cmd(args)
    env = build_musescore_env()

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            env=env,
        )
        # Log full output server-side (visible in Render / docker logs)
        if result.returncode != 0:
            print(f"[MuseScore] exit={result.returncode}", flush=True)
            print(f"[MuseScore] stderr:\n{result.stderr}", flush=True)
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
    """Quick health check — reveals MuseScore path, version, and help text."""
    info: dict = {
        "status": "ok",
        "musescore": {
            "path": MUSESCORE_PATH or "not found",
            "display": os.environ.get("DISPLAY"),
            "xvfb_run": bool(shutil.which("xvfb-run")),
        },
    }
    if MUSESCORE_PATH:
        for flag in ["-v", "--version", "-h", "--help"]:
            try:
                r = subprocess.run(
                    build_musescore_cmd([flag]),
                    capture_output=True,
                    text=True,
                    timeout=30,
                    env=build_musescore_env(),
                )
                out = filter_qt_noise(f"{r.stdout}\n{r.stderr}")
                if out:
                    info["musescore"]["probe_flag"] = flag
                    info["musescore"]["probe_output"] = out[:2000]
                    info["musescore"]["ready"] = (r.returncode == 0)
                    if r.returncode != 0:
                        info["musescore"]["diagnostic"] = diagnose_musescore_failure(
                            r.returncode, r.stderr, r.stdout
                        )
                    break
            except Exception as exc:
                info["musescore"]["probe_error"] = str(exc)
    return jsonify(info)


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
        # Always use a safe ASCII filename — MuseScore CLI may fail on Unicode paths
        safe_ext   = ".mscx" if original_name.lower().endswith(".mscx") else ".mscz"
        input_path = os.path.join(tmpdir, "input" + safe_ext)
        upload.save(input_path)

        if os.path.getsize(input_path) == 0:
            return jsonify({"error": "Uploaded file is empty or corrupt."}), 400

        # ----- Export MusicXML — try .xml then .musicxml (MuseScore 4 format support varies) -----
        xml_path = None
        rc, err = 0, ""
        musicxml_diagnostic = None
        for xml_ext in ["output.xml", "output.musicxml"]:
            candidate = os.path.join(tmpdir, xml_ext)
            try:
                rc, _, err = run_musescore(["-o", candidate, input_path])
            except TimeoutError as exc:
                return jsonify({"error": str(exc)}), 504
            except RuntimeError as exc:
                return jsonify({"error": str(exc)}), 503
            if os.path.exists(candidate) and os.path.getsize(candidate) > 0:
                xml_path = candidate
                if rc != 0:
                    print(f"[INFO] export exit={rc} but file exists — continuing", flush=True)
                break
            musicxml_diagnostic = diagnose_musescore_failure(rc, err)

        if not xml_path:
            diagnostic = musicxml_diagnostic or diagnose_musescore_failure(rc, err)
            summary = (
                "MusicXML export failed before the score could be converted. "
                f"(exit code {rc})"
            )
            return musescore_error_response(summary, diagnostic, stage="musicxml_export")
        if rc != 0:
            print(f"[INFO] MusicXML export exit={rc} but file exists — treating as success", flush=True)

        with open(xml_path, "r", encoding="utf-8", errors="replace") as fp:
            musicxml_text = fp.read()

        # ----- Export Audio (optional — try OGG then WAV) -----
        audio_b64: str | None = None
        audio_mime: str | None = None
        warnings: list[dict] = []

        for ext, mime in [(".ogg", "audio/ogg"), (".wav", "audio/wav")]:
            audio_path = os.path.join(tmpdir, f"output{ext}")
            try:
                rc_a, _, _ = run_musescore(["-o", audio_path, input_path])
                if os.path.exists(audio_path) and os.path.getsize(audio_path) > 0:
                    with open(audio_path, "rb") as fp:
                        audio_b64 = base64.b64encode(fp.read()).decode()
                    audio_mime = mime
                    break
                if rc_a != 0:
                    print(f"[WARN] audio export exit={rc_a} without output for {ext}", flush=True)
            except TimeoutError:
                warnings.append({
                    "stage": "audio_export",
                    "message": "Audio export timed out, but MusicXML export succeeded.",
                })
            except RuntimeError as exc:
                warnings.append({
                    "stage": "audio_export",
                    "message": "Audio export could not start, but MusicXML export succeeded.",
                    "details": str(exc),
                })

        if not audio_b64:
            warnings.append({
                "stage": "audio_export",
                "message": "MusicXML export succeeded, but no preview audio was generated.",
            })

        payload = {
            "musicxml":   musicxml_text,
            "audio":      audio_b64,
            "audio_type": audio_mime,
            "filename":   original_name,
        }
        if warnings:
            payload["warnings"] = warnings
        return jsonify(payload)


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
