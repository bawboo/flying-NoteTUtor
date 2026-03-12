"""
Download the latest MuseScore 4 Linux AppImage from GitHub.
Falls back to a pinned URL if the API is unavailable.
"""
import urllib.request, json, sys, os

API_URL  = 'https://api.github.com/repos/musescore/MuseScore/releases/latest'
# Pinned fallback — update tag/filename if a newer release is needed
FALLBACK = ('https://github.com/musescore/MuseScore/releases/download/'
            'v4.4.4/MuseScore-Studio-4.4.4.242570447-x86_64.AppImage')
DEST     = '/tmp/mscore.AppImage'
MIN_SIZE = 10 * 1024 * 1024  # 10 MB — anything smaller is likely an error page

def fetch_url():
    print('Querying GitHub API for latest MuseScore release...', flush=True)
    try:
        req = urllib.request.Request(
            API_URL, headers={'User-Agent': 'Docker-Build/1.0',
                              'Accept': 'application/vnd.github.v3+json'})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)
        assets = [a for a in data['assets'] if 'x86_64.AppImage' in a['name']]
        if assets:
            return assets[0]['browser_download_url']
        print(f'No AppImage asset found. Available: {[a["name"] for a in data["assets"]]}',
              flush=True)
    except Exception as exc:
        print(f'GitHub API error: {exc}', flush=True)
    print(f'Using fallback URL: {FALLBACK}', flush=True)
    return FALLBACK

url = fetch_url()
print(f'Downloading: {url}', flush=True)

urllib.request.urlretrieve(url, DEST)

size = os.path.getsize(DEST)
print(f'Downloaded {size:,} bytes.', flush=True)

if size < MIN_SIZE:
    print(f'ERROR: file is only {size} bytes — download likely failed.', flush=True)
    # Print first 500 chars so we can see if it's an HTML error page
    try:
        with open(DEST, 'rb') as f:
            print(f.read(500), flush=True)
    except Exception:
        pass
    sys.exit(1)

print('Download OK.', flush=True)
