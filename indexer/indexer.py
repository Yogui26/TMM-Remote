#!/usr/bin/env python3
"""Indexeur en lecture seule pour TMM Remote.

Parcourt le dossier de médias (NFO, images, sous-titres) pour afficher la
bibliothèque, et lit les logs de tinyMediaManager. N'écrit jamais rien.
Écoute uniquement sur 127.0.0.1 : c'est nginx qui l'expose sous /lib/.
Bibliothèque standard uniquement.
"""
import json
import mimetypes
import os
import re
import sys
import threading
import time
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

MEDIA_DIR = os.environ.get("MEDIA_DIR", "/media")
DATA_DIR = os.environ.get("DATA_DIR", "/data")
# Chemin des médias tel que le voit le conteneur tinyMediaManager (pour les actions ciblées)
TMM_MEDIA_PATH = (os.environ.get("TMM_MEDIA_PATH", "/media") or "/media").rstrip("/")
HOST = os.environ.get("INDEXER_HOST", "127.0.0.1")
PORT = int(os.environ.get("INDEXER_PORT", "8081"))

VIDEO_EXT = {".mkv", ".mp4", ".avi", ".m4v", ".mov", ".wmv", ".ts", ".m2ts", ".mpg", ".mpeg",
             ".iso", ".flv", ".webm", ".divx", ".vob"}
SUB_EXT = {".srt", ".sub", ".ass", ".ssa", ".vtt", ".idx", ".sup"}
IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".tbn"}  # .tbn : jpeg renommé (Emby / Kodi)
POSTER_STEMS = ("poster", "folder", "cover", "default", "movie")  # noms d'affiche reconnus par Emby
POSTER_SUFFIXES = ("-poster", "-cover")
FANART_RE = re.compile(r"(?i)(^|-)(fanart|backdrop|background)$")
SKIP_DIRS = {"@eaDir", "#recycle", "lost+found", ".Trash-1000", "$RECYCLE.BIN"}
EP_RE = re.compile(r"(?i)(?:\bs\d{1,3}[ ._-]?e\d{1,4}|\b\d{1,2}x\d{2,3}\b)")
SEASON_RE = re.compile(r"(?i)^(season|saison|staffel|specials?|s\d{1,2})[ ._-]*\d*$")
YEAR_RE = re.compile(r"[(\[. ](19\d\d|20\d\d)[)\]. ]?")
NFO_ROOT_RE = re.compile(r"<(movie|tvshow|episodedetails)\b.*</\1>", re.S)

_lock = threading.Lock()
_cache = {"movie": None, "tvshow": None, "at": 0}


# --------------------------------------------------------------- utilitaires
def log(msg):
    print("indexeur: " + msg, flush=True)


def safe_join(base, rel):
    """Chemin absolu de `rel` sous `base`, ou None s'il en sort (anti « .. » et liens)."""
    base_real = os.path.realpath(base)
    target = os.path.realpath(os.path.join(base_real, rel))
    if target == base_real or target.startswith(base_real + os.sep):
        return target
    return None


def relpath(abs_path):
    r = os.path.relpath(abs_path, os.path.realpath(MEDIA_DIR))
    return "" if r == "." else r.replace(os.sep, "/")


def tmm_path(rel):
    return TMM_MEDIA_PATH + ("/" + rel if rel else "")


def parse_nfo(path):
    """Retourne (balise_racine, élément) ou (None, None). Tolère le texte après le XML."""
    try:
        with open(path, "rb") as f:
            raw = f.read(2_000_000)
        text = raw.decode("utf-8-sig", errors="replace")
        m = NFO_ROOT_RE.search(text)
        if not m:
            return None, None
        root = ET.fromstring(m.group(0))
        return root.tag, root
    except (OSError, ET.ParseError, ValueError):
        return None, None


def txt(el, tag):
    e = el.find(tag)
    return (e.text or "").strip() if e is not None and e.text else ""


ID_TAGS = {"tmdbid": "tmdb", "imdbid": "imdb", "imdb_id": "imdb", "tvdbid": "tvdb", "tvmazeid": "tvmaze"}


def nfo_ids(el):
    """Identifiants : <uniqueid type="…"> (Kodi, Emby ≥ 4.6) et balises Emby <tmdbid>, <imdbid>, <tvdbid>."""
    ids = {}
    for tag, name in ID_TAGS.items():
        v = txt(el, tag)
        if v:
            ids[name] = v
    for u in el.findall("uniqueid"):
        t, v = (u.get("type") or "").strip().lower(), (u.text or "").strip()
        if t and v:
            ids[t] = v
    return ids


def nfo_info(el, full=False):
    rating = ""
    r = el.find("ratings/rating/value")
    if r is not None and r.text:
        rating = r.text.strip()
    elif txt(el, "rating"):
        rating = txt(el, "rating")
    elif txt(el, "criticrating"):  # Emby
        rating = txt(el, "criticrating")
    year = (txt(el, "year") or txt(el, "productionyear") or txt(el, "premiered")[:4]
            or txt(el, "releasedate")[:4] or txt(el, "aired")[:4])
    info = {"title": txt(el, "title"), "year": year, "rating": rating[:4]}
    if full:
        s = el.find("set")  # Kodi : <set><name>…</name></set> ; Emby : <set>Nom</set>
        collection = ""
        if s is not None:
            collection = txt(s, "name") or (s.text or "").strip()
        info.update({
            "originaltitle": txt(el, "originaltitle"),
            "plot": txt(el, "plot") or txt(el, "outline"),
            "tagline": txt(el, "tagline"),
            "runtime": txt(el, "runtime"),
            "genres": [g.text.strip() for g in el.findall("genre") if g.text],
            "ids": nfo_ids(el),
            "collection": collection,
            "status": txt(el, "status"),
        })
    return info


def lang_of(name):
    stem = os.path.splitext(name)[0]
    tok = stem.rsplit(".", 1)[-1].lower() if "." in stem else ""
    return tok if 2 <= len(tok) <= 3 and tok.isalpha() else "?"


def classify(entries):
    """Trie les fichiers d'un dossier."""
    videos, nfos, imgs, subs = [], [], [], []
    for e in entries:
        ext = os.path.splitext(e)[1].lower()
        if ext in VIDEO_EXT:
            videos.append(e)
        elif ext == ".nfo":
            nfos.append(e)
        elif ext in IMG_EXT:
            imgs.append(e)
        elif ext in SUB_EXT:
            subs.append(e)
    return videos, nfos, imgs, subs


def pick_poster(imgs):
    """Affiche selon les noms reconnus par Emby : poster, folder, cover, default, movie, <nom>-poster, <nom>-cover."""
    stems = {i: os.path.splitext(i)[0].lower() for i in imgs}
    for key in POSTER_STEMS:
        for i in sorted(imgs):
            if stems[i] == key:
                return i
    for i in sorted(imgs):
        if stems[i].endswith(POSTER_SUFFIXES):
            return i
    return None


def has_fanart(imgs):
    return any(FANART_RE.search(os.path.splitext(i)[0]) for i in imgs)


def list_dir(path):
    try:
        with os.scandir(path) as it:
            files, dirs = [], []
            for e in it:
                (dirs if e.is_dir(follow_symlinks=False) else files).append(e.name)
            return sorted(files), sorted(dirs)
    except OSError:
        return [], []


def mtime(path):
    try:
        return int(os.stat(path).st_mtime)
    except OSError:
        return 0


# --------------------------------------------------------------------- scan
def movie_item(abs_dir, files, dirs):
    videos, nfos, imgs, subs = classify(files)
    info = {"title": "", "year": "", "rating": ""}
    has_nfo = False
    stems = [os.path.splitext(v)[0] for v in videos]
    ordered = [n for n in nfos if n.lower() == "movie.nfo"] + \
              [n for n in nfos if os.path.splitext(n)[0] in stems] + nfos
    for n in ordered:
        tag, el = parse_nfo(os.path.join(abs_dir, n))
        if tag == "movie":
            info = nfo_info(el)
            has_nfo = True
            break
    folder = os.path.basename(abs_dir) or "(racine)"
    rel = relpath(abs_dir)
    if not info["title"]:
        info["title"] = YEAR_RE.sub(" ", folder).strip(" ._-") or folder
    if not info["year"]:
        m = YEAR_RE.search(folder)
        info["year"] = m.group(1) if m else ""
    poster = pick_poster(imgs)
    return {
        "id": rel, "kind": "movie", "title": info["title"], "year": info["year"], "rating": info["rating"],
        "folder": folder, "tmm_path": tmm_path(rel),
        "has_nfo": has_nfo, "has_poster": bool(poster), "has_fanart": has_fanart(imgs),
        "poster": (rel + "/" + poster).lstrip("/") if poster else None,
        "subs": sorted({lang_of(s) for s in subs}), "videos": len(videos),
        "shared": len(videos) > 1, "added": mtime(abs_dir),
    }


def show_item(abs_dir):
    """Résumé d'une série : dossier racine + saisons + épisodes."""
    files, dirs = list_dir(abs_dir)
    _, nfos, imgs, _ = classify(files)
    info = {"title": "", "year": "", "rating": ""}
    has_nfo = False
    if "tvshow.nfo" in files:
        tag, el = parse_nfo(os.path.join(abs_dir, "tvshow.nfo"))
        if tag == "tvshow":
            info, has_nfo = nfo_info(el), True
    folder = os.path.basename(abs_dir)
    rel = relpath(abs_dir)
    if not info["title"]:
        info["title"] = YEAR_RE.sub(" ", folder).strip(" ._-") or folder
    ep = ep_nfo = ep_sub = seasons = 0
    newest = mtime(abs_dir)
    for dirpath, dnames, fnames in os.walk(abs_dir):
        dnames[:] = [d for d in dnames if d not in SKIP_DIRS and not d.startswith(".")]
        v, n, _, s = classify(fnames)
        if dirpath != abs_dir:
            seasons += 1 if v else 0
            newest = max(newest, mtime(dirpath))
        stems = {os.path.splitext(x)[0] for x in n}
        ep += len(v)
        ep_nfo += sum(1 for x in v if os.path.splitext(x)[0] in stems)
        ep_sub += len(s)
    poster = pick_poster(imgs)
    return {
        "id": rel, "kind": "tvshow", "title": info["title"], "year": info["year"], "rating": info["rating"],
        "folder": folder, "tmm_path": tmm_path(rel),
        "has_nfo": has_nfo, "has_poster": bool(poster), "has_fanart": has_fanart(imgs),
        "poster": (rel + "/" + poster).lstrip("/") if poster else None,
        "subs": ["%d" % ep_sub] if ep_sub else [], "videos": ep, "seasons": seasons,
        "episodes_nfo": ep_nfo, "shared": False, "added": newest,
    }


def scan():
    movies, shows = [], []
    base = os.path.realpath(MEDIA_DIR)
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        videos = classify(filenames)[0]
        is_show = ("tvshow.nfo" in filenames
                   or any(SEASON_RE.match(d) for d in dirnames)
                   or (videos and any(EP_RE.search(v) for v in videos)))
        if is_show and dirpath != base:
            shows.append(show_item(dirpath))
            dirnames[:] = []
        elif videos:
            movies.append(movie_item(dirpath, filenames, dirnames))
    movies.sort(key=lambda x: x["title"].lower())
    shows.sort(key=lambda x: x["title"].lower())
    return movies, shows


def library(kind, refresh=False):
    with _lock:
        if refresh or _cache[kind] is None:
            t0 = time.time()
            movies, shows = scan()
            _cache.update({"movie": movies, "tvshow": shows, "at": int(time.time())})
            log("scan : %d films, %d séries en %.1f s" % (len(movies), len(shows), time.time() - t0))
        return _cache[kind], _cache["at"]


# ------------------------------------------------------------------- détail
def item_detail(kind, rel):
    abs_dir = safe_join(MEDIA_DIR, rel)
    if not abs_dir or not os.path.isdir(abs_dir):
        return None
    files, dirs = list_dir(abs_dir)
    out = {"id": rel, "kind": kind, "folder": os.path.basename(abs_dir), "tmm_path": tmm_path(rel)}
    if kind == "movie":
        for n in [x for x in files if x.lower().endswith(".nfo")]:
            tag, el = parse_nfo(os.path.join(abs_dir, n))
            if tag == "movie":
                out.update(nfo_info(el, full=True))
                break
        out["files"] = []
        for n in files[:300]:
            try:
                size = os.stat(os.path.join(abs_dir, n)).st_size
            except OSError:
                size = 0
            out["files"].append({"name": n, "size": size})
    else:
        if "tvshow.nfo" in files:
            tag, el = parse_nfo(os.path.join(abs_dir, "tvshow.nfo"))
            if tag == "tvshow":
                out.update(nfo_info(el, full=True))
        seasons = []
        for dirpath, dnames, fnames in os.walk(abs_dir):
            dnames[:] = sorted(d for d in dnames if d not in SKIP_DIRS and not d.startswith("."))
            v, n, _, s = classify(fnames)
            if v:
                stems = {os.path.splitext(x)[0] for x in n}
                seasons.append({
                    "name": os.path.relpath(dirpath, abs_dir).replace(os.sep, "/") if dirpath != abs_dir else "(racine)",
                    "episodes": len(v),
                    "with_nfo": sum(1 for x in v if os.path.splitext(x)[0] in stems),
                    "subs": len(s), "sample": v[:3],
                })
        out["seasons"] = seasons
        out["files"] = [{"name": n, "size": 0} for n in files[:100]]
    return out


# --------------------------------------------------------------------- logs
def log_dirs():
    return [d for d in (os.path.join(DATA_DIR, "logs"), os.path.join(DATA_DIR, "data", "logs")) if os.path.isdir(d)]


def list_logs():
    names = []
    for d in log_dirs():
        for n in sorted(os.listdir(d)):
            if n.endswith(".log") and os.path.isfile(os.path.join(d, n)) and n not in names:
                names.append(n)
    return names


def read_log(name, lines):
    if name not in list_logs():
        return None
    path = next(os.path.join(d, name) for d in log_dirs() if os.path.isfile(os.path.join(d, name)))
    size = os.path.getsize(path)
    chunk = min(size, 600_000)
    with open(path, "rb") as f:
        f.seek(size - chunk)
        data = f.read(chunk).decode("utf-8", errors="replace")
    rows = data.splitlines()
    if size > chunk and rows:
        rows = rows[1:]  # première ligne probablement coupée
    return {"file": name, "size": size, "mtime": mtime(path), "lines": rows[-lines:]}


# --------------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "tmm-remote-indexer"

    def log_message(self, fmt, *args):  # silence : nginx journalise déjà
        pass

    def send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path == "/lib/api/status":
                return self.send_json(self.status())
            if u.path == "/lib/api/library":
                kind = q.get("kind", "movie")
                if kind not in ("movie", "tvshow"):
                    return self.send_json({"error": "kind invalide"}, 400)
                if not os.path.isdir(MEDIA_DIR):
                    return self.send_json({"error": "dossier de médias absent"}, 404)
                items, at = library(kind, q.get("refresh") == "1")
                return self.send_json({"kind": kind, "indexed_at": at, "items": items})
            if u.path == "/lib/api/item":
                d = item_detail(q.get("kind", "movie"), q.get("id", ""))
                return self.send_json(d) if d else self.send_json({"error": "introuvable"}, 404)
            if u.path == "/lib/api/log":
                names = list_logs()
                name = q.get("file") or ("tmm.log" if "tmm.log" in names else (names[0] if names else ""))
                try:
                    lines = max(10, min(int(q.get("lines", "300")), 2000))
                except ValueError:
                    lines = 300
                d = read_log(name, lines) if name else None
                return self.send_json(d) if d else self.send_json({"error": "log introuvable", "files": names}, 404)
            if u.path == "/lib/img":
                return self.send_image(q.get("p", ""))
            self.send_json({"error": "route inconnue"}, 404)
        except Exception as e:  # ne jamais faire tomber le service
            log("erreur : %r" % (e,))
            self.send_json({"error": "erreur interne"}, 500)

    def status(self):
        media_ok = os.path.isdir(MEDIA_DIR)
        try:
            media_ok = media_ok and bool(os.listdir(MEDIA_DIR))
        except OSError:
            media_ok = False
        logs = list_logs()
        return {"enabled": media_ok or bool(logs), "media": media_ok, "tmm_media_path": TMM_MEDIA_PATH,
                "logs": logs, "indexed_at": _cache["at"],
                "counts": {k: (len(_cache[k]) if _cache[k] is not None else None) for k in ("movie", "tvshow")}}

    def send_image(self, rel):
        path = safe_join(MEDIA_DIR, rel)
        ext = os.path.splitext(rel)[1].lower()
        if not path or ext not in IMG_EXT or not os.path.isfile(path):
            return self.send_json({"error": "image introuvable"}, 404)
        size = os.path.getsize(path)
        ctype = mimetypes.guess_type(path)[0]
        if not ctype:  # .tbn : jpeg ou png renommé, on lit l'en-tête
            with open(path, "rb") as f:
                head = f.read(8)
            ctype = "image/jpeg" if head[:3] == b"\xff\xd8\xff" else "image/png" if head[:4] == b"\x89PNG" else "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(size))
        self.send_header("Cache-Control", "public, max-age=3600")
        self.end_headers()
        with open(path, "rb") as f:
            while True:
                buf = f.read(65536)
                if not buf:
                    break
                self.wfile.write(buf)


def main():
    log("écoute sur %s:%d (médias : %s, données : %s)" % (HOST, PORT, MEDIA_DIR, DATA_DIR))
    ThreadingHTTPServer.daemon_threads = True
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
