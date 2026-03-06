#!/usr/bin/env python3
"""
Maritime Fleet Portal — HTTP server module.
Entry point: python -m portal [--port 8765] [--data ./data]
"""
import sys, os, json, math, csv, copy, io, html, threading, argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
import pandas as pd

from .shared import (
    STATE, DATA_DIR, TABLE_SOURCES, _clean, safe_json,
    get_table, init_tables, df_to_rows, rows_to_df,
    load_one_table, ALL_TEMPLATES, ALL_PORTAL_TEMPLATES,
    _resolve_data_dir, reload_table,
)
from .simulation import (
    run_simulation_task, run_branch_task,
    build_portal_params_defaults, _BRANCH_COLORS,
)

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass

    def _json(self, data, status=200):
        body = safe_json(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _html(self, html):
        body = html if isinstance(html, bytes) else html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n)) if n else {}

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path == "/":
            self._html(_load_static("index.html"))
        elif path.startswith("/static/"):
            fname = path[8:]  # strip /static/
            if not fname or "/" in fname or ".." in fname:
                self.send_response(404); self.end_headers(); return
            try:
                data = _load_static(fname)
                ext  = os.path.splitext(fname)[1]
                mime = _MIME.get(ext, "application/octet-stream")
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", len(data))
                self.end_headers()
                self.wfile.write(data)
            except FileNotFoundError:
                self.send_response(404); self.end_headers()
        elif path == "/api/tables":
            self._json(STATE["tables"])
        elif path == "/api/status":
            self._json(dict(running=STATE["sim_running"], progress=STATE["sim_progress"],
                            error=STATE["sim_error"], has_result=STATE["sim_result"] is not None,
                            active_branch=STATE["active_branch"],
                            branch_running=STATE["branch_running"]))
        elif path == "/api/result":
            # Return active branch result if set, otherwise main
            ab = STATE["active_branch"]
            if ab and ab in STATE["branches"] and STATE["branches"][ab].get("result"):
                self._json(STATE["branches"][ab]["result"])
            elif STATE["sim_result"]:
                self._json(STATE["sim_result"])
            else:
                self._json({"error": "no result"}, 404)
        elif path == "/api/branches":
            # Summary of all branches (no heavy result payloads)
            summary = []
            for bid, b in STATE["branches"].items():
                summary.append({
                    "id": bid, "name": b["name"], "status": b["status"],
                    "fork_from": b["fork_from"], "fork_step": b["fork_step"],
                    "color": b["color"], "progress": b.get("progress", 0),
                    "error": b.get("error"),
                    "created_at": b.get("created_at", 0),
                })
            self._json({"branches": summary, "active": STATE["active_branch"]})
        elif path == "/api/export_csv":
            self._export_csv()
        elif path.startswith("/api/download_table/"):
            tname = path.split("/api/download_table/", 1)[1]
            self._download_table(tname)
        elif path == "/api/data_config":
            all_templates = {**ALL_TEMPLATES, **ALL_PORTAL_TEMPLATES}
            self._json({
                "data_dir": DATA_DIR or "",
                "tables": [
                    {
                        "name":    name,
                        "source":  TABLE_SOURCES.get(name, "template"),
                        "rows":    len(STATE["tables"].get(name, [])),
                        "has_template": name in all_templates,
                    }
                    for name in sorted(STATE["tables"].keys())
                ],
            })
        else:
            self.send_response(404); self.end_headers()

    def do_POST(self):
        path = urlparse(self.path).path.rstrip("/")
        if path == "/api/run":
            body = self._body()
            if STATE["sim_running"]:
                self._json({"error": "already running"}, 409); return
            cfg  = build_portal_params_defaults()
            cfg.update(body.get("config", {}))
            snap = copy.deepcopy(STATE["tables"])
            threading.Thread(target=run_simulation_task, args=(cfg, snap), daemon=True).start()
            self._json({"status": "started"})
        elif path == "/api/table":
            body = self._body()
            name, rows = body.get("name"), body.get("rows")
            if name and rows is not None:
                STATE["tables"][name] = _clean(rows)
                self._json({"status": "ok", "rows": len(rows)})
            else:
                self._json({"error": "bad request"}, 400)
        elif path == "/api/set_data_dir":
            body = self._body()
            new_dir = body.get("data_dir", "").strip()
            resolved = _resolve_data_dir(new_dir or None) if new_dir else None
            if new_dir and not resolved:
                self._json({"error": f"Directory not found: {new_dir}"}, 400); return
            init_tables(data_dir=resolved)
            self._json({"status": "ok", "data_dir": DATA_DIR or "",
                        "loaded": len(STATE["tables"])})
        elif path == "/api/upload_csv":
            self._upload_csv()
        elif path == "/api/reset_table":
            body = self._body()
            tname = body.get("name", "")
            src_str = reload_table(tname)
            self._json({"status": "ok", "source": src_str, "rows": len(STATE["tables"].get(tname, []))})
        elif path == "/api/save_table_csv":
            body = self._body()
            tname = body.get("name", "")
            if not tname or tname not in STATE["tables"]:
                self._json({"error": "unknown table"}, 400); return
            save_dir = DATA_DIR or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
            os.makedirs(save_dir, exist_ok=True)
            csv_path = os.path.join(save_dir, f"{tname}.csv")
            df = rows_to_df(STATE["tables"][tname])
            df.to_csv(csv_path, index=False)
            TABLE_SOURCES[tname] = f"csv:{csv_path}"
            self._json({"status": "ok", "path": csv_path})
        # ── Branch endpoints ──────────────────────────────────────────────────
        elif path == "/api/branch/create":
            body = self._body()
            if not STATE["sim_result"]:
                self._json({"error": "Run main simulation first"}, 400); return
            if STATE["branch_running"]:
                self._json({"error": "A branch is already running"}, 409); return
            fork_step      = int(body.get("fork_step", 0))
            fork_branch_id = str(body.get("fork_branch_id", "main"))
            override_cfg   = body.get("config", {})
            branch_name    = str(body.get("name", f"Branch @step{fork_step}"))
            import time
            bid = f"b{int(time.time()*1000) % 1_000_000}"
            color_idx = len(STATE["branches"]) % len(_BRANCH_COLORS)
            STATE["branches"][bid] = {
                "id": bid, "name": branch_name, "status": "pending",
                "fork_from": fork_branch_id, "fork_step": fork_step,
                "cfg": override_cfg, "color": _BRANCH_COLORS[color_idx],
                "created_at": int(time.time()), "progress": 0,
                "result": None, "error": None,
            }
            snap = copy.deepcopy(STATE["tables"])
            cfg  = build_portal_params_defaults()
            cfg.update(override_cfg)
            threading.Thread(
                target=run_branch_task,
                args=(bid, fork_step, fork_branch_id, cfg, snap),
                daemon=True).start()
            self._json({"status": "started", "branch_id": bid})
        elif path == "/api/branch/activate":
            body = self._body()
            bid  = body.get("branch_id")
            if bid == "main" or bid is None:
                STATE["active_branch"] = None
                self._json({"status": "ok", "active": "main"})
            elif bid in STATE["branches"]:
                STATE["active_branch"] = bid
                self._json({"status": "ok", "active": bid})
            else:
                self._json({"error": "unknown branch"}, 404)
        elif path == "/api/branch/delete":
            body = self._body()
            bid  = body.get("branch_id")
            if bid in STATE["branches"]:
                del STATE["branches"][bid]
                if STATE["active_branch"] == bid:
                    STATE["active_branch"] = None
                self._json({"status": "ok"})
            else:
                self._json({"error": "unknown branch"}, 404)
        else:
            self.send_response(404); self.end_headers()

    def _upload_csv(self):
        """Multipart CSV upload: ?table=name + file body."""
        from urllib.parse import parse_qs, urlparse
        qs = parse_qs(urlparse(self.path).query)
        tname = (qs.get("table") or [""])[0]
        if not tname:
            self._json({"error": "?table= required"}, 400); return
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        try:
            df = pd.read_csv(io.StringIO(raw))
        except Exception as e:
            self._json({"error": f"CSV parse error: {e}"}, 400); return
        rows = df_to_rows(df)
        STATE["tables"][tname] = rows
        TABLE_SOURCES[tname] = "upload"
        # Optionally persist to data dir
        if DATA_DIR:
            os.makedirs(DATA_DIR, exist_ok=True)
            df.to_csv(os.path.join(DATA_DIR, f"{tname}.csv"), index=False)
            TABLE_SOURCES[tname] = f"csv:{os.path.join(DATA_DIR, tname + '.csv')}"
        self._json({"status": "ok", "rows": len(rows), "columns": list(df.columns)})

    def _download_table(self, tname: str):
        rows = STATE["tables"].get(tname)
        if rows is None:
            self.send_response(404); self.end_headers(); return
        df = rows_to_df(rows)
        body = df.to_csv(index=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/csv")
        self.send_header("Content-Disposition", f"attachment; filename={tname}.csv")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def _export_csv(self):
        if not STATE["sim_result"]:
            self._json({"error": "no result"}, 404); return
        steps = STATE["sim_result"]["steps"]
        buf = io.StringIO()
        if steps:
            w = csv.DictWriter(buf, fieldnames=list(steps[0].keys()))
            w.writeheader()
            for s in steps:
                w.writerow({k: (safe_json(v) if isinstance(v, dict) else v) for k, v in s.items()})
        body = buf.getvalue().encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/csv")
        self.send_header("Content-Disposition", "attachment; filename=maritime_sim.csv")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)


# ── Portal HTML ───────────────────────────────────────────────────────────────

# ── Static file serving ───────────────────────────────────────────────────────
_STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

_MIME = {
    ".html": "text/html; charset=utf-8",
    ".css":  "text/css",
    ".js":   "application/javascript",
}

def _load_static(name: str) -> bytes:
    path = os.path.join(_STATIC_DIR, name)
    with open(path, "rb") as f:
        return f.read()



# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    global DATA_DIR
    p = argparse.ArgumentParser(description="Maritime Fleet Simulation Portal v3")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--host", default="localhost")
    p.add_argument("--data", default=None,
                   help="CSV override directory. Files named {table}.csv override built-in templates.")
    args = p.parse_args()
    resolved = _resolve_data_dir(args.data)

    print(f"\n{'═'*56}\n  ⬡  Maritime Fleet Simulation Portal  v3\n{'═'*56}")
    print(f"  Loading tables...")
    init_tables(data_dir=resolved)
    print(f"  http://{args.host}:{args.port}\n{'═'*56}\n")
    HTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
