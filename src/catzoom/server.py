"""Loopback-only classifier workbench. The Jev key never leaves Python."""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import uuid
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .cli import _read_records, _upsert_record
from .jev import QUESTIONS, evaluate_questions, payload
from .storia import LOCATIONS, Collector

PAGE_SIZE = 9
MAX_POOL = 100
MAX_CLASSIFIERS = 12
STATIC = Path(__file__).parent / "static"


def defaults():
    definitions = (
        ("pets", "Cat friendly", 3, [("allowed", 1), ("conditional", .4), ("forbidden", -2), ("unspecified", 0)]),
        ("workspace", "Video-call workspace", 2, [("dedicated", 1), ("possible", .5), ("unspecified", 0), ("unsuitable", -1)]),
        ("noise", "Quiet clues", 1, [("quiet_claim", 1), ("noise_warning", -1), ("mixed", -.5), ("unspecified", 0)]),
        ("balcony", "Outdoor space", 1, [("private", 1), ("shared", .25), ("none", 0), ("unspecified", 0)]),
    )
    result = []
    for ident, name, weight, values in definitions:
        q = QUESTIONS[ident]
        result.append({"id": ident, "name": name, "kind": "choice", "question": q["instructions"], "weight": weight,
                       "options": [{"key": key, "description": q["criteria"][key], "value": val} for key, val in values]})
    return result


def validate_configs(items, existing=()):
    if not isinstance(items, list) or len(items) > MAX_CLASSIFIERS:
        raise ValueError(f"Choose at most {MAX_CLASSIFIERS} classifiers")
    known = {x.get("id") for x in existing if isinstance(x, dict) and isinstance(x.get("id"), str)} | {x["id"] for x in defaults()}
    ids = set()
    result = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Each classifier must be an object")
        ident = item.get("id")
        if not isinstance(ident, str) or ident not in known:
            ident = "custom-" + uuid.uuid4().hex[:12]
        if ident in ids:
            raise ValueError("Duplicate classifier ID")
        ids.add(ident)
        name, question, kind = item.get("name"), item.get("question"), item.get("kind")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 48:
            raise ValueError("Classifier name must be 1–48 characters")
        if not isinstance(question, str) or not 12 <= len(question.strip()) <= 300:
            raise ValueError("Question must be 12–300 characters")
        if kind not in ("noul", "choice", "score"):
            raise ValueError("Choose a yes/no, multiple-choice, or rubric score classifier")
        weight = item.get("weight")
        if isinstance(weight, bool) or not isinstance(weight, (int, float)) or not 0 <= weight <= 5:
            raise ValueError("Weight must be between 0 and 5")
        config = {"id": ident, "name": name.strip(), "kind": kind, "question": question.strip(), "weight": round(weight, 2)}
        if kind == "noul":
            if item.get("preferred") not in ("yes", "no"):
                raise ValueError("Select whether yes or no is desirable")
            config["preferred"] = item["preferred"]
        elif kind == "score":
            levels = item.get("levels")
            if not isinstance(levels, list) or not 2 <= len(levels) <= 5 or any(not isinstance(x, str) or not 1 <= len(x.strip()) <= 160 for x in levels):
                raise ValueError("Rubric score needs 2–5 levels, each 1–160 characters")
            config["levels"] = [x.strip() for x in levels]
        else:
            options = item.get("options")
            if not isinstance(options, list) or not 2 <= len(options) <= 5:
                raise ValueError("Choice needs 2–5 options")
            parsed = []
            keys = set()
            for option in options:
                if not isinstance(option, dict):
                    raise ValueError("Invalid option")
                key, desc, value = option.get("key"), option.get("description"), option.get("value")
                if not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,23}", key) or key in keys:
                    raise ValueError("Option keys must be distinct lowercase identifiers (max 24 chars)")
                if not isinstance(desc, str) or not 1 <= len(desc.strip()) <= 160:
                    raise ValueError("Option descriptions must be 1–160 characters")
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not -2 <= value <= 1:
                    raise ValueError("Option score must be between -2 and 1")
                keys.add(key)
                parsed.append({"key": key, "description": desc.strip(), "value": round(value, 2)})
            config["options"] = parsed
        result.append(config)
    return result


def question_for(config):
    if config["kind"] == "noul":
        return {"type": "noul", "instructions": config["question"]}
    if config["kind"] == "score":
        return {"type": "score", "instructions": config["question"], "criteria": config["levels"]}
    return {"type": "choice", "instructions": config["question"],
            "criteria": {x["key"]: x["description"] for x in config["options"]}}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:20]


def score(record, configs, results):
    capacity = sum(c["weight"] * max(0, max((o["value"] for o in c["options"]), default=0))
                   if c["kind"] == "choice" else c["weight"] for c in configs)
    if capacity <= 0:
        return None
    points = 0
    for c in configs:
        answer = results.get(c["id"], {})
        val = answer.get("value")
        if val == "review":
            continue
        if c["kind"] == "noul":
            points += c["weight"] if val == c["preferred"] else 0
        elif c["kind"] == "score":
            if isinstance(val, (int, float)):
                points += c["weight"] * val / (len(c["levels"]) - 1)
        else:
            points += c["weight"] * next((o["value"] for o in c["options"] if o["key"] == val), 0)
    return round(max(0, min(100, points / capacity * 100)))


class Workbench:
    def __init__(self, output, api_key=None, evaluator=evaluate_questions, collector_factory=Collector):
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=True)
        self.api_key = api_key
        self.evaluator = evaluator
        self.collector_factory = collector_factory
        self.lock = threading.RLock()
        self.records_path = self.output / "listings.jsonl"
        self.records = {}
        self.records_mtime = None
        self._reload_records(force=True)
        self.inflight = set()
        self.crawl = {"running": False, "processed": 0, "error": None, "area": None}
        self.stop_event = threading.Event()
        self.config_path = self.output / "classifiers.json"
        self.cache_path = self.output / "classifications.json"
        if self.config_path.exists():
            saved = json.loads(self.config_path.read_text())
            self.configs = validate_configs(saved, saved)
        else:
            self.configs = defaults()
        self.cache = json.loads(self.cache_path.read_text()) if self.cache_path.exists() else {}

    @staticmethod
    def record_id(record):
        listing = record["listing"]
        return f"{listing['transaction']}:{listing['id']}"

    def _write(self, path, data):
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    def _reload_records(self, force=False):
        stamp = self.records_path.stat().st_mtime_ns if self.records_path.exists() else None
        if not force and stamp == self.records_mtime:
            return
        records = list(_read_records(self.records_path).values())
        records.sort(key=lambda r: r["listing"].get("collected_at") or "", reverse=True)
        self.records = {self.record_id(r): r for r in records[:MAX_POOL]}
        self.records_mtime = stamp

    def result_for(self, record_id, config):
        record = self.records[record_id]
        signature = digest(question_for(config))
        listing_hash = digest(payload(record["listing"])["state"])
        cached = self.cache.get(record_id, {}).get(config["id"], {})
        if cached.get("signature") == signature and cached.get("listing_hash") == listing_hash:
            return cached.get("result")
        # Previous CLI classifications remain useful until a deliberate recheck.
        baseline = next((c for c in defaults() if c["id"] == config["id"]), None)
        legacy = ((record.get("jev") or {}).get("signals") or {}).get(config["id"])
        if baseline and digest(question_for(baseline)) == signature and legacy:
            return legacy
        return None

    def snapshot(self):
        with self.lock:
            self._reload_records()
            listings = []
            for ident, record in self.records.items():
                results = {c["id"]: self.result_for(ident, c) for c in self.configs}
                results = {k: v for k, v in results.items() if v is not None}
                listings.append({"id": ident, "listing": record["listing"], "results": results,
                                 "score": score(record, self.configs, results)})
            return {"listings": listings, "classifiers": deepcopy(self.configs), "page_size": PAGE_SIZE,
                    "max_pool": MAX_POOL, "has_key": bool(self.api_key), "presets": defaults(), "crawl": dict(self.crawl),
                    "classifying": sorted({ident for ident, _ in self.inflight})}

    def configure(self, items):
        with self.lock:
            self.configs = validate_configs(items, self.configs)
            self._write(self.config_path, self.configs)
            return self.snapshot()

    def classify(self, ids, model="jev-latest"):
        if not self.api_key:
            raise RuntimeError("JEV_API_KEY is not set in the server process")
        if not isinstance(ids, list) or not 1 <= len(ids) <= PAGE_SIZE or len(ids) != len(set(ids)):
            raise ValueError(f"Select 1–{PAGE_SIZE} distinct listings from the current pool")
        if not self.configs:
            raise ValueError("Add a classifier first")
        updated = 0
        with self.lock:
            self._reload_records()
            if any(ident not in self.records for ident in ids):
                raise ValueError("Listing is outside the current 100-listing pool")
        for ident in ids:
            with self.lock:
                self._reload_records()
                if ident not in self.records:
                    continue  # A newer listing moved this one outside the bounded pool.
                record = self.records[ident]
                pending = {c["id"]: question_for(c) for c in self.configs
                           if self.result_for(ident, c) is None and (ident, c["id"]) not in self.inflight}
                if not pending:
                    continue
                self.inflight.update((ident, key) for key in pending)
                listing = deepcopy(record["listing"])
                listing_hash = digest(payload(listing)["state"])
            try:
                response = self.evaluator(listing, self.api_key, pending, model)
            except Exception:
                with self.lock:
                    self.inflight.difference_update((ident, key) for key in pending)
                raise
            with self.lock:
                try:
                    cache = self.cache.setdefault(ident, {})
                    for key, answer in response["signals"].items():
                        cache[key] = {"signature": digest(pending[key]), "listing_hash": listing_hash, "result": answer}
                    self._write(self.cache_path, self.cache)
                    updated += 1
                finally:
                    self.inflight.difference_update((ident, key) for key in pending)
        return {"classified": updated, "state": self.snapshot()}

    def start_crawl(self, params):
        transaction, location = params.get("transaction"), params.get("location")
        pages, limit = params.get("pages"), params.get("limit")
        if transaction not in ("rent", "sale") or location not in LOCATIONS:
            raise ValueError("Choose a supported transaction and area")
        if isinstance(pages, bool) or not isinstance(pages, int) or not 1 <= pages <= 3:
            raise ValueError("Pages must be 1–3")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 30:
            raise ValueError("Limit must be 1–30")
        with self.lock:
            if self.crawl["running"]:
                raise ValueError("A crawl is already running")
            self.stop_event.clear()
            self.crawl = {"running": True, "processed": 0, "error": None, "area": location}
            thread = threading.Thread(target=self._crawl_worker, args=(transaction, location, pages, limit), daemon=True)
            thread.start()
            return self.snapshot()

    def stop_crawl(self):
        self.stop_event.set()
        return self.snapshot()

    def _crawl_worker(self, transaction, location, pages, limit):
        try:
            records = _read_records(self.records_path)
            skip_ids = {key[1] for key, record in records.items() if key[0] == transaction and record["listing"].get("detail_found")}
            collector = self.collector_factory(3.0)
            for listing in collector.collect(transaction, pages, limit, location, skip_ids):
                if self.stop_event.is_set():
                    break
                _upsert_record(self.records_path, {"listing": listing, "jev": None})
                with self.lock:
                    self.crawl["processed"] += 1
                    self._reload_records(force=True)
        except (ValueError, RuntimeError, OSError, json.JSONDecodeError) as exc:
            with self.lock:
                self.crawl["error"] = str(exc)
        finally:
            with self.lock:
                self.crawl["running"] = False


class AppHandler(BaseHTTPRequestHandler):
    workbench = None

    def _headers(self, code, content_type, length):
        self.send_response(code)
        for key, val in {"Content-Type": content_type, "Content-Length": str(length), "Cache-Control": "no-store",
                         "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
                         "Content-Security-Policy": "default-src 'self'; img-src https:; style-src 'self'; script-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'self'"}.items():
            self.send_header(key, val)
        self.end_headers()

    def _send(self, code, data):
        raw = json.dumps(data, ensure_ascii=False).encode()
        self._headers(code, "application/json; charset=utf-8", len(raw))
        self.wfile.write(raw)

    def do_GET(self):
        if self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}":
            self._send(403, {"error": "Local host required"})
            return
        path = urlsplit(self.path).path
        if path == "/api/state":
            self._send(200, self.workbench.snapshot())
            return
        file = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"),
                "/style.css": ("style.css", "text/css")}.get(path)
        if file is None:
            self._send(404, {"error": "Not found"})
            return
        raw = (STATIC / file[0]).read_bytes()
        self._headers(200, file[1] + "; charset=utf-8", len(raw))
        self.wfile.write(raw)

    def do_POST(self):
        expected = f"http://127.0.0.1:{self.server.server_port}"
        if self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}" or self.headers.get("Origin") not in (None, expected) or self.headers.get("X-Catzoom-Request") != "1" or self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            self._send(403, {"error": "Local same-origin JSON request required"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 32768:
                raise ValueError("Request body must be 1–32768 bytes")
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError("Request must be a JSON object")
            path = urlsplit(self.path).path
            if path == "/api/classifiers":
                result = self.workbench.configure(data.get("classifiers"))
            elif path == "/api/classify":
                model = data.get("model", "jev-latest")
                if not isinstance(model, str) or not re.fullmatch(r"jev-[a-zA-Z0-9.-]{1,40}", model):
                    raise ValueError("Invalid Jev model name")
                result = self.workbench.classify(data.get("ids"), model)
            elif path == "/api/crawl":
                result = self.workbench.start_crawl(data)
            elif path == "/api/crawl/stop":
                result = self.workbench.stop_crawl()
            else:
                self._send(404, {"error": "Not found"})
                return
            self._send(200, result)
        except (ValueError, RuntimeError, json.JSONDecodeError) as exc:
            self._send(400, {"error": str(exc)})

    def log_message(self, format, *args):
        print("catzoom:", format % args)


def make_server(output, port=8765, api_key=None, evaluator=evaluate_questions):
    workbench = Workbench(output, api_key, evaluator)
    handler = type("BoundAppHandler", (AppHandler,), {"workbench": workbench})
    return ThreadingHTTPServer(("127.0.0.1", port), handler)


def serve_main(argv):
    import argparse
    parser = argparse.ArgumentParser(description="Run the local classifier workbench")
    parser.add_argument("--output", type=Path, default=Path("out"))
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    if not 1024 <= args.port <= 65535:
        parser.error("Port must be 1024–65535")
    server = make_server(args.output, args.port, os.getenv("JEV_API_KEY"))
    print(f"Cat & Zoom Radar: http://127.0.0.1:{args.port} ({len(server.RequestHandlerClass.workbench.records)} listings)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
