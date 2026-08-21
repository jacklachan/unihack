"""Dashboard server.

Standard library only -- ``python -m caliper serve`` needs no pip install and
no build step, which matters because the people evaluating this will run it
once, on their own machine, without reading the setup notes.

Serves the enrichment view, the per-cell evidence panel, the induced category
specs, the review queue and the scoreboard, plus a live upload endpoint that
runs the full pipeline on a file dropped into the browser.
"""
from __future__ import annotations

import io
import json
import mimetypes
import os
import posixpath
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional, Tuple

from ..io.tabular import read_table, write_csv
from ..pipeline import Pipeline, RowResult
from ..schema import DELIVERY_COLUMNS, detect_schema

_HERE = os.path.dirname(os.path.abspath(__file__))
_STATIC = os.path.join(_HERE, "static")


class State:
    """In-memory results for the running dashboard."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.results: List[RowResult] = []
        self.report: Dict[str, Any] = {}
        self.source_name: str = ""
        self.queue: List[Dict[str, Any]] = []
        self.edges: List[Dict[str, Any]] = []
        # Session AI settings. The key lives in this process's memory for the
        # lifetime of the server and is never written to disk, never logged and
        # never echoed back to the browser.
        self.provider: str = ""
        self.api_key: str = ""
        self.use_audit: bool = False
        self.model_name: str = ""
        # Live progress for the browser to poll while a run is in flight.
        self.progress: Dict[str, Any] = {
            "running": False, "done": 0, "total": 0, "stage": "",
            "started": 0.0, "finished": True, "error": "", "notice": ""}

    def load_from_disk(self, data_dir: str) -> None:
        rep = os.path.join(data_dir, "report.json")
        graphs = os.path.join(data_dir, "graphs.json")
        if os.path.exists(rep):
            with open(rep, "r", encoding="utf-8") as fh:
                self.report = json.load(fh)
        if os.path.exists(graphs):
            with open(graphs, "r", encoding="utf-8") as fh:
                self._cached_rows = json.load(fh)
        else:
            self._cached_rows = []
        deliv = os.path.join(data_dir, "delivery.csv")
        if os.path.exists(deliv):
            rows, _ = read_table(deliv)
            self._cached_delivery = rows
            self.source_name = os.path.basename(deliv)
        else:
            self._cached_delivery = []
        q = os.path.join(data_dir, "review_queue.csv")
        if os.path.exists(q):
            self.queue, _ = read_table(q)
        g = os.path.join(data_dir, "relationships.csv")
        if os.path.exists(g):
            self.edges, _ = read_table(g)

    def set_results(self, results: List[RowResult], report: Dict[str, Any],
                    name: str) -> None:
        with self.lock:
            self.results = results
            self.report = report
            self.source_name = name
            self._cached_rows = [r.to_dict() for r in results]
            self._cached_delivery = [r.delivery for r in results]
            from ..cli import export_review_queue
            self.queue = export_review_queue(results)
            self.edges = [e.to_dict() for e in getattr(self, "_last_edges", [])]

    # -- views -------------------------------------------------------------
    def rows_page(self, offset: int, limit: int, status: str = "",
                  query: str = "") -> Dict[str, Any]:
        rows = getattr(self, "_cached_rows", [])
        deliv = getattr(self, "_cached_delivery", [])
        idx = list(range(len(rows)))
        if status:
            idx = [i for i in idx if rows[i].get("status") == status]
        if query:
            q = query.lower()
            idx = [i for i in idx
                   if q in json.dumps(deliv[i] if i < len(deliv) else {}).lower()]
        total = len(idx)
        page = idx[offset:offset + limit]
        out = []
        for i in page:
            d = deliv[i] if i < len(deliv) else {}
            g = rows[i]
            out.append({
                "index": i,
                "status": g.get("status"),
                "score": g.get("score"),
                "family_id": g.get("family_id"),
                "filled": g.get("filled"),
                "part_number": d.get("Mfg_Part_Num", ""),
                "source_desc": d.get("Part_Desc", ""),
                "brand": d.get("BRAND_NAME", ""),
                "classpath": d.get("Classpath", ""),
                "product_name": d.get("Product Name", ""),
                "invoice": d.get("INVOICE_DESC", ""),
                "mobile": d.get("MOBILE_DESC", ""),
                "short": d.get("SHORT_DESC", ""),
                "n_flags": len(g.get("flags", [])),
                "n_violations": len(g.get("violations", [])),
            })
        return {"total": total, "offset": offset, "limit": limit, "rows": out}

    def row_detail(self, i: int) -> Dict[str, Any]:
        rows = getattr(self, "_cached_rows", [])
        deliv = getattr(self, "_cached_delivery", [])
        if i < 0 or i >= len(rows):
            return {}
        d = deliv[i] if i < len(deliv) else {}
        populated = {k: v for k, v in d.items() if str(v).strip()}
        prov = {}
        if i < len(self.results):
            prov = self.results[i].provenance
        return {"index": i, "delivery": populated, "graph": rows[i],
                "provenance": prov, "columns": DELIVERY_COLUMNS}


STATE = State()


class Handler(BaseHTTPRequestHandler):
    server_version = "CALIPER/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:      # quieter console
        pass

    # -- helpers -----------------------------------------------------------
    def _json(self, obj: Any, code: int = 200) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path: str) -> None:
        if not os.path.isfile(path):
            self.send_error(404)
            return
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        with open(path, "rb") as fh:
            body = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _query(self) -> Dict[str, str]:
        q = urllib.parse.urlparse(self.path).query
        return {k: v[0] for k, v in urllib.parse.parse_qs(q).items()}

    # -- routes ------------------------------------------------------------
    def do_GET(self) -> None:
        route = urllib.parse.urlparse(self.path).path
        q = self._query()

        if route in ("/", "/index.html"):
            return self._file(os.path.join(_STATIC, "index.html"))
        if route.startswith("/static/"):
            rel = posixpath.normpath(route[len("/static/"):]).lstrip("/\\")
            return self._file(os.path.join(_STATIC, rel))

        if route == "/api/report":
            return self._json({"report": STATE.report, "source": STATE.source_name})
        if route == "/api/rows":
            return self._json(STATE.rows_page(
                int(q.get("offset", 0)), min(200, int(q.get("limit", 50))),
                q.get("status", ""), q.get("q", "")))
        if route == "/api/row":
            return self._json(STATE.row_detail(int(q.get("i", 0))))
        if route == "/api/specs":
            return self._json({"specs": STATE.report.get("specs", [])})
        if route == "/api/queue":
            return self._json({"queue": STATE.queue[:400], "total": len(STATE.queue)})
        if route == "/api/families":
            return self._json(self._families())
        if route == "/api/graph":
            rel = q.get("relation", "")
            rows = [e for e in STATE.edges
                    if not rel or e.get("relation") == rel]
            return self._json({
                "summary": STATE.report.get("knowledge", {}),
                "edges": rows[:400], "total": len(rows)})
        if route == "/api/corrections":
            return self._json(STATE.report.get("corrections", {}))
        if route == "/api/progress":
            p = dict(STATE.progress)
            el = max(0.001, time.time() - (p.get("started") or time.time()))
            done, total = p.get("done", 0), p.get("total", 0) or 1
            p["elapsed"] = round(el, 1)
            p["rate"] = round(done / el, 1) if done else 0.0
            p["eta"] = round((total - done) / (done / el), 0) if done else None
            return self._json(p)
        if route == "/api/session":
            from ..llm.provider import PROVIDERS, load_dotenv
            load_dotenv()
            env_ready = sorted(p for p, c in PROVIDERS.items()
                               if os.environ.get(c["env"]))
            return self._json({
                "providers": sorted(PROVIDERS),
                "configured": bool(STATE.api_key) or bool(env_ready),
                "provider": STATE.provider,
                "model": STATE.model_name,
                "audit": STATE.use_audit,
                "from_env": env_ready,
            })
        if route == "/api/download":
            kind = q.get("kind", "delivery")
            return self._download(kind)
        self.send_error(404)

    def _families(self) -> Dict[str, Any]:
        rows = getattr(STATE, "_cached_rows", [])
        deliv = getattr(STATE, "_cached_delivery", [])
        fam: Dict[str, List[int]] = {}
        for i, g in enumerate(rows):
            fam.setdefault(g.get("family_id", "?"), []).append(i)
        out = []
        for fid, members in sorted(fam.items(), key=lambda x: -len(x[1])):
            if len(members) < 2:
                continue
            sample = deliv[members[0]] if members[0] < len(deliv) else {}
            out.append({
                "family_id": fid, "size": len(members),
                "item_type": sample.get("Product Name", ""),
                "brand": sample.get("BRAND_NAME", ""),
                "members": [
                    {"index": m,
                     "part_number": deliv[m].get("Mfg_Part_Num", "") if m < len(deliv) else "",
                     "desc": deliv[m].get("Part_Desc", "") if m < len(deliv) else ""}
                    for m in members[:25]],
            })
        singles = sum(1 for m in fam.values() if len(m) == 1)
        return {"families": out[:120], "total": len(fam), "singletons": singles}

    def _download(self, kind: str) -> None:
        rows = getattr(STATE, "_cached_delivery", [])
        if kind == "delivery":
            buf = io.StringIO()
            import csv as _csv
            w = _csv.DictWriter(buf, fieldnames=DELIVERY_COLUMNS, extrasaction="ignore")
            w.writeheader()
            for r in rows:
                w.writerow({k: r.get(k, "") for k in DELIVERY_COLUMNS})
            body = buf.getvalue().encode("utf-8-sig")
            fname = "caliper_delivery.csv"
        elif kind == "queue":
            import csv as _csv
            buf = io.StringIO()
            cols = list(STATE.queue[0].keys()) if STATE.queue else ["row"]
            w = _csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            for r in STATE.queue:
                w.writerow(r)
            body = buf.getvalue().encode("utf-8-sig")
            fname = "caliper_review_queue.csv"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition",
                         'attachment; filename="{}"'.format(fname))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        route = urllib.parse.urlparse(self.path).path
        if route == "/api/session":
            length = int(self.headers.get("Content-Length", 0))
            try:
                body = json.loads(self.rfile.read(length).decode("utf-8"))
            except Exception:
                return self._json({"error": "invalid payload"}, 400)
            mode = str(body.get("mode", "deterministic"))
            if mode == "deterministic":
                STATE.provider = STATE.api_key = STATE.model_name = ""
                STATE.use_audit = False
                return self._json({"ok": True, "mode": "deterministic"})

            provider = str(body.get("provider", "")).strip().lower()
            key = str(body.get("api_key", "")).strip()
            from ..llm.provider import PROVIDERS, get_provider
            if provider not in PROVIDERS:
                return self._json({"error": "unknown provider"}, 400)
            if not key:
                return self._json({"error": "no API key supplied"}, 400)
            from ..llm.provider import probe as probe_provider
            res = probe_provider(provider, key)
            if not res.get("ok"):
                # A used-up quota is not a dead end: offer the deterministic path.
                return self._json({
                    "error": res.get("error", "provider rejected the key"),
                    "quota": bool(res.get("quota")),
                    "daily": bool(res.get("daily")),
                    "resets_in_s": res.get("resets_in_s") or 0,
                    "fallback": "deterministic"}, 400)
            STATE.provider, STATE.api_key = provider, key
            STATE.use_audit = bool(body.get("audit"))
            STATE.model_name = res.get("model", "")
            # The key is deliberately absent from this response.
            return self._json({"ok": True, "mode": "ai", "provider": provider,
                               "model": STATE.model_name, "audit": STATE.use_audit,
                               "remaining_tokens": res.get("remaining_tokens"),
                               "remaining_requests": res.get("remaining_requests")})

        if route == "/api/correct":
            length = int(self.headers.get("Content-Length", 0))
            try:
                body = json.loads(self.rfile.read(length).decode("utf-8"))
            except Exception:
                return self._json({"error": "invalid payload"}, 400)
            from ..core.corrections import Correction, CorrectionStore
            store = CorrectionStore.load()
            store.add(Correction(
                scope=body.get("scope", "part"), target=body.get("target", ""),
                key=body.get("key", ""), value=body.get("value", ""),
                uom=body.get("uom", ""), note=body.get("note", ""),
                by=body.get("by", "dashboard")))
            store.save()
            return self._json({"ok": True, "stored": len(store.corrections),
                               "note": "Applies on the next run."})
        if route != "/api/enrich":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            return self._json({"error": "invalid payload"}, 400)

        text = payload.get("csv", "")
        name = payload.get("name", "upload.csv")
        limit = int(payload.get("limit", 0) or 0)
        if not text.strip():
            return self._json({"error": "empty file"}, 400)

        tmp = os.path.join(_HERE, "_upload.csv")
        with open(tmp, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        try:
            rows, header = read_table(tmp)
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass
        if not rows:
            return self._json({"error": "no rows parsed"}, 400)
        if limit:
            rows = rows[:limit]

        schema = detect_schema(header, rows)

        if STATE.progress.get("running"):
            return self._json({"error": "a run is already in progress"}, 409)

        STATE.progress = {"running": True, "done": 0, "total": len(rows),
                          "stage": "analysing the catalogue",
                          "started": time.time(), "finished": False,
                          "error": "", "notice": ""}

        def work() -> None:
            try:
                from ..llm.provider import Stats, get_auditor, get_provider
                Stats.reset_breaker()
                llm = auditor = None
                if STATE.api_key and STATE.provider:
                    llm = get_provider(STATE.provider, api_key=STATE.api_key)
                    if STATE.use_audit:
                        auditor = get_auditor(STATE.provider, api_key=STATE.api_key)

                def tick(done: int, total: int) -> None:
                    STATE.progress["done"] = done
                    STATE.progress["total"] = total
                    STATE.progress["stage"] = (
                        "enriching with {}".format(STATE.model_name)
                        if llm else "enriching")
                    if Stats.exhausted:
                        STATE.progress["notice"] = (
                            "{} quota is used up, so the remaining rows are being "
                            "enriched deterministically. Every one of the 252 "
                            "columns is still produced.".format(
                                (STATE.provider or "provider").title()))

                pipe = Pipeline(llm=llm, auditor=auditor)
                results, report = pipe.run(rows, schema, progress=tick)
                STATE._last_edges = getattr(pipe, "edges", [])
                STATE.set_results(results, report.to_dict(), name)
                STATE.progress["stage"] = "done"
                if Stats.exhausted:
                    STATE.progress["notice"] = (
                        "{} quota ran out during this run; the rest completed "
                        "deterministically.".format((STATE.provider or "provider").title()))
            except Exception as exc:
                STATE.progress["error"] = "{}: {}".format(type(exc).__name__, exc)
            finally:
                STATE.progress["running"] = False
                STATE.progress["finished"] = True

        threading.Thread(target=work, daemon=True).start()
        return self._json({"started": True, "total": len(rows)})


def serve(host: str = "127.0.0.1", port: int = 8765,
          data_dir: str = "data/out", open_browser: bool = True) -> None:
    STATE.load_from_disk(data_dir)
    httpd = ThreadingHTTPServer((host, port), Handler)
    url = "http://{}:{}/".format(host, port)
    print("CALIPER dashboard -> {}".format(url))
    print("  loaded {} rows from {}".format(
        len(getattr(STATE, "_cached_rows", [])), data_dir))
    print("  Ctrl-C to stop")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
        httpd.shutdown()
