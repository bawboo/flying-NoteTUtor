"""
Download MuseScore 4 Linux x86_64 AppImage from GitHub releases.

Strategy: parse the releases HTML page — no API token, no rate limit.
Tries the 'latest' page first, then falls back to specific version tags.
"""
import urllib.request, re, sys, os

DEST     = '/tmp/mscore.AppImage'
MIN_SIZE = 50 * 1024 * 1024   # 50 MB — anything smaller is a failed download
HEADERS  = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64)'}

# Release pages to try in order (latest redirect first, then pinned tags)
RELEASE_PAGES = [
    'https://github.com/musescore/MuseScore/releases/latest',
    'https://github.com/musescore/MuseScore/releases/expanded_assets/v4.4.4',
    'https://github.com/musescore/MuseScore/releases/tag/v4.4.4',
    'https://github.com/musescore/MuseScore/releases/tag/v4.4.2',
    'https://github.com/musescore/MuseScore/releases/tag/v4.4.0',
    'https://github.com/musescore/MuseScore/releases/tag/v4.3.2',
]

APPIMAGE_RE = re.compile(
    r'href="(/musescore/MuseScore/releases/download/[^"]*x86_64\.AppImage[^"]*)"'
)


def page_urls(page_url: str) -> list[str]:
    """Fetch a GitHub releases page and return all AppImage asset URLs found."""
    try:
        req = urllib.request.Request(page_url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=30) as r:
            html = r.read().decode('utf-8', errors='replace')
        found = ['https://github.com' + m for m in APPIMAGE_RE.findall(html)]
        return found
    except Exception as exc:
        print(f'  Fetch failed: {exc}', flush=True)
        return []


def try_download(url: str) -> bool:
    """Download from URL to DEST. Returns True on success."""
    try:
        print(f'  Downloading: {url}', flush=True)
        urllib.request.urlretrieve(url, DEST)
        size = os.path.getsize(DEST)
        if size < MIN_SIZE:
            os.remove(DEST)
            print(f'  Too small ({size:,} bytes) — likely an error page', flush=True)
            return False
        print(f'  OK — {size:,} bytes', flush=True)
        return True
    except Exception as exc:
        print(f'  Failed: {exc}', flush=True)
        if os.path.exists(DEST):
            os.remove(DEST)
        return False


seen: set[str] = set()

for page in RELEASE_PAGES:
    print(f'Checking page: {page}', flush=True)
    for url in page_urls(page):
        if url in seen:
            continue
        seen.add(url)
        if try_download(url):
            sys.exit(0)

print('ERROR: Could not download MuseScore AppImage from any source.', flush=True)
sys.exit(1)
