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
export APPDIR="${APPDIR:-/opt/musescore4}"

args=()
for arg in "$@"; do
    case "${arg}" in
        --no-webview|--no-synthesizer)
            ;;
        *)
            args+=("${arg}")
            ;;
    esac
done
stdout_file="$(mktemp)"
stderr_file="$(mktemp)"

cleanup() {
    rm -f "${stdout_file}" "${stderr_file}"
}
trap cleanup EXIT

set +e
"${REAL_MUSESCORE_BIN}" "${args[@]}" >"${stdout_file}" 2>"${stderr_file}"
status=$?
set -e

cat "${stdout_file}"

while IFS= read -r line; do
    if [[ -z "${line}" ]]; then
        continue
    fi

    if [[ "${line}" == /lib/* && -e "${line}" ]]; then
        continue
    fi

    if [[ "${line}" == AppImage:\ Using\ fallback\ for\ library* ]]; then
        continue
    fi

    printf '%s\n' "${line}" >&2
done < "${stderr_file}"

exit "${status}"
