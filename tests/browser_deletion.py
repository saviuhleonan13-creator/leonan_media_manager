"""Real UI deletion/restore checks using synthetic media in fresh temporary registries."""
import argparse
from contextlib import closing, contextmanager
import hashlib
import io
import json
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile

from PIL import Image
from playwright.sync_api import sync_playwright, expect


@contextmanager
def isolated_server(python, root):
    repo = Path(__file__).resolve().parents[1]
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    with (root.parent / f"server-{port}.log").open("w+") as log:
        process = subprocess.Popen([python, str(repo / "app.py"), "--port", str(port), "--data-dir", str(root)],
                                   cwd=repo, stdout=log, stderr=log)
        try:
            for _ in range(100):
                try:
                    urllib.request.urlopen(base + "/api/state", timeout=1).close()
                    break
                except OSError:
                    if process.poll() is not None:
                        log.seek(0)
                        raise RuntimeError(log.read())
                    time.sleep(.1)
            else:
                raise RuntimeError("O servidor de teste não iniciou.")
            yield base
        finally:
            process.terminate()
            process.wait(timeout=10)


def signature(state):
    assets = {a["id"]: a for a in state["assets"]}
    episodes = {e["id"]: e for e in state["episodes"]}
    return sorted((episodes[t["episode_id"]]["code"], t["number"], t["title"], t["prompt"], t["notes"], t["status"],
                   sorted((assets[b["asset_id"]]["sha"], b["kind"], b["version"], b["active"], b["label"], b["original_name"])
                          for b in state["bindings"] if b["take_id"] == t["id"])) for t in state["takes"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--screenshot", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="leonan-v02-isolated-") as folder:
        root = Path(folder)
        with isolated_server(args.python, root / "original") as base, sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=shutil.which("chromium") or shutil.which("google-chrome"),
                                                 args=["--no-sandbox"])
            page = browser.new_page(viewport={"width":1440, "height":1050})
            errors, failed_media, outside = [], [], []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("response", lambda r: failed_media.append(r.url) if "/media/" in r.url and r.status >= 400 else None)
            page.on("request", lambda r: outside.append(r.url) if not r.url.startswith(base + "/") else None)
            page.goto(base)
            page.get_by_role("button", name="Conhecer com um piloto").click()
            expect(page.locator(".take-card")).to_have_count(3)
            headers = {"X-App-Token": page.locator('meta[name="app-token"]').get_attribute("content")}

            def state():
                return page.request.get(base + "/api/state").json()

            def post(path, body):
                response = page.request.post(base + path, headers=headers, data=body)
                assert response.ok, response.text()
                return response.json()

            def upload(take, name, content, kind="image", version="1"):
                response = page.request.post(base + f"/api/takes/{take}/media", headers=headers,
                    multipart={"file":{"name":name,"mimeType":"image/png" if kind == "image" else "video/mp4","buffer":content},
                               "kind":kind, "version":version, "label":"Mídia SINTÉTICA de teste"})
                assert response.ok, response.text()
                return response.json()["asset_id"]

            pilot_state = state()
            pilot_images = [a for a in pilot_state["assets"] if a["kind"] == "image"]
            pilot_video = next(a for a in pilot_state["assets"] if a["kind"] == "video")
            shared = pilot_images[0]
            episode = post("/api/episodes", {"code":"EP04", "title":"ACERVO SINTÉTICO DE TESTE"})["id"]
            take_ids = {}
            for number in (4,8,9):
                take_ids[number] = post(f"/api/episodes/{episode}/takes", {"number":number, "title":f"Cena sintética {number}"})["id"]
            for color, version in (("#82a8c1","1"),("#c3b58c","3.1")):
                image = Image.new("RGB", (400,225), color)
                buffer = io.BytesIO()
                image.save(buffer,"PNG")
                current_image = upload(take_ids[4], f"EP04-sintético-V{version}.png", buffer.getvalue(), version=version)
            post(f"/api/takes/{take_ids[8]}/link", {"asset_id":shared["id"],"version":"1"})
            historical = next(b for b in state()["bindings"] if b["take_id"] == take_ids[8])
            upload(take_ids[8], "EP04-sintético-atual.png", buffer.getvalue(), version="2")
            post(f"/api/takes/{take_ids[9]}/link", {"asset_id":current_image,"version":"3.1"})
            video = root / "vídeo EP04 sintético.mp4"
            subprocess.run(["ffmpeg","-nostdin","-v","error","-f","lavfi","-i","color=c=blue:s=320x180:d=1",
                            "-c:v","libx264","-pix_fmt","yuv420p","-threads","1",str(video)],check=True)
            video_hash = hashlib.sha256(video.read_bytes()).hexdigest()
            video_id = upload(take_ids[4], video.name, video.read_bytes(), kind="video", version="1.3")
            post(f"/api/takes/{take_ids[9]}/link", {"asset_id":video_id,"version":"1.3"})
            response = page.request.patch(base + f"/api/takes/{take_ids[9]}", headers=headers,
                                          data={"status":"approved","prompt":"Prompt sintético","notes":"Observação sintética"})
            assert response.ok
            before = state()
            files = {str(p.relative_to(root/"original")): hashlib.sha256(p.read_bytes()).hexdigest()
                     for directory in ("media","thumbs") for p in (root/"original"/directory).iterdir()}
            page.reload()
            expect(page.locator(".episode-button")).to_have_count(2)
            expect(page.locator(".version-tag")).to_have_text("V0.2")
            # Opening and canceling must not modify any record.
            page.get_by_role("button", name="Excluir episódio", exact=True).click()
            expect(page.locator("#dialog-title")).to_have_text("Excluir episódio")
            expect(page.locator("#dialog-fields")).to_contain_text("PILOTO")
            expect(page.locator("#dialog-fields")).to_contain_text("3 take(s), 3 imagem(ns) distinta(s), 1 vídeo(s)")
            page.locator("#dialog-submit").click()  # Missing explicit code/backup: native validation.
            assert state() == before
            page.locator('input[name="confirm_code"]').fill("ERRADO")
            page.locator('input[name="backup_confirmed"]').check()
            page.locator("#dialog-submit").click()
            expect(page.locator("#dialog-error")).to_contain_text("código informado não corresponde")
            assert state() == before
            page.get_by_role("button", name="Cancelar", exact=True).click()
            expect(page.locator("#form-dialog")).not_to_be_visible()
            assert state() == before
            page.get_by_role("button", name="Excluir episódio", exact=True).click()
            page.locator('input[name="confirm_code"]').fill("PILOTO")
            page.locator("#dialog-submit").click()  # Still needs backup acknowledgment.
            assert state() == before
            page.locator('input[name="backup_confirmed"]').check()
            if args.screenshot:
                args.screenshot.parent.mkdir(parents=True, exist_ok=True)
                page.locator('input[name="confirm_code"]').focus()
                page.screenshot(path=str(args.screenshot))
            page.locator("#dialog-submit").click()
            expect(page.locator("#form-dialog")).not_to_be_visible()
            expect(page.locator(".episode-button")).to_have_count(1)
            expect(page.locator(".episode-button")).not_to_contain_text("PILOTO")
            after = state()
            assert [t for t in before["takes"] if t["episode_id"] == episode] == after["takes"]
            assert [b for b in before["bindings"] if b["take_id"] in take_ids.values()] == after["bindings"]
            orphan_ids = {a["id"] for a in pilot_images[1:]} | {pilot_video["id"]}
            assert not orphan_ids.intersection(a["id"] for a in after["assets"])
            assert shared["id"] in {a["id"] for a in after["assets"]}
            assert not any(p["left"] in orphan_ids or p["right"] in orphan_ids for p in after["similarities"])
            # The real reuse selector contains every referenced image, and no orphan.
            page.locator('[data-action="reuse"][data-kind="image"]').click()
            options = page.locator('#dialog-fields select[name="asset_id"] option').evaluate_all("options => options.map(o => Number(o.value))")
            assert set(options) == {a["id"] for a in after["assets"] if a["kind"] == "image"}
            page.get_by_role("button", name="Cancelar", exact=True).click()
            # Take confirmation identifies its episode, original number and description.
            page.get_by_role("button", name="Excluir este take", exact=True).click()
            expect(page.locator("#dialog-fields")).to_contain_text("EP04 TAKE-04 — Cena sintética 4")
            page.get_by_role("button", name="Cancelar", exact=True).click()
            assert state() == after
            page.get_by_role("button", name="Excluir este take", exact=True).click()
            page.locator('input[name="backup_confirmed"]').check()
            # A server failure must leave the dialog open and records unchanged.
            path = base + f"/api/takes/{take_ids[4]}"
            page.route(path, lambda route: route.fulfill(status=503, content_type="application/json",
                       body=json.dumps({"error":"Banco não confirmou a operação (falha sintética de teste)."})))
            page.locator("#dialog-submit").click()
            expect(page.locator("#dialog-error")).to_contain_text("não confirmou")
            expect(page.locator("#form-dialog")).to_be_visible()
            assert state() == after
            page.unroute(path)
            page.locator("#dialog-submit").click()
            expect(page.locator("#form-dialog")).not_to_be_visible()
            expect(page.locator(".take-card")).to_have_count(2)
            remaining = state()
            assert remaining["takes"] == [t for t in after["takes"] if t["id"] != take_ids[4]]
            assert remaining["bindings"] == [b for b in after["bindings"] if b["take_id"] != take_ids[4]]
            assert [t["number"] for t in remaining["takes"]] == [8,9]
            assert files == {str(p.relative_to(root/"original")): hashlib.sha256(p.read_bytes()).hexdigest()
                             for directory in ("media","thumbs") for p in (root/"original"/directory).iterdir()}
            # Reverse to the historical shared image after its original episode was deleted.
            page.locator('.version-list').first.locator('summary').click()
            page.locator(f'[data-action="select-binding"][data-id="{historical["id"]}"]').click()
            expect(page.locator('.media-panel').first.locator('.friendly-name')).to_contain_text('V1')
            page.locator('.comparison summary').click()
            expect(page.locator('.compare-card')).to_have_count(2)
            page.locator(f'[data-action="take"][data-id="{take_ids[9]}"]').click()
            expect(page.locator('.status-chip')).to_have_text('APROVADO')
            page.locator('video').evaluate('async video => { await video.play(); }')
            page.wait_for_function("document.querySelector('video').currentTime > 0")
            page.locator('video').evaluate('video => video.pause()')
            page.wait_for_function("[...document.querySelectorAll('.take-card img')].every(i => i.complete && i.naturalWidth > 0)")
            assert hashlib.sha256(video.read_bytes()).hexdigest() == video_hash
            with closing(sqlite3.connect(root/'original'/'registry.sqlite3')) as db, db:
                assert db.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
                assert db.execute('PRAGMA foreign_key_check').fetchall() == []
            with page.expect_download() as download:
                page.locator('#export').click()
            backup = root/'backup após exclusão.zip'
            download.value.save_as(backup)
            with zipfile.ZipFile(backup) as bundle:
                manifest = json.loads(bundle.read('project.json'))
                assert [e['code'] for e in manifest['episodes']] == ['EP04']
                assert not orphan_ids.intersection(a['id'] for a in manifest['assets'])
            expected = signature(state())
            # Restore the post-deletion ZIP into a second entirely empty registry.
            with isolated_server(args.python, root/'restored') as restored_base:
                restored_page = browser.new_page(viewport={'width':390,'height':844})
                restored_page.on('pageerror',lambda error: errors.append(str(error)))
                restored_page.goto(restored_base)
                restored_page.locator('#restore-file').set_input_files(backup)
                expect(restored_page.locator('.episode-button')).to_have_count(1)
                expect(restored_page.locator('.take-card')).to_have_count(2)
                restored_state = restored_page.request.get(restored_base+'/api/state').json()
                assert signature(restored_state) == expected
                ninth = next(t for t in restored_state['takes'] if t['number'] == 9)
                restored_page.locator(f'[data-action="take"][data-id="{ninth["id"]}"]').click()
                restored_page.locator('video').evaluate('async video => { await video.play(); }')
                restored_page.wait_for_function("document.querySelector('video').currentTime > 0")
                restored_page.locator('video').evaluate('video => video.pause()')
                restored_page.get_by_role('button',name='Excluir este take',exact=True).click()
                expect(restored_page.locator('#form-dialog')).to_be_visible()
                assert restored_page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
                restored_page.get_by_role('button',name='Cancelar',exact=True).click()
                restored_page.close()
            assert not failed_media, failed_media
            assert not errors, errors
            assert not outside, outside
            browser.close()
            print('PASSOU V0.2: exclusão do PILOTO e TAKE, cancelamento, código/backup obrigatórios, erro na UI, biblioteca sem órfãos, mídias compartilhadas inclusive históricas, reversão, continuidade, vídeo/miniaturas, integridade SQLite e exportação/restauração em acervo vazio. Todos os dados eram sintéticos e temporários.')


if __name__ == '__main__':
    main()
