"""LEONAN MEDIA MANAGER: a local, copy-only media registry."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
import subprocess
import tempfile
import warnings
import zipfile

from flask import Flask, abort, jsonify, render_template, request, send_file, send_from_directory
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from PIL import Image, ImageOps, UnidentifiedImageError
from werkzeug.exceptions import HTTPException

STATUSES = {"investigating", "approved", "discarded"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}
VIDEO_INPUT_OPTIONS = ["-protocol_whitelist", "file,pipe", "-format_whitelist",
                       "mov,mp4,m4a,3gp,3g2,mj2,matroska,webm,avi"]
IMAGE_FORMATS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}
MAX_MEDIA = 1024 * 1024 * 1024
MAX_RESTORE = 4 * MAX_MEDIA
SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS episodes (
 id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, title TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS takes (
 id INTEGER PRIMARY KEY, episode_id INTEGER NOT NULL REFERENCES episodes(id),
 number INTEGER NOT NULL, title TEXT NOT NULL DEFAULT '', prompt TEXT NOT NULL DEFAULT '',
 notes TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'investigating'
 CHECK(status IN ('investigating','approved','discarded')),
 UNIQUE(episode_id, number)
);
CREATE TABLE IF NOT EXISTS assets (
 id INTEGER PRIMARY KEY, sha TEXT NOT NULL UNIQUE, kind TEXT NOT NULL,
 original_name TEXT NOT NULL, extension TEXT NOT NULL, dhash TEXT,
 width INTEGER NOT NULL, height INTEGER NOT NULL, duration REAL,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS bindings (
 id INTEGER PRIMARY KEY, take_id INTEGER NOT NULL REFERENCES takes(id),
 asset_id INTEGER NOT NULL REFERENCES assets(id), kind TEXT NOT NULL,
 version TEXT NOT NULL DEFAULT '', label TEXT NOT NULL DEFAULT '', original_name TEXT NOT NULL DEFAULT '',
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1))
);
CREATE UNIQUE INDEX IF NOT EXISTS active_binding ON bindings(take_id, kind) WHERE active=1;
"""


class InputError(Exception):
    pass


def text_field(data, key, maximum=10000, default=""):
    value = data.get(key, default)
    if not isinstance(value, str) or len(value) > maximum:
        raise InputError(f"Campo inválido: {key} (máximo de {maximum} caracteres).")
    return value.strip()


def positive_number(value):
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 999:
        raise InputError("O número do take deve estar entre 1 e 999.")
    return value


def json_object():
    data = request.get_json()
    if not isinstance(data, dict):
        raise InputError("Envie um objeto JSON válido.")
    return data


def image_hash(image):
    # 64-bit difference hash. This is a heuristic, never an approval decision.
    pixels = list(image.convert("L").resize((9, 8)).getdata())
    bits = [pixels[y * 9 + x] > pixels[y * 9 + x + 1] for y in range(8) for x in range(8)]
    return f"{sum(int(bit) << i for i, bit in enumerate(bits)):016x}"


def command(args, timeout=60):
    try:
        result = subprocess.run(args, capture_output=True, timeout=timeout, check=True)
        return result.stdout
    except FileNotFoundError as exc:
        raise InputError("Instale FFmpeg (incluindo ffprobe) para importar vídeos e abrir o piloto.") from exc
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise InputError("O FFmpeg não conseguiu ler este vídeo. Confira o arquivo e tente MP4/H.264.") from exc


def prepare_media(source: Path, name: str, work: Path):
    """Read the staged copy. Never open an operator's original for writing."""
    with source.open("rb") as original:
        sha = hashlib.file_digest(original, "sha256").hexdigest()
    info = {"sha": sha, "original_name": Path(name.replace("\\", "/")).name[:255], "dhash": None,
            "duration": None}
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(source) as image:
                if image.format not in IMAGE_FORMATS:
                    raise InputError("Use imagem PNG, JPEG ou WebP.")
                info.update(kind="image", extension=IMAGE_FORMATS[image.format])
                image = ImageOps.exif_transpose(image)
                image.load()
                info.update(width=image.width, height=image.height, dhash=image_hash(image))
                image.thumbnail((640, 640))
                if image.mode in ("RGBA", "LA") or "transparency" in image.info:
                    rgba = image.convert("RGBA")
                    background = Image.new("RGB", image.size, "#e6e6e6")
                    background.paste(rgba, mask=rgba.getchannel("A"))
                    image = background
                image.convert("RGB").save(work / "thumb.jpg", quality=86)
    except UnidentifiedImageError:
        extension = Path(name).suffix.lower()
        if extension not in VIDEO_EXTENSIONS:
            raise InputError("Arquivo não reconhecido. Use PNG, JPEG, WebP ou um vídeo MP4, MOV, WebM, MKV ou AVI.")
        raw = command(["ffprobe", "-v", "error", *VIDEO_INPUT_OPTIONS,
                       "-show_streams", "-show_format", "-of", "json", str(source)])
        probe = json.loads(raw)
        streams = [s for s in probe.get("streams", []) if s.get("codec_type") == "video"
                   and not s.get("disposition", {}).get("attached_pic")]
        if not streams:
            raise InputError("O arquivo não contém uma faixa de vídeo.")
        stream = streams[0]
        info.update(kind="video", extension=extension, width=stream["width"], height=stream["height"],
                    duration=float(probe.get("format", {}).get("duration", 0)))
        command(["ffmpeg", "-nostdin", "-v", "error", *VIDEO_INPUT_OPTIONS, "-i", str(source), "-map", f"0:{stream['index']}",
                 "-frames:v", "1", "-vf", "scale=640:640:force_original_aspect_ratio=decrease",
                 "-threads", "1", "-y", str(work / "thumb.jpg")])
        if not (work / "thumb.jpg").is_file():
            raise InputError("Não foi possível gerar a miniatura do vídeo.")
    except (Image.DecompressionBombError, Image.DecompressionBombWarning, OSError, ValueError) as exc:
        raise InputError("A imagem está corrompida ou excede o limite seguro de resolução.") from exc
    return info


def create_app(data_dir=None):
    app = Flask(__name__)
    app.config.update(MAX_CONTENT_LENGTH=MAX_RESTORE + 10 * 1024 * 1024, APP_TOKEN=secrets.token_urlsafe(32))
    root = Path(data_dir or os.environ.get("LEONAN_DATA_DIR", Path(__file__).parent / "data")).resolve()
    root.mkdir(parents=True, exist_ok=True)
    for folder in ("media", "thumbs", "tmp"):
        (root / folder).mkdir(exist_ok=True)
    app.config["DATA_DIR"] = root
    deletion_signer = URLSafeTimedSerializer(app.config["APP_TOKEN"], salt="leonan-delete-v02")
    deletion_generations = {}

    @contextmanager
    def db():
        connection = sqlite3.connect(root / "registry.sqlite3", timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    with db() as connection:
        connection.executescript(SCHEMA)

    def require_row(connection, table, row_id):
        if type(row_id) is not int or row_id < 1:
            raise InputError("Identificador de registro inválido.")
        row = connection.execute(f"SELECT * FROM {table} WHERE id=?", (row_id,)).fetchone()
        if row is None:
            raise InputError("Registro não encontrado. Atualize a página.")
        return row

    def project_records(connection):
        # A single read transaction prevents mixed snapshots during export/state requests.
        connection.execute("BEGIN")
        result = {table: [dict(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY id")]
                  for table in ("episodes", "takes", "bindings")}
        # Keep orphan metadata and bytes on disk; expose only active OR historical references.
        result["assets"] = [dict(row) for row in connection.execute(
            "SELECT a.* FROM assets a WHERE EXISTS (SELECT 1 FROM bindings b WHERE b.asset_id=a.id) ORDER BY a.id")]
        return result

    def deletion_snapshot(connection, kind, row_id):
        table = "episodes" if kind == "episode" else "takes"
        target = connection.execute(f"SELECT * FROM {table} WHERE id=?", (row_id,)).fetchone()
        if target is None:
            abort(404, description="Registro não encontrado ou já excluído. Atualize o acervo.")
        episode = target if kind == "episode" else require_row(connection, "episodes", target["episode_id"])
        takes = [dict(row) for row in connection.execute(
            "SELECT * FROM takes WHERE episode_id=? ORDER BY id" if kind == "episode" else
            "SELECT * FROM takes WHERE id=? ORDER BY id", (row_id,))]
        bindings = [dict(row) for row in connection.execute(
            "SELECT b.* FROM bindings b JOIN takes t ON t.id=b.take_id WHERE t.episode_id=? ORDER BY b.id"
            if kind == "episode" else "SELECT * FROM bindings WHERE take_id=? ORDER BY id", (row_id,))]
        snapshot = {"episode": dict(episode), "takes": takes, "bindings": bindings}
        digest = hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        summary = {"episode": dict(episode), "take": dict(target) if kind == "take" else None,
                   "take_count": len(takes), "binding_count": len(bindings),
                   "image_count": len({b["asset_id"] for b in bindings if b["kind"] == "image"}),
                   "video_count": len({b["asset_id"] for b in bindings if b["kind"] == "video"})}
        return summary, digest

    def deletion_preview(kind, row_id):
        with db() as connection:
            connection.execute("BEGIN")
            summary, digest = deletion_snapshot(connection, kind, row_id)
        summary["confirmation_token"] = deletion_signer.dumps(
            {"kind": kind, "id": row_id, "digest": digest,
             "generation": deletion_generations.get((kind, row_id), 0)})
        return jsonify(summary)

    def delete_confirmed(kind, row_id):
        data = json_object()
        token = text_field(data, "confirmation_token", 2000)
        try:
            review = deletion_signer.loads(token, max_age=600)
        except (BadSignature, SignatureExpired):
            raise InputError("A confirmação expirou ou é inválida. Reabra a janela de exclusão.")
        if review.get("kind") != kind or review.get("id") != row_id:
            raise InputError("A confirmação não corresponde ao registro selecionado.")
        if data.get("backup_confirmed") is not True:
            raise InputError("Confirme que você possui um backup válido antes de excluir.")
        # No file operations occur here. The record deletion either commits fully or rolls back.
        with db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if review["generation"] != deletion_generations.get((kind, row_id), 0):
                abort(409, description="O registro desta confirmação já foi excluído. Atualize o acervo.")
            summary, digest = deletion_snapshot(connection, kind, row_id)
            if review["digest"] != digest:
                abort(409, description="O registro mudou desde a conferência. Reabra a confirmação antes de excluir.")
            if text_field(data, "confirm_code", 1000) != summary["episode"]["code"]:
                raise InputError("O código informado não corresponde ao episódio selecionado.")
            if kind == "take" and (type(data.get("confirm_number")) is not int or
                                    data["confirm_number"] != summary["take"]["number"]):
                raise InputError("O número confirmado não corresponde ao take selecionado.")
            if kind == "episode":
                affected_takes = [row[0] for row in connection.execute("SELECT id FROM takes WHERE episode_id=?", (row_id,))]
                connection.execute("DELETE FROM bindings WHERE take_id IN (SELECT id FROM takes WHERE episode_id=?)", (row_id,))
                connection.execute("DELETE FROM takes WHERE episode_id=?", (row_id,))
                connection.execute("DELETE FROM episodes WHERE id=?", (row_id,))
            else:
                affected_takes = [row_id]
                connection.execute("DELETE FROM bindings WHERE take_id=?", (row_id,))
                connection.execute("DELETE FROM takes WHERE id=?", (row_id,))
        # Invalidate every outstanding preview for these records, including reused SQLite IDs.
        # On restart the signing key changes, invalidating all earlier confirmations.
        for take_id in affected_takes:
            key = ("take", take_id)
            deletion_generations[key] = deletion_generations.get(key, 0) + 1
        if kind == "episode":
            key = (kind, row_id)
            deletion_generations[key] = deletion_generations.get(key, 0) + 1
        return jsonify(ok=True, deleted=kind, id=row_id)

    def store_media(connection, source, name, work, expected_kind=None):
        info = prepare_media(source, name, work)
        if expected_kind and info["kind"] != expected_kind:
            raise InputError("O tipo do arquivo não corresponde ao campo escolhido.")
        existing = connection.execute("SELECT id,kind FROM assets WHERE sha=?", (info["sha"],)).fetchone()
        if existing:
            return existing["id"], existing["kind"]
        # Content-addressed copies. Existing media files are never overwritten.
        target = root / "media" / (info["sha"] + info["extension"])
        if not target.exists():
            with target.open("xb") as output, source.open("rb") as original:
                shutil.copyfileobj(original, output)
        thumbnail = root / "thumbs" / (info["sha"] + ".jpg")
        if not thumbnail.exists():
            with thumbnail.open("xb") as output, (work / "thumb.jpg").open("rb") as original:
                shutil.copyfileobj(original, output)
        columns = list(info)
        cursor = connection.execute(f"INSERT INTO assets ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                                    tuple(info.values()))
        return cursor.lastrowid, info["kind"]

    def bind(connection, take_id, asset_id, kind, version="", label="", active=True, original_name=None):
        if active:
            connection.execute("UPDATE bindings SET active=0 WHERE take_id=? AND kind=?", (take_id, kind))
            connection.execute("UPDATE takes SET status='investigating' WHERE id=?", (take_id,))
        if original_name is None:
            original_name = require_row(connection, "assets", asset_id)["original_name"]
        return connection.execute("INSERT INTO bindings(take_id,asset_id,kind,version,label,active,original_name) VALUES(?,?,?,?,?,?,?)",
                                  (take_id, asset_id, kind, version, label, int(active), original_name)).lastrowid

    @app.before_request
    def local_only():
        if request.path.endswith("/media") and request.method == "POST":
            request.max_content_length = MAX_MEDIA + 1024 * 1024
        if request.host.split(":")[0] not in {"127.0.0.1", "localhost"}:
            return jsonify(error="Este aplicativo aceita somente acesso local."), 403
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            if not secrets.compare_digest(request.headers.get("X-App-Token", ""), app.config["APP_TOKEN"]):
                return jsonify(error="Sessão expirada. Atualize a página antes de continuar."), 403

    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' blob:; media-src 'self' blob:; "
            "style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; form-action 'self'")
        if request.path.startswith("/api") or request.path == "/":
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(InputError)
    def bad_input(error):
        return jsonify(error=str(error)), 400

    @app.errorhandler(sqlite3.IntegrityError)
    def conflict(error):
        if request.method == "DELETE":
            return database_error(error)
        return jsonify(error="Já existe um episódio com esse código ou um take com esse número."), 409

    @app.errorhandler(sqlite3.DatabaseError)
    def database_error(error):
        return jsonify(error="O banco de dados não confirmou a operação. Verifique espaço, permissões e outras instâncias abertas; atualize o acervo antes de tentar novamente."), 503

    @app.errorhandler(HTTPException)
    def http_error(error):
        message = "Arquivo muito grande. Limites: 1 GB por mídia e 4 GB por backup ZIP." if error.code == 413 else error.description
        return jsonify(error=message), error.code

    @app.get("/")
    def index():
        return render_template("index.html", token=app.config["APP_TOKEN"])

    @app.get("/api/state")
    def state():
        with db() as connection:
            result = project_records(connection)
        for asset in result["assets"]:
            asset["thumbnail_url"] = f"/media/{asset['id']}/thumbnail"
            asset["url"] = f"/media/{asset['id']}"
        pairs = []
        assets = result["assets"]
        for i, left in enumerate(assets):
            if left["kind"] != "image":
                continue
            for right in assets[i + 1:]:
                if right["kind"] != "image":
                    continue
                distance = (int(left["dhash"], 16) ^ int(right["dhash"], 16)).bit_count()
                if distance <= 6:
                    pairs.append({"left": left["id"], "right": right["id"], "distance": distance})
        result["similarities"] = pairs
        result["ffmpeg_available"] = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
        return jsonify(result)

    @app.post("/api/episodes")
    def add_episode():
        data = json_object()
        code = text_field(data, "code", 40).upper()
        if not code:
            raise InputError("Informe o código do episódio, por exemplo EP04.")
        with db() as connection:
            cursor = connection.execute("INSERT INTO episodes(code,title) VALUES(?,?)", (code, text_field(data, "title", 200)))
        return jsonify(id=cursor.lastrowid), 201

    @app.post("/api/episodes/<int:episode_id>/takes")
    def add_take(episode_id):
        data = json_object()
        with db() as connection:
            require_row(connection, "episodes", episode_id)
            number = positive_number(data.get("number"))
            cursor = connection.execute("INSERT INTO takes(episode_id,number,title) VALUES(?,?,?)",
                                        (episode_id, number, text_field(data, "title", 200)))
        return jsonify(id=cursor.lastrowid), 201

    @app.get("/api/episodes/<int:episode_id>/deletion-preview")
    def preview_episode_deletion(episode_id):
        return deletion_preview("episode", episode_id)

    @app.get("/api/takes/<int:take_id>/deletion-preview")
    def preview_take_deletion(take_id):
        return deletion_preview("take", take_id)

    @app.delete("/api/episodes/<int:episode_id>")
    def delete_episode(episode_id):
        return delete_confirmed("episode", episode_id)

    @app.delete("/api/takes/<int:take_id>")
    def delete_take(take_id):
        return delete_confirmed("take", take_id)

    @app.patch("/api/takes/<int:take_id>")
    def update_take(take_id):
        data = json_object()
        with db() as connection:
            current = dict(require_row(connection, "takes", take_id))
            for key in ("title", "prompt", "notes"):
                if key in data:
                    current[key] = text_field(data, key, 200 if key == "title" else 20000)
            if "number" in data:
                current["number"] = positive_number(data["number"])
            if "status" in data:
                if not isinstance(data["status"], str) or data["status"] not in STATUSES:
                    raise InputError("Escolha APROVADO, EM INVESTIGAÇÃO ou DESCARTADO.")
                current["status"] = data["status"]
            connection.execute("UPDATE takes SET number=?,title=?,prompt=?,notes=?,status=? WHERE id=?",
                               tuple(current[k] for k in ("number", "title", "prompt", "notes", "status")) + (take_id,))
        return jsonify(ok=True)

    @app.post("/api/takes/<int:take_id>/media")
    def upload(take_id):
        upload = request.files.get("file")
        if not upload or not upload.filename:
            raise InputError("Selecione uma imagem ou um vídeo.")
        version = text_field(request.form, "version", 40)
        label = text_field(request.form, "label", 200)
        expected_kind = request.form.get("kind")
        with tempfile.TemporaryDirectory(dir=root / "tmp") as folder, db() as connection:
            require_row(connection, "takes", take_id)
            work = Path(folder)
            source = work / "upload"
            upload.save(source)
            if source.stat().st_size > MAX_MEDIA:
                raise InputError("A mídia excede o limite de 1 GB.")
            asset_id, kind = store_media(connection, source, upload.filename, work, expected_kind)
            binding_id = bind(connection, take_id, asset_id, kind, version, label,
                              original_name=Path(upload.filename.replace("\\", "/")).name[:255])
        return jsonify(id=binding_id, asset_id=asset_id), 201

    @app.post("/api/takes/<int:take_id>/link")
    def link_existing(take_id):
        data = json_object()
        with db() as connection:
            require_row(connection, "takes", take_id)
            asset = require_row(connection, "assets", data.get("asset_id"))
            if not connection.execute("SELECT 1 FROM bindings WHERE asset_id=? LIMIT 1", (asset["id"],)).fetchone():
                raise InputError("Esta mídia não tem vínculos restantes. Atualize o seletor ou importe uma cópia novamente.")
            binding_id = bind(connection, take_id, asset["id"], asset["kind"], text_field(data, "version", 40),
                              text_field(data, "label", 200))
        return jsonify(id=binding_id), 201

    @app.patch("/api/bindings/<int:binding_id>")
    def edit_binding(binding_id):
        data = json_object()
        with db() as connection:
            current = dict(require_row(connection, "bindings", binding_id))
            for key in ("version", "label"):
                if key in data:
                    current[key] = text_field(data, key, 40 if key == "version" else 200)
            if data.get("active") is True:
                connection.execute("UPDATE bindings SET active=0 WHERE take_id=? AND kind=?",
                                   (current["take_id"], current["kind"]))
                current["active"] = 1
            elif data.get("active") is False:
                current["active"] = 0
            # A new selected file or a revised identifier requires the operator to review again.
            connection.execute("UPDATE takes SET status='investigating' WHERE id=?", (current["take_id"],))
            connection.execute("UPDATE bindings SET version=?,label=?,active=? WHERE id=?",
                               (current["version"], current["label"], current["active"], binding_id))
        return jsonify(ok=True)

    @app.get("/media/<int:asset_id>")
    @app.get("/media/<int:asset_id>/<mode>")
    def media(asset_id, mode=None):
        with db() as connection:
            asset = require_row(connection, "assets", asset_id)
        if mode == "thumbnail":
            return send_from_directory(root / "thumbs", asset["sha"] + ".jpg")
        if mode not in {None, "download"}:
            raise InputError("Tipo de mídia inválido.")
        return send_from_directory(root / "media", asset["sha"] + asset["extension"],
                                   as_attachment=mode == "download", download_name=asset["original_name"], conditional=True)

    @app.get("/api/export")
    def export():
        with db() as connection:
            manifest = project_records(connection)
        manifest["format"] = "leonan-media-manager"
        manifest["version"] = 1
        encoded_manifest = json.dumps(manifest, ensure_ascii=False, indent=2)
        total_size = len(encoded_manifest.encode("utf-8")) + sum(
            (root / "media" / (asset["sha"] + asset["extension"])).stat().st_size for asset in manifest["assets"])
        if total_size > MAX_RESTORE or len(manifest["assets"]) > 9999 or len(encoded_manifest.encode("utf-8")) > 10 * 1024 * 1024:
            raise InputError("O projeto excede o limite do ZIP (4 GB / 9.999 mídias). Com o aplicativo fechado, copie a pasta de dados inteira como backup.")
        # Spooled temporary file keeps large projects off the Python heap.
        archive = tempfile.TemporaryFile(dir=root / "tmp")
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as bundle:
            bundle.writestr("project.json", encoded_manifest)
            for asset in manifest["assets"]:
                filename = asset["sha"] + asset["extension"]
                bundle.write(root / "media" / filename, "media/" + filename)
        archive.seek(0)
        response = send_file(archive, mimetype="application/zip", as_attachment=True,
                             download_name="LEONAN-projeto.zip")
        response.call_on_close(archive.close)
        return response

    @app.post("/api/restore")
    def restore():
        upload = request.files.get("file")
        if not upload:
            raise InputError("Selecione o ZIP exportado pelo aplicativo.")
        with tempfile.TemporaryDirectory(dir=root / "tmp") as folder:
            work = Path(folder)
            source = work / "project.zip"
            upload.save(source)
            try:
                with zipfile.ZipFile(source) as bundle:
                    manifest = validate_archive(bundle)
                    with db() as connection:
                        # Force transaction before reading so concurrent restores cannot collide.
                        connection.execute("BEGIN IMMEDIATE")
                        asset_map, episode_map, take_map = {}, {}, {}
                        for asset in manifest["assets"]:
                            target = work / "incoming"
                            with bundle.open("media/" + asset["sha"] + asset["extension"]) as incoming, target.open("wb") as output:
                                shutil.copyfileobj(incoming, output)
                            with target.open("rb") as incoming:
                                if hashlib.file_digest(incoming, "sha256").hexdigest() != asset["sha"]:
                                    raise InputError("Backup corrompido: uma mídia não corresponde ao SHA-256 registrado.")
                            new_id, _ = store_media(connection, target, asset["original_name"], work, asset["kind"])
                            asset_map[asset["id"]] = new_id
                        for episode in manifest["episodes"]:
                            base, code, suffix = episode["code"], episode["code"], 1
                            while connection.execute("SELECT 1 FROM episodes WHERE code=?", (code,)).fetchone():
                                suffix += 1
                                code = f"{base} (restaurado {suffix})"
                            cursor = connection.execute("INSERT INTO episodes(code,title) VALUES(?,?)", (code, episode["title"]))
                            episode_map[episode["id"]] = cursor.lastrowid
                        for take in manifest["takes"]:
                            cursor = connection.execute("INSERT INTO takes(episode_id,number,title,prompt,notes,status) VALUES(?,?,?,?,?,?)",
                                                        (episode_map[take["episode_id"]], take["number"], take["title"],
                                                         take["prompt"], take["notes"], take["status"]))
                            take_map[take["id"]] = cursor.lastrowid
                        source_assets = {a["id"]: a for a in manifest["assets"]}
                        for binding in manifest["bindings"]:
                            connection.execute("INSERT INTO bindings(take_id,asset_id,kind,version,label,active,original_name) VALUES(?,?,?,?,?,?,?)",
                                               (take_map[binding["take_id"]], asset_map[binding["asset_id"]], source_assets[binding["asset_id"]]["kind"],
                                                binding["version"], binding["label"], binding["active"],
                                                binding.get("original_name", source_assets[binding["asset_id"]]["original_name"])))
            except (zipfile.BadZipFile, KeyError, TypeError, ValueError, UnicodeError, RuntimeError, EOFError, AttributeError) as exc:
                raise InputError("Backup inválido ou incompleto. Use um ZIP exportado pelo LEONAN MEDIA MANAGER.") from exc
        return jsonify(ok=True, episode_ids=list(episode_map.values()))

    @app.post("/api/demo")
    def demo():
        # Generated locally; no paid service, AI, stock content, or operator files.
        from PIL import ImageDraw
        with tempfile.TemporaryDirectory(dir=root / "tmp") as folder, db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute("SELECT id FROM episodes WHERE code='PILOTO'").fetchone()
            if existing:
                return jsonify(id=existing["id"])
            episode_id = connection.execute("INSERT INTO episodes(code,title) VALUES('PILOTO','Demonstração • mídias sintéticas')").lastrowid
            work = Path(folder)
            for number, title in enumerate(("A ordem na cozinha", "O detalhe da xícara", "A reação na porta"), 1):
                take_id = connection.execute("INSERT INTO takes(episode_id,number,title,prompt,notes) VALUES(?,?,?,?,?)",
                                             (episode_id, number, title, "Exemplo de prompt: plano fixo, manter cenário e personagem.",
                                              "Mídia sintética de demonstração. Substitua pelas imagens reais do episódio.")).lastrowid
                image = Image.new("RGB", (960, 540), "#253a43")
                draw = ImageDraw.Draw(image)
                draw.rectangle((0, 350, 960, 540), fill="#c7a779")
                draw.rectangle((80, 60, 330, 310), fill="#9eb9b7")
                draw.rectangle((100, 80, 310, 290), fill="#dce8d3")
                # Take 2 intentionally has a very similar anchor to demonstrate the warning.
                x = 580 if number < 3 else 400
                draw.ellipse((x, 110, x + 100, 210), fill="#e8ba83")
                draw.rounded_rectangle((x - 20, 210, x + 120, 430), radius=30, fill="#d98a59")
                draw.rectangle((400, 370, 800, 400), fill="#654f42")
                draw.text((32, 30), f"PILOTO / TAKE {number:02d} / MIDIA SINTETICA", fill="white", font_size=24)
                source = work / f"demo-{number}.png"
                image.save(source)
                asset_id, kind = store_media(connection, source, source.name, work)
                bind(connection, take_id, asset_id, kind, "1", title)
                if number == 1:
                    video = work / "demo.mp4"
                    command(["ffmpeg", "-nostdin", "-v", "error", "-loop", "1", "-i", str(source), "-t", "2",
                             "-vf", "scale=640:360", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-threads", "1",
                             "-movflags", "+faststart", "-y", str(video)])
                    asset_id, kind = store_media(connection, video, video.name, work)
                    bind(connection, take_id, asset_id, kind, "1.0", "Clipe de demonstração")
        return jsonify(id=episode_id), 201

    return app


def validate_archive(bundle):
    """Validate before changing the registry. Never extract arbitrary ZIP paths."""
    entries = bundle.infolist()
    names = [entry.filename for entry in entries]
    if len(entries) > 10000 or len(names) != len(set(names)) or sum(e.file_size for e in entries) > MAX_RESTORE:
        raise InputError("Backup excede os limites ou contém entradas repetidas.")
    if "project.json" not in names or bundle.getinfo("project.json").file_size > 10 * 1024 * 1024:
        raise InputError("Registro do projeto ausente ou muito grande.")
    manifest = json.loads(bundle.read("project.json"))
    if manifest.get("format") != "leonan-media-manager" or manifest.get("version") != 1:
        raise InputError("Formato de backup não reconhecido.")
    maps = {}
    for table in ("episodes", "takes", "assets", "bindings"):
        rows = manifest[table]
        if not isinstance(rows, list) or len(rows) > 10000:
            raise InputError("Registro inválido.")
        ids = [r["id"] for r in rows]
        if any(type(i) is not int or i < 1 for i in ids) or len(ids) != len(set(ids)):
            raise InputError("Identificadores inválidos no backup.")
        maps[table] = {r["id"]: r for r in rows}
    codes, numbers, active = set(), set(), set()
    for episode in manifest["episodes"]:
        code = text_field(episode, "code", 1000)
        text_field(episode, "title", 200)
        if not code or code in codes:
            raise InputError("Episódios inválidos no backup.")
        codes.add(code)
    for take in manifest["takes"]:
        key = (take["episode_id"], positive_number(take["number"]))
        if take["episode_id"] not in maps["episodes"] or key in numbers or take["status"] not in STATUSES:
            raise InputError("Takes inválidos no backup.")
        numbers.add(key)
        for field in ("title", "prompt", "notes"):
            text_field(take, field, 200 if field == "title" else 20000)
    expected_files = {"project.json"}
    for asset in manifest["assets"]:
        sha, extension = asset["sha"], asset["extension"]
        if not isinstance(sha, str) or len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
            raise InputError("Hash inválido no backup.")
        if extension not in set(IMAGE_FORMATS.values()) | VIDEO_EXTENSIONS or asset["kind"] not in {"image", "video"}:
            raise InputError("Tipo de mídia inválido no backup.")
        text_field(asset, "original_name", 255)
        name = "media/" + sha + extension
        if name not in names or bundle.getinfo(name).file_size > MAX_MEDIA:
            raise InputError("Mídia ausente ou muito grande no backup.")
        expected_files.add(name)
    if set(names) != expected_files:
        raise InputError("O backup contém arquivos inesperados.")
    for binding in manifest["bindings"]:
        if binding["take_id"] not in maps["takes"] or binding["asset_id"] not in maps["assets"]:
            raise InputError("Vínculo inválido no backup.")
        kind = maps["assets"][binding["asset_id"]]["kind"]
        if binding["kind"] != kind or type(binding["active"]) is not int or binding["active"] not in {0, 1}:
            raise InputError("Seleção de mídia inválida no backup.")
        key = (binding["take_id"], kind)
        if binding["active"] and key in active:
            raise InputError("Mais de uma versão ativa para a mesma mídia.")
        if binding["active"]:
            active.add(key)
        text_field(binding, "version", 40)
        text_field(binding, "label", 200)
        text_field(binding, "original_name", 255)
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LEONAN MEDIA MANAGER — somente neste computador")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-dir", help="Pasta local do registro e das cópias de mídia")
    args = parser.parse_args()
    create_app(args.data_dir).run(host="127.0.0.1", port=args.port, debug=False, threaded=False)
