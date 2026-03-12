#!/usr/bin/env bash
set -euo pipefail

REAL_MUSESCORE_BIN="/opt/musescore4/AppRun"
LIB_DIR="/lib/x86_64-linux-gnu"

ensure_lib_path() {
    local lib_name="$1"
    local target_path="${LIB_DIR}/${lib_name}"
    local resolved_path

    if [[ -e "${target_path}" ]]; then
        return 0
    fi

    resolved_path="$(ldconfig -p | awk -v lib="${lib_name}" '$1 == lib { print $NF; exit }')"
    if [[ -n "${resolved_path}" ]]; then
        ln -sf "${resolved_path}" "${target_path}"
    fi
}

for lib in libOpenGL.so.0 libjack.so.0 libnss3.so libwayland-client.so.0; do
    ensure_lib_path "${lib}"
done

export LIBGL_ALWAYS_SOFTWARE="${LIBGL_ALWAYS_SOFTWARE:-1}"
export QT_OPENGL="${QT_OPENGL:-software}"
export QT_QUICK_BACKEND="${QT_QUICK_BACKEND:-software}"
export QSG_RENDER_LOOP="${QSG_RENDER_LOOP:-basic}"
export QTWEBENGINE_DISABLE_SANDBOX="${QTWEBENGINE_DISABLE_SANDBOX:-1}"
export QTWEBENGINE_CHROMIUM_FLAGS="${QTWEBENGINE_CHROMIUM_FLAGS:---no-sandbox --disable-gpu --disable-dev-shm-usage}"
export SKIP_LIBJACK="${SKIP_LIBJACK:-1}"

args=("$@")
extra_args=(--no-webview)
output_path=""

for ((i = 0; i < ${#args[@]}; i++)); do
    if [[ "${args[$i]}" == "-o" && $((i + 1)) -lt ${#args[@]} ]]; then
        output_path="${args[$((i + 1))]}"
        break
    fi
done

if [[ -n "${output_path}" ]]; then
    lower_output="$(printf '%s' "${output_path}" | tr '[:upper:]' '[:lower:]')"
    case "${lower_output}" in
        *.xml|*.musicxml|*.mxl)
            extra_args+=(--no-synthesizer)
            ;;
    esac
fi

exec "${REAL_MUSESCORE_BIN}" "${extra_args[@]}" "${args[@]}"
