"""Lecture « humaine » du log de tinyMediaManager (format logback) : transforme les lignes
brutes en séquences d'étapes (mise à jour, scrape, images, renommage…) avec le résultat par
film, et en alertes dédupliquées. Lecture seule, bibliothèque standard uniquement."""
import re

LINE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),\d+ (\w+)\s+\[([^\]]*)\] (\S+?):(\d+) - (.*)$")
GAP_STEP = 60      # secondes : une étape sans nouvelle ligne depuis ce délai est close
GAP_SEQ = 25       # secondes entre deux étapes d'une même séquence
MAX_ITEMS = 400
MAX_NOTES = 25
SEV = {"ok": 0, "info": 0, "warn": 1, "err": 2}


def secs(ts):
    y, mo, d = int(ts[0:4]), int(ts[5:7]), int(ts[8:10])
    h, mi, s = int(ts[11:13]), int(ts[14:16]), int(ts[17:19])
    return (((y * 12 + mo) * 31 + d) * 24 + h) * 3600 + mi * 60 + s


def short(p):
    p = p.strip("'\"")
    return p.split("/")[-1] if "/" in p else p


def rel(p):
    """Chemin raccourci : .../dossier/fichier"""
    parts = [x for x in p.strip("'\"").split("/") if x]
    return "/".join(parts[-2:]) if len(parts) > 2 else "/".join(parts)


def parse_entries(text):
    cur = None
    for raw in text.splitlines():
        m = LINE.match(raw)
        if m:
            if cur:
                yield cur
            ts, lvl, thread, logger, ln, msg = m.groups()
            cur = {"ts": ts, "lvl": lvl, "thread": thread, "logger": logger.split(".")[-1], "msg": msg, "more": []}
        elif cur and raw.strip() and len(cur["more"]) < 12:
            cur["more"].append(raw.rstrip()[:300])
    if cur:
        yield cur


class Step:
    def __init__(self, kind, title, ts, origin=None):
        self.kind, self.title, self.start, self.end = kind, title, ts, ts
        self.origin, self.ms, self.done = origin, None, False
        self.items, self.index, self.notes = [], {}, []
        self.cache_err = 0
        self.aborted = False
        self.summary = []

    def item(self, name):
        it = self.index.get(name)
        if it is None:
            it = {"name": name, "status": "info", "note": "", "_score": None}
            if len(self.items) < MAX_ITEMS:
                self.items.append(it)
            self.index[name] = it
        return it

    def note(self, lvl, text, more=None):
        if len(self.notes) < MAX_NOTES:
            n = {"lvl": lvl, "text": text}
            if more:
                n["more"] = more
            self.notes.append(n)

    def status(self):
        worst = 0
        for it in self.items:
            worst = max(worst, SEV[it["status"]])
        for n in self.notes:
            worst = max(worst, SEV[n["lvl"]])
        if self.cache_err:
            worst = max(worst, 1)
        return ["ok", "warn", "err"][worst]

    def out(self):
        for it in self.items:
            it.pop("_score", None)
        counts = {"ok": 0, "warn": 0, "err": 0}
        for it in self.items:
            if it["status"] in counts:
                counts[it["status"]] += 1
        notes = list(self.notes)
        if self.cache_err:
            notes.append({"lvl": "warn", "text": "%d image(s) du cache interne non déplacée(s) (sans effet sur vos fichiers)" % self.cache_err})
        return {"kind": self.kind, "title": self.title, "start": self.start, "end": self.end, "ms": self.ms,
                "done": self.done, "origin": self.origin, "status": self.status(), "summary": self.summary,
                "counts": counts, "items": self.items, "notes": notes}


def duration_ms(s):
    m = re.match(r"(\d+):(\d+):(\d+)(?:\.(\d+))?", s)
    if m:
        h, mi, sec, frac = int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4) or "0"
        return ((h * 60 + mi) * 60 + sec) * 1000 + int(float("0." + frac) * 1000)
    return None


MEDIA = {"movies": "films", "movie": "film", "tv shows": "séries", "tvshows": "séries", "tv show": "série",
         "episodes": "épisodes", "episode": "épisode", "movie sets": "sagas", "movie set": "saga",
         "seasons": "saisons", "season": "saison"}


PLURAL = {"movie": "films", "tv show": "séries", "tvshow": "séries", "episode": "épisodes"}


def media(w):
    return MEDIA.get(w.lower().strip(), w)


API_STEPS = {
    "Writing NFO files": ("nfo", "Écriture des NFO"),
    "Cleaning up unwanted files": ("clean", "Nettoyage des fichiers indésirables"),
    "Post processing": ("post", "Post-traitement"),
    "Refreshing Kodi library": ("kodi", "Rafraîchissement Kodi"),
}


def analyse(text, max_steps=80):
    steps, alerts = [], {}
    cur = None
    origin = None
    last_ts = None

    def close():
        nonlocal cur
        cur = None

    def start(kind, title, ts, **kw):
        nonlocal cur, origin
        if cur is not None and cur.kind == "update" and kind == "update":
            cur.done = True
        s = Step(kind, title, ts, origin)
        origin = None
        for k, v in kw.items():
            setattr(s, k, v)
        steps.append(s)
        cur = s
        return s

    def misc(ts):
        nonlocal cur
        if cur and cur.kind == "misc" and secs(ts) - secs(cur.end) <= 30:
            return cur
        return start("misc", "Autre activité", ts)

    def alert(e, text):
        k = (e["lvl"], text)
        a = alerts.get(k)
        if a:
            a["count"] += 1
            a["last"] = e["ts"]
        else:
            alerts[k] = {"lvl": "err" if e["lvl"] in ("ERROR", "FATAL") else "warn", "text": text, "count": 1,
                         "first": e["ts"], "last": e["ts"], "more": e["more"]}

    for e in parse_entries(text):
        ts, lvl, lg, msg = e["ts"], e["lvl"], e["logger"], e["msg"]
        last_ts = ts
        if cur and not cur.done and secs(ts) - secs(cur.end) > GAP_STEP:
            close()
        if lg == "svgSalamandeLogger":
            continue

        # ------------------------------------------------ alertes de fond (hors tâche)
        if lg in ("ImageCacheTask", "ImageCache", "ImageLoader") and lvl in ("WARN", "ERROR"):
            m = re.match(r"Failed to cache file: '(.+?)' - '(.*)'$", msg)
            if m:
                reason = "mémoire insuffisante" if "memory" in m.group(2) else m.group(2)
                alert(e, "Image non mise en cache (%s) : %s" % (reason, rel(m.group(1))))
            else:
                alert(e, msg[:200])
            continue

        # ------------------------------------------------ détails de renommage (DEBUG / TRACE)
        if cur and cur.kind == "rename" and not cur.done and lvl in ("DEBUG", "TRACE", "WARN") and lg in ("Utils", "MovieRenamer", "TvShowRenamer"):
            it = cur.items[-1] if cur.items else None
            m = re.match(r"Successfully moved file from '(.+)' to '(.+)'$", msg)
            if m and it is not None:
                a, b = m.group(1), m.group(2)
                if a != b:
                    it["status"] = "ok"
                    it["note"] = "%s → %s" % (rel(a), rel(b))
                continue
            m = re.match(r"Successfully moved folder (.+) to (.+)$", msg)
            if m and it is not None:
                it["status"] = "ok"
                it["note"] = (it["note"] + " · " if it["note"] else "") + "dossier : %s → %s" % (short(m.group(1)), short(m.group(2)))
                continue
            if msg.startswith("Upgrading movie into it's own dir") and it is not None:
                it["status"] = "ok"
                it["note"] = (it["note"] + " · " if it["note"] else "") + "placé dans son propre dossier"
                it["_own"] = True
                continue
            if lg == "MovieRenamer" and lvl == "WARN" and msg.startswith("Error moving cached file"):
                cur.cache_err += 1
                continue
            if lvl == "WARN":
                cur.note("warn", msg[:240], e["more"])
                if it is not None:
                    it["status"] = "warn"
                continue
            continue

        # ------------------------------------------------ scores de similarité (scrape)
        if lvl == "DEBUG" and cur and cur.kind == "scrape" and not cur.done:
            m = re.match(r"Similarity Score: \[(.*?)\] \[(.*)\]=\[([\d.]+)\]$", msg)
            if m:
                it = cur.index.get(m.group(1))
                sc = float(m.group(3))
                if it is not None and (it["_score"] is None or sc > it["_score"][0]):
                    it["_score"] = (sc, m.group(2))
                continue

        # ------------------------------------------------ origine
        if lvl == "DEBUG":
            m = re.match(r"action fired: (\w+)", msg)
            if m:
                origin = "interface (%s)" % m.group(1)
                continue
            m = re.match(r"HTTP API: (.+?) - '", msg)
            if m:
                kind, title = API_STEPS.get(m.group(1), ("api", m.group(1)))
                start(kind, title, ts, origin="API")
                cur.done = True
                continue
            continue
        if lvl == "TRACE":
            continue

        # ------------------------------------------------ messages INFO / WARN / ERROR
        m = re.match(r"Aborting task queue \(discarding (\d+) tasks\)", msg)
        if m:
            if cur is None and steps and steps[-1].kind == "rename":
                cur_prev = steps[-1]
            else:
                cur_prev = cur
            if cur_prev is not None:
                cur_prev.note("warn", "Annulé : %s tâche(s) jamais exécutée(s)" % m.group(1))
                cur_prev.aborted = True
                if cur_prev.kind == "rename":
                    finish_rename(cur_prev)
                cur_prev.done = True
                cur_prev.end = ts
            continue

        # démarrage
        if msg == "starting tinyMediaManager":
            start("startup", "Démarrage de tinyMediaManager", ts)
            continue
        if cur and cur.kind == "startup" and not cur.done:
            m = re.match(r"tmm\.version\s*: (.+)$", msg)
            if m:
                cur.summary.append("version " + m.group(1))
                continue
            m = re.match(r"==> Loaded (\d+) ([\w ]+?)( \(.*)?$", msg)
            if m:
                cur.note("info", "Chargé : %s %s" % (m.group(1), media(m.group(2))))
                continue
            if msg == "UI loaded":
                cur.done = True
                cur.note("info", "Interface prête")
                continue
            if lg == "TinyMediaManager" or lvl == "INFO":
                if lvl == "INFO":
                    continue

        # mise à jour des sources
        m = re.match(r'Starting "update data sources" on datasource: (.+)$', msg)
        if m:
            s = start("update", "Mise à jour de la source %s" % m.group(1), ts)
            s.summary = []
            continue
        if "UpdateDatasourceTask" in lg and cur and cur.kind == "update":
            m = re.match(r"New (movies|TV shows|episodes) found: (\d+)", msg)
            if m:
                cur.summary.insert(0, "nouveaux %s : %s" % (media(m.group(1)), m.group(2)))
                continue
            m = re.match(r"Files found: (\d+)", msg)
            if m:
                cur.note("info", "%s fichiers parcourus" % m.group(1))
                continue
            m = re.match(r"Total (\w+(?: \w+)?) count: (\d+)", msg)
            if m:
                cur.note("info", "Total : %s %s" % (m.group(2), PLURAL.get(m.group(1).lower(), m.group(1))))
                continue
            m = re.match(r"Finished updating data sources.*took (\S+)", msg)
            if m:
                cur.ms = duration_ms(m.group(1))
                cur.done = True
                cur.end = ts
                continue
            if lvl in ("WARN", "ERROR"):
                cur.note(SEV_NAME(lvl), msg[:240], e["more"])
            continue

        # scrape
        m = re.match(r"Scraping (\d+) ([\w ]+?) with '(.+?)'", msg)
        if m and "Task" in lg:
            start("scrape", "Scrape de %s %s (%s)" % (m.group(1), media(m.group(2)), m.group(3)), ts)
            continue
        if cur and cur.kind == "scrape" and not cur.done:
            m = re.match(r"Searching for (?:[\w ]+?) '(.*)'$", msg)
            if m and "Task" in lg:
                cur.item(m.group(1))
                continue
            m = re.match(r"Found '(\d+)' results for .* title '(.*)'$", msg)
            if m:
                it = cur.item(m.group(2))
                it["found"] = int(m.group(1))
                continue
            m = re.match(r"Scraping (?:[\w ]+?) '(.*)' with '(.+?)'$", msg)
            if m:
                it = cur.item(m.group(1))
                it["status"] = "ok"
                it["note"] = "scrapé (%s)" % m.group(2)
                continue
            m = re.match(r"Score \(([\d.]+)\) is lower than minimum score \(([\d.]+)\) for '(.*)' - ignore result", msg)
            if m:
                it = cur.item(m.group(3))
                it["status"] = "warn"
                it["note"] = "non scrapé : meilleur score %.2f < seuil %.2f" % (float(m.group(1)), float(m.group(2)))
                if it["_score"]:
                    it["note"] += " (« %s »)" % it["_score"][1]
                continue
            m = re.match(r"Finished scraping .*took (\d+) ms", msg)
            if m:
                cur.ms = int(m.group(1))
                cur.done = True
                cur.end = ts
                for it in cur.items:
                    if it["status"] == "info":
                        if it.get("found") == 0:
                            it["status"], it["note"] = "warn", "aucun résultat"
                        else:
                            it["status"], it["note"] = "warn", "non scrapé (aucune correspondance retenue)"
                    it.pop("found", None)
                ok = sum(1 for it in cur.items if it["status"] == "ok")
                cur.summary = ["%d scrapé(s)" % ok] + (["%d non scrapé(s)" % (len(cur.items) - ok)] if len(cur.items) > ok else [])
                continue
            if lg == "MovieList":
                continue
            if lvl in ("WARN", "ERROR"):
                cur.note(SEV_NAME(lvl), msg[:240], e["more"])
            continue

        # images manquantes
        m = re.match(r"Getting missing artwork for '(\d+)' ([\w ]+)", msg)
        if m:
            start("artwork", "Images manquantes pour %s %s" % (m.group(1), media(m.group(2))), ts)
            continue
        if cur and cur.kind == "artwork" and not cur.done:
            m = re.match(r"Download missing artwork for (?:[\w ]+?) '(.*)'$", msg)
            if m:
                it = cur.item(m.group(1))
                it["status"], it["note"] = "ok", "images téléchargées"
                continue
            m = re.match(r"Finished getting missing artwork - took (\d+) ms", msg)
            if m:
                cur.ms, cur.done, cur.end = int(m.group(1)), True, ts
                cur.summary = ["%d mis à jour" % len(cur.items)] if cur.items else ["rien à télécharger"]
                continue
            if lvl in ("WARN", "ERROR"):
                cur.note(SEV_NAME(lvl), msg[:240], e["more"])
            continue

        # renommage
        m = re.match(r"Renaming '(\d+)' ([\w ]+)", msg)
        if m:
            start("rename", "Renommage de %s %s" % (m.group(1), media(m.group(2))), ts)
            continue
        if cur and cur.kind == "rename" and not cur.done:
            m = re.match(r"Renaming (?:[\w ]+?): (.*)$", msg)
            if m:
                # l'élément précédent sans déplacement = déjà conforme
                it = cur.item(m.group(1))
                it["status"], it["note"] = "info", ""
                continue
            m = re.match(r"Finished renaming .*took (\d+) ms", msg)
            if m:
                cur.ms, cur.done, cur.end = int(m.group(1)), True, ts
                finish_rename(cur)
                continue
            if lvl in ("WARN", "ERROR"):
                cur.note(SEV_NAME(lvl), msg[:240], e["more"])
            continue
        # nettoyage
        if "CleanUpUnwantedFilesTask" in lg:
            m = re.match(r"Start cleanup of unwanted file types: (.*)$", msg)
            if m:
                if cur and cur.kind == "clean":
                    cur.note("info", "Types supprimés : " + m.group(1))
                else:
                    s = start("clean", "Nettoyage des fichiers indésirables", ts)
                    s.note("info", "Types supprimés : " + m.group(1))
                    s.done = True
                continue

        # recherche manuelle depuis l'interface, etc.
        m = re.match(r"Search '(.+?)' for (?:[\w ]+?) title '(.*)'$", msg)
        if m:
            s = misc(ts)
            s.note("info", "Recherche « %s » (%s)" % (m.group(2), m.group(1)))
            s.end = ts
            continue
        m = re.match(r"Found '(\d+)' results for .* title '(.*)'$", msg)
        if m:
            s = misc(ts)
            s.note("info", "%s résultat(s) pour « %s »" % (m.group(1), m.group(2)))
            s.end = ts
            continue
        m = re.match(r"Scraping (?:[\w ]+?) '(.*)' with '(.+?)'$", msg)
        if m:
            s = misc(ts)
            s.title = "Scrape manuel (interface)"
            s.note("info", "« %s » scrapé (%s)" % (m.group(1), m.group(2)))
            s.end = ts
            continue

        # tout le reste en WARN/ERROR : dans l'étape en cours ou en alerte
        if lvl in ("WARN", "ERROR", "FATAL"):
            if cur and not cur.done:
                cur.note(SEV_NAME(lvl), msg[:240], e["more"])
            elif steps and secs(ts) - secs(steps[-1].end) <= 10:
                steps[-1].note(SEV_NAME(lvl), msg[:240], e["more"])
            else:
                alert(e, msg[:240])
            continue
        # INFO ignorés (bruit)

        if cur:
            cur.end = ts

    # ------------------------------------------------ séquences
    seqs = []
    for s in steps:
        if s.kind == "startup":
            seqs.append({"steps": [s]})
            continue
        if seqs and seqs[-1]["steps"][-1].kind != "startup" and s.kind != "misc" \
                and secs(s.start) - secs(seqs[-1]["steps"][-1].end) <= GAP_SEQ:
            seqs[-1]["steps"].append(s)
        else:
            seqs.append({"steps": [s]})
    out = []
    for q in seqs[-max_steps:]:
        st = [s.out() for s in q["steps"]]
        worst = max(SEV[x["status"]] for x in st)
        names = []
        for x in st:
            for it in x["items"]:
                if it["name"] not in names:
                    names.append(it["name"])
        out.append({"start": st[0]["start"], "end": max(x["end"] for x in st), "status": ["ok", "warn", "err"][worst],
                    "origin": st[0]["origin"], "names": names[:3], "total": len(names), "steps": st})
    out.reverse()
    al = sorted(alerts.values(), key=lambda a: a["last"], reverse=True)[:60]
    return {"sequences": out, "alerts": al, "last": last_ts}


def SEV_NAME(lvl):
    return "err" if lvl in ("ERROR", "FATAL") else "warn" if lvl == "WARN" else "info"


def finish_rename(step):
    moved = renamed = 0
    for it in step.items:
        it.pop("_own", None)
        if it["status"] == "ok":
            moved += 1
        elif it["status"] == "info":
            it["note"] = "déjà conforme, rien à changer"
            it["status"] = "ok"
            renamed += 1
    if getattr(step, "aborted", False):
        step.summary = ["%d traité(s) avant annulation" % len(step.items)]
    else:
        step.summary = ["%d renommé(s)" % moved] + (["%d déjà conforme(s)" % renamed] if renamed else [])
