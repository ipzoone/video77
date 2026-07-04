from flask import Flask, send_from_directory, jsonify, request, abort
import requests
from bs4 import BeautifulSoup
import json
import re
import time
import concurrent.futures
from collections import defaultdict

app = Flask(__name__)

# ══════════════════════════════════════════════════════════════
#  SECURITY HEADERS
# ══════════════════════════════════════════════════════════════
app.config['PROPAGATE_EXCEPTIONS'] = False

@app.after_request
def set_security_headers(resp):
    resp.headers['X-Frame-Options'] = 'SAMEORIGIN'
    resp.headers['X-Content-Type-Options'] = 'nosniff'
    resp.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    resp.headers['Content-Security-Policy'] = (
        "default-src 'self' https: data: blob:; "
        "script-src 'self' 'unsafe-inline' https:; "
        "style-src 'self' 'unsafe-inline' https:; "
        "img-src 'self' https: data: blob:; "
        "frame-src https:; "
        "connect-src 'self' https:; "
        "media-src https: blob:;"
    )
    return resp

@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'not found'}), 404

@app.errorhandler(429)
def too_many(e):
    return jsonify({'error': 'too many requests, slow down'}), 429

@app.errorhandler(Exception)
def handle_exception(e):
    return jsonify({'error': 'internal server error'}), 500

# ══════════════════════════════════════════════════════════════
#  RATE LIMITER — sederhana, in-memory per IP
# ══════════════════════════════════════════════════════════════
_RATE_STORE  = defaultdict(list)
_RATE_LIMIT  = 20
_RATE_WINDOW = 60

def _get_ip():
    return (
        request.headers.get('X-Forwarded-For', '').split(',')[0].strip()
        or request.remote_addr
        or '0.0.0.0'
    )

def rate_limit_check():
    ip  = _get_ip()
    now = time.time()
    _RATE_STORE[ip] = [t for t in _RATE_STORE[ip] if now - t < _RATE_WINDOW]
    if len(_RATE_STORE[ip]) >= _RATE_LIMIT:
        abort(429)
    _RATE_STORE[ip].append(now)


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def get(url, timeout=20, **kwargs):
    """GET dengan 1x retry kalau gagal."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout, **kwargs)
        r.raise_for_status()
        return r
    except Exception:
        r = requests.get(url, headers=HEADERS, timeout=timeout + 10, **kwargs)
        r.raise_for_status()
        return r


# ══════════════════════════════════════════════════════════════
#  SETIAP SCRAPER WAJIB RETURN LIST OF DICT DENGAN SHAPE INI:
#
#  {
#    'id':        str,   # id unik video di platform itu
#    'title':     str,
#    'thumbnail': str,   # url gambar thumbnail
#    'duration':  str,   # boleh kosong ''
#    'source':    str,   # nama key di SCRAPERS, dipakai utk badge warna
#    'type':      'video' | 'film',  # 'video' = autoplay di hero (embed),
#                                    # 'film'  = dibuka di modal iframe
#    'embed_url': str,   # url utk <iframe> (kalau type='video')
#    'page_url':  str,   # url halaman asli (tombol "buka di tab baru")
#    'rating':    str,   # boleh kosong ''
#    'genre':     str,   # boleh kosong ''
#    'year':      str,   # boleh kosong ''
#  }
# ══════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════
#  1. YOUTUBE
# ══════════════════════════════════════════════════════════════
# def scrape_youtube(query):
#     url = f"https://www.youtube.com/results?search_query={requests.utils.quote(query)}"
#     results = []
#     try:
#         soup = BeautifulSoup(get(url).text, 'html.parser')
#         for script in soup.find_all('script'):
#             if 'ytInitialData' not in script.text:
#                 continue
#             m = re.search(r'var ytInitialData\s*=\s*(\{.*?\})(?:;|\s*</script>)', script.text, re.DOTALL)
#             if not m:
#                 m = re.search(r'var ytInitialData\s*=\s*(\{.*)', script.text, re.DOTALL)
#             if not m:
#                 break
#             data = json.loads(m.group(1).rstrip(';'))
#             contents = (
#                 data['contents']['twoColumnSearchResultsRenderer']
#                     ['primaryContents']['sectionListRenderer']
#                     ['contents'][0]['itemSectionRenderer']['contents']
#             )
#             for item in contents:
#                 if 'videoRenderer' not in item:
#                     continue
#                 vd = item['videoRenderer']
#                 vid = vd.get('videoId', '')
#                 title = vd.get('title', {}).get('runs', [{}])[0].get('text', '')
#                 thumbs = vd.get('thumbnail', {}).get('thumbnails', [])
#                 thumb = thumbs[-1]['url'] if thumbs else f'https://i.ytimg.com/vi/{vid}/mqdefault.jpg'
#                 dur = vd.get('lengthText', {}).get('simpleText', '')
#                 results.append({
#                     'id': vid, 'title': title, 'thumbnail': thumb,
#                     'duration': dur, 'source': 'youtube', 'type': 'video',
#                     'embed_url': f'https://www.youtube.com/embed/{vid}?autoplay=1&rel=0',
#                     'page_url': f'https://www.youtube.com/watch?v={vid}',
#                     'rating': '', 'genre': '', 'year': '',
#                 })
#             break
#     except Exception as e:
#         print(f"[YouTube] {e}")
#     return results


# # ══════════════════════════════════════════════════════════════
# #  2. DAILYMOTION  (pakai API resmi mereka, jadi bukan scraping HTML)
# # ══════════════════════════════════════════════════════════════
# def scrape_dailymotion(query):
#     api = (
#         "https://api.dailymotion.com/videos"
#         f"?search={requests.utils.quote(query)}"
#         "&fields=id,title,thumbnail_480_url,duration,embed_url,url"
#         "&limit=20&flags=no_live"
#     )
#     results = []
#     try:
#         data = get(api).json()
#         for item in data.get('list', []):
#             vid = item.get('id', '')
#             mins, secs = divmod(int(item.get('duration', 0)), 60)
#             dur = f"{mins}:{secs:02d}" if item.get('duration') else ''
#             results.append({
#                 'id': vid, 'title': item.get('title', ''),
#                 'thumbnail': item.get('thumbnail_480_url', ''),
#                 'duration': dur, 'source': 'dailymotion', 'type': 'video',
#                 'embed_url': (item.get('embed_url') or f'https://www.dailymotion.com/embed/video/{vid}') + '?autoplay=1',
#                 'page_url': item.get('url', f'https://www.dailymotion.com/video/{vid}'),
#                 'rating': '', 'genre': '', 'year': '',
#             })
#     except Exception as e:
#         print(f"[Dailymotion] {e}")
#     return results


# # ══════════════════════════════════════════════════════════════
# #  3. VIMEO
# # ══════════════════════════════════════════════════════════════
# def scrape_vimeo(query):
#     url = f"https://vimeo.com/search?q={requests.utils.quote(query)}"
#     results = []
#     try:
#         soup = BeautifulSoup(get(url).text, 'html.parser')
#         for script in soup.find_all('script', type='application/ld+json'):
#             try:
#                 data = json.loads(script.string or '{}')
#                 items = data if isinstance(data, list) else [data]
#                 for item in items:
#                     if item.get('@type') != 'VideoObject':
#                         continue
#                     m = re.search(r'vimeo\.com/(\d+)', item.get('url', ''))
#                     if not m:
#                         continue
#                     vid = m.group(1)
#                     thumb = item.get('thumbnailUrl', '')
#                     if isinstance(thumb, list):
#                         thumb = thumb[0] if thumb else ''
#                     dur = ''
#                     raw = item.get('duration', '')
#                     if raw:
#                         dm = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', raw)
#                         if dm:
#                             h, mi, s = dm.group(1), dm.group(2), dm.group(3)
#                             p = []
#                             if h: p.append(h)
#                             p += [(mi or '0'), (s or '0').zfill(2)]
#                             dur = ':'.join(p)
#                     results.append({
#                         'id': vid, 'title': item.get('name', ''),
#                         'thumbnail': thumb or f'https://vumbnail.com/{vid}.jpg',
#                         'duration': dur, 'source': 'vimeo', 'type': 'video',
#                         'embed_url': f'https://player.vimeo.com/video/{vid}?autoplay=1',
#                         'page_url': f'https://vimeo.com/{vid}',
#                         'rating': '', 'genre': '', 'year': '',
#                     })
#             except Exception:
#                 pass
#         if not results:
#             seen = set()
#             for a in soup.find_all('a', href=re.compile(r'^/\d{6,}$')):
#                 vid = a['href'].strip('/')
#                 if vid in seen:
#                     continue
#                 seen.add(vid)
#                 results.append({
#                     'id': vid, 'title': a.get_text(strip=True) or f'Vimeo {vid}',
#                     'thumbnail': f'https://vumbnail.com/{vid}.jpg',
#                     'duration': '', 'source': 'vimeo', 'type': 'video',
#                     'embed_url': f'https://player.vimeo.com/video/{vid}?autoplay=1',
#                     'page_url': f'https://vimeo.com/{vid}',
#                     'rating': '', 'genre': '', 'year': '',
#                 })
#                 if len(results) >= 15:
#                     break
#     except Exception as e:
#         print(f"[Vimeo] {e}")
#     return results


# # ══════════════════════════════════════════════════════════════
# #  4. ARCHIVE.ORG  (public domain film & video)
# # ══════════════════════════════════════════════════════════════
# def scrape_archive(query):
#     results = []
#     try:
#         api = (
#             "https://archive.org/advancedsearch.php"
#             f"?q=mediatype:movies+title:({requests.utils.quote(query)})"
#             "&fl=identifier,title,description,year,subject,downloads"
#             "&rows=20&output=json&sort=downloads+desc"
#         )
#         data = get(api).json()
#         docs = data.get('response', {}).get('docs', [])
#         for doc in docs:
#             iid = doc.get('identifier', '')
#             title = doc.get('title', '')
#             if not iid or not title:
#                 continue
#             year = str(doc.get('year', ''))[:4]
#             subject = doc.get('subject', '')
#             if isinstance(subject, list):
#                 subject = ', '.join(subject[:3])
#             results.append({
#                 'id': iid, 'title': title,
#                 'thumbnail': f'https://archive.org/services/img/{iid}',
#                 'duration': '', 'source': 'archive', 'type': 'video',
#                 'embed_url': f'https://archive.org/embed/{iid}?autoplay=1',
#                 'page_url': f'https://archive.org/details/{iid}',
#                 'rating': '', 'genre': subject[:40] if subject else 'Public Domain',
#                 'year': year,
#             })
#     except Exception as e:
#         print(f"[Archive.org] {e}")
#     return results


# ══════════════════════════════════════════════════════════════
#  ╔═══════════════════════════════════════════════════════╗
#  ║  >>> TAMBAH SUMBER BARU DI SINI (contoh: Bstation) <<< ║
#  ╚═══════════════════════════════════════════════════════╝
#
#  1. Cari tahu dulu apakah platform tujuan punya API resmi/publik
#     (jauh lebih stabil daripada scraping HTML, dan biasanya legal
#     dipakai selama sesuai Terms of Service mereka).
#     Kalau tidak ada API, baru scraping HTML dengan BeautifulSoup
#     seperti contoh scrape_vimeo() di atas.
#
#  2. Salin template kosong di bawah ini, isi logikanya, lalu
#     pastikan return-nya list of dict dengan shape yang sama
#     seperti dijelaskan di komentar "SETIAP SCRAPER WAJIB..." atas.
#
#  3. Daftarkan fungsinya ke dict SCRAPERS (di bawah, cari juga
#     tag TAMBAH SUMBER BARU).
#
#  4. Di index.html, cari tag yang sama untuk menambahkan:
#     - warna badge (variabel CSS --bs)
#     - pill filter di navbar
#     - style .pill[data-src="bstation"] dll
#     - entry di objek SRC_META (javascript)
#
def scrape_rebahin(query):
    base = "http://139.59.196.140"
    url  = f"{base}/?s={requests.utils.quote(query)}"
    results = []
    try:
        soup = BeautifulSoup(get(url).text, 'html.parser')
        cards = (
            soup.select('article.item') or
            soup.select('.movies-list .ml-item') or
            soup.select('.result-item article') or
            soup.select('article') or
            soup.select('div.item')
        )
        if not cards:
            soup2 = BeautifulSoup(get(base).text, 'html.parser')
            cards = (
                soup2.select('article.item') or
                soup2.select('div.ml-item') or
                soup2.select('.TPost') or
                soup2.select('article')
            )
        for card in cards[:25]:
            title_el = card.select_one('h2, h3, .Title, .title, a')
            title    = title_el.get_text(strip=True) if title_el else ''
            if not title or len(title) < 2: continue

            link_el  = card.select_one('a[href]')
            page_url = link_el['href'] if link_el else base
            if page_url.startswith('/'):
                page_url = base + page_url

            thumb_el  = card.select_one('img[src], img[data-src], img[data-lazy-src]')
            thumbnail = ''
            if thumb_el:
                thumbnail = (thumb_el.get('data-lazy-src') or
                             thumb_el.get('data-src') or
                             thumb_el.get('src') or '')

            rating_el = card.select_one('.Qlty, .rating, .score, .imdb, span[class*="rat"]')
            rating    = rating_el.get_text(strip=True) if rating_el else ''

            genre_el  = card.select_one('.genres a, .category, .Genre')
            genre     = genre_el.get_text(strip=True) if genre_el else ''

            year_el   = card.select_one('.year, .Year, time, .date')
            year      = year_el.get_text(strip=True)[:4] if year_el else ''

            results.append({
                'id':        re.sub(r'[^a-z0-9]', '-', title.lower())[:40],
                'title':     title,
                'thumbnail': thumbnail,
                'duration':  '',
                'source':    'rebahin',
                'type':      'film',
                'embed_url': page_url,
                'page_url':  page_url,
                'rating':    rating,
                'genre':     genre,
                'year':      year,
            })
    except Exception as e:
        print(f"[REBAHIN] {e}")
    return results


def scrape_lk21(query):
    base = "https://pieandmightymsp.com"
    url  = f"{base}/?s={requests.utils.quote(query)}"
    results = []
    try:
        soup = BeautifulSoup(get(url).text, 'html.parser')
        cards = (
            soup.select('article.item') or
            soup.select('div.item') or
            soup.select('article') or
            soup.select('.movies-list .ml-item')
        )
        if not cards:
            soup2 = BeautifulSoup(get(base).text, 'html.parser')
            cards = (
                soup2.select('article.item') or
                soup2.select('article') or
                soup2.select('div.item') or
                soup2.select('div.ml-item')
            )
        for card in cards[:25]:
            title_el = card.select_one('h2, h3, .title, .itemTitle a')
            title    = title_el.get_text(strip=True) if title_el else ''
            if not title or len(title) < 2: continue

            link_el  = card.select_one('a[href]')
            page_url = link_el['href'] if link_el else base
            if page_url.startswith('/'):
                page_url = base + page_url

            thumb_el  = card.select_one('img[src], img[data-src]')
            thumbnail = ''
            if thumb_el:
                thumbnail = (thumb_el.get('data-src') or
                             thumb_el.get('src') or '')

            rating_el = card.select_one('.rating, .score, .imdb, span.imdb')
            rating    = rating_el.get_text(strip=True) if rating_el else ''

            genre_el  = card.select_one('.genres a, .category a')
            genre     = genre_el.get_text(strip=True) if genre_el else ''

            year_el   = card.select_one('.year, time, .date')
            year      = year_el.get_text(strip=True)[:4] if year_el else ''

            results.append({
                'id':        re.sub(r'[^a-z0-9]', '-', title.lower())[:40],
                'title':     title,
                'thumbnail': thumbnail,
                'duration':  '',
                'source':    'lk21',
                'type':      'film',
                'embed_url': page_url,
                'page_url':  page_url,
                'rating':    rating,
                'genre':     genre,
                'year':      year,
            })
    except Exception as e:
        print(f"[LK21] {e}")
    return results

# ══════════════════════════════════════════════════════════════


def scrape_klikxxi(query):
    base = "https://flagsio.com"
    url  = f"{base}/?s={requests.utils.quote(query)}"
    results = []
    try:
        soup = BeautifulSoup(get(url).text, 'html.parser')
        cards = (
            soup.select('article.item') or
            soup.select('div.item') or
            soup.select('article') or
            soup.select('.movies-list .ml-item') or
            soup.select('.search-page .result-item')
        )
        if not cards:
            soup2 = BeautifulSoup(get(base).text, 'html.parser')
            cards = (
                soup2.select('article.item') or
                soup2.select('div.item') or
                soup2.select('article') or
                soup2.select('div.ml-item')
            )
        for card in cards[:25]:
            title_el = card.select_one('h2, h3, .title, .itemTitle a')
            title    = title_el.get_text(strip=True) if title_el else ''
            if not title: continue

            link_el  = card.select_one('a[href]')
            page_url = link_el['href'] if link_el else base
            if page_url.startswith('/'):
                page_url = base + page_url

            thumb_el  = card.select_one('img[src], img[data-src]')
            thumbnail = ''
            if thumb_el:
                thumbnail = thumb_el.get('data-src') or thumb_el.get('src') or ''

            rating_el = card.select_one('.rating, .score, span.imdb, .rate')
            rating    = rating_el.get_text(strip=True) if rating_el else ''

            genre_el = card.select_one('.genres a, .category a, .genre')
            genre    = genre_el.get_text(strip=True) if genre_el else ''

            year_el = card.select_one('.year, .date, time')
            year    = year_el.get_text(strip=True)[:4] if year_el else ''

            results.append({
                'id':        re.sub(r'[^a-z0-9]', '-', title.lower())[:40],
                'title':     title,
                'thumbnail': thumbnail,
                'duration':  '',
                'source':    'klikxxi',
                'type':      'film',
                'embed_url': page_url,
                'page_url':  page_url,
                'rating':    rating,
                'genre':     genre,
                'year':      year,
            })
    except Exception as e:
        print(f"[KLIKXXI] {e}")
    return results


def scrape_starpathz(query):
    base = "https://starpathz.com"
    url  = f"{base}/?s={requests.utils.quote(query)}"
    results = []
    try:
        soup = BeautifulSoup(get(url).text, 'html.parser')
        cards = (
            soup.select('article.item') or
            soup.select('div.item') or
            soup.select('article') or
            soup.select('.movies-list .ml-item') or
            soup.select('.search-page .result-item')
        )
        if not cards:
            soup2 = BeautifulSoup(get(base).text, 'html.parser')
            cards = (
                soup2.select('article.item') or
                soup2.select('div.item') or
                soup2.select('article') or
                soup2.select('div.ml-item')
            )
        for card in cards[:25]:
            title_el = card.select_one('h2, h3, .title, .itemTitle a')
            title    = title_el.get_text(strip=True) if title_el else ''
            if not title: continue

            link_el  = card.select_one('a[href]')
            page_url = link_el['href'] if link_el else base
            if page_url.startswith('/'):
                page_url = base + page_url

            thumb_el  = card.select_one('img[src], img[data-src]')
            thumbnail = ''
            if thumb_el:
                thumbnail = thumb_el.get('data-src') or thumb_el.get('src') or ''

            rating_el = card.select_one('.rating, .score, span.imdb, .rate')
            rating    = rating_el.get_text(strip=True) if rating_el else ''

            genre_el = card.select_one('.genres a, .category a, .genre')
            genre    = genre_el.get_text(strip=True) if genre_el else ''

            year_el = card.select_one('.year, .date, time')
            year    = year_el.get_text(strip=True)[:4] if year_el else ''

            results.append({
                'id':        re.sub(r'[^a-z0-9]', '-', title.lower())[:40],
                'title':     title,
                'thumbnail': thumbnail,
                'duration':  '',
                'source':    'starpathz',
                'type':      'film',
                'embed_url': page_url,
                'page_url':  page_url,
                'rating':    rating,
                'genre':     genre,
                'year':      year,
            })
    except Exception as e:
        print(f"[STARPATHZ] {e}")
    return results


# ══════════════════════════════════════════════════════════════
#  SCRAPER MAP
#  >>> TAMBAH SUMBER BARU DI SINI: tambahkan baris baru,
#      key = nama source (dipakai di HTML/JS juga), value = fungsinya
# ══════════════════════════════════════
SCRAPERS = {
    # 'youtube':     scrape_youtube,
    # 'dailymotion': scrape_dailymotion,
    # 'vimeo':       scrape_vimeo,
    # 'archive':     scrape_archive,
    'lk21':        scrape_lk21,   # <- contoh cara mendaftarkan sumber baru
    'klikxxi':     scrape_klikxxi, 
    'rebahin':     scrape_rebahin, # <- contoh cara mendaftarkan sumber baru
    'starpathz':   scrape_starpathz, # <- contoh cara mendaftarkan sumber baru
}


# ══════════════════════════════════════════════════════════════
#  ROUTES
# ══════════════════════════════════════════════════════════════
@app.route('/')
def home():
    return send_from_directory('.', 'index.html')


@app.route('/api/videos')
def api_videos():
    rate_limit_check()

    raw_q = request.args.get('q', 'kucing lucu')
    query = re.sub(r'[<>{}\[\]\\;`\'"]', '', raw_q).strip()[:100]
    if not query:
        query = 'video'

    src_raw = request.args.get('sources', ','.join(SCRAPERS.keys()))
    sources = [s.strip() for s in src_raw.split(',') if s.strip() in SCRAPERS][:len(SCRAPERS)]
    if not sources:
        sources = list(SCRAPERS.keys())

    all_results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(SCRAPERS[s], query): s for s in sources}
        for fut in concurrent.futures.as_completed(futs):
            try:
                all_results.extend(fut.result())
            except Exception as e:
                print(f"[{futs[fut]}] thread error: {e}")

    # videos.json ditimpa (overwrite) tiap kali ada pencarian baru,
    # jadi otomatis "kehapus & keganti" seperti yang kamu mau —
    # ini dipakai sebagai fallback offline oleh frontend kalau /api/videos gagal.
    try:
        with open('videos.json', 'w', encoding='utf-8') as f:
            json.dump({"query": query, "videos": all_results}, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    return jsonify(all_results)


@app.route('/api/sources')
def api_sources():
    return jsonify(list(SCRAPERS.keys()))


@app.route('/<path:filename>')
def static_files(filename):
    return send_from_directory('.', filename)


if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 5000))
    print("\n🎬  VideoHub  →  http://127.0.0.1:" + str(port))
    print("    Sumber:", ' · '.join(f'[{k}]' for k in SCRAPERS))
    print()
    app.run(debug=False, host='0.0.0.0', port=port)