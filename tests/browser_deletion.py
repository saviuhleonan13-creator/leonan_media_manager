"""Real UI deletion/restore checks using synthetic media in fresh temporary registries."""
import argparse
from contextlib import closing, contextmanager
import hashlib
import io
import json
import os
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
from playwright.sync_api import sync_playwright, expect, TimeoutError as PlaywrightTimeoutError


def wait_for_properties(locator, expression, predicate, description, timeout=30):
    """Poll DOM properties through DevTools; no page-side eval or CSP bypass.

    JavaScript errors propagate. The deadline includes locator resolution;
    polling never substitutes a fixed sleep for the required assertion.
    """
    deadline = time.monotonic() + timeout
    last = None
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise AssertionError(f"{description}: timeout de {timeout}s; último estado: {last!r}")
        try:
            last = locator.evaluate(expression, timeout=max(1, remaining * 1000))
        except PlaywrightTimeoutError as exc:
            raise AssertionError(f"{description}: elemento indisponível dentro de {timeout}s; último estado: {last!r}") from exc
        if predicate(last):
            return last
        time.sleep(min(0.05, max(0, deadline - time.monotonic())))


def wait_video_progress(video, timeout=30):
    return wait_for_properties(
        video,
        "video => ({time: video.currentTime, readyState: video.readyState, "
        "paused: video.paused, error: video.error ? {code: video.error.code, message: video.error.message} : null})",
        lambda state: state['time'] > 0 and state['error'] is None,
        "O vídeo não avançou além de zero segundos", timeout)


def wait_card_images(page, timeout=30):
    return wait_for_properties(
        page.locator('body'),
        "body => Array.from(body.querySelectorAll('.take-card img'), image => "
        "({src: image.currentSrc || image.src, complete: image.complete, width: image.naturalWidth, height: image.naturalHeight}))",
        lambda states: bool(states) and all(s['complete'] and s['width'] > 0 and s['height'] > 0 for s in states),
        "As imagens dos takes não carregaram com dimensões válidas", timeout)


UNCONFIRMED_SERVERS = set()


def diagnostic(event, **values):
    print("RECURSOS " + json.dumps({"evento": event, **values}, ensure_ascii=True), flush=True)


def log_holders(path):
    """Read-only diagnostics. Never asks Restart Manager to shut down anything."""
    if os.name != "nt":
        holders = set()
        for process in Path("/proc").glob("[0-9]*"):
            try:
                for fd in (process / "fd").iterdir():
                    try:
                        if fd.resolve() == path.resolve():
                            holders.add(int(process.name))
                    except OSError:
                        pass  # A descriptor can disappear during this diagnostic snapshot.
            except (PermissionError, FileNotFoundError):
                continue
        return sorted(holders)
    import ctypes
    from ctypes import wintypes

    class UniqueProcess(ctypes.Structure):
        _fields_ = [("pid", wintypes.DWORD), ("started", wintypes.FILETIME)]

    class ProcessInfo(ctypes.Structure):
        _fields_ = [("process", UniqueProcess), ("name", wintypes.WCHAR * 256),
                    ("service", wintypes.WCHAR * 64), ("type", ctypes.c_int),
                    ("status", wintypes.ULONG), ("session", wintypes.DWORD),
                    ("restartable", wintypes.BOOL)]

    rm = ctypes.WinDLL("Rstrtmgr")
    handle = wintypes.DWORD()
    key = ctypes.create_unicode_buffer(33)
    status = rm.RmStartSession(ctypes.byref(handle), 0, key)
    if status:
        raise OSError(status, "RmStartSession")
    try:
        names = (wintypes.LPCWSTR * 1)(str(path.resolve()))
        status = rm.RmRegisterResources(handle, 1, names, 0, None, 0, None)
        if status:
            raise OSError(status, "RmRegisterResources")
        needed, count, reasons = wintypes.UINT(), wintypes.UINT(), wintypes.DWORD()
        status = rm.RmGetList(handle, ctypes.byref(needed), ctypes.byref(count), None, ctypes.byref(reasons))
        if status == 0:
            return []
        if status != 234:  # ERROR_MORE_DATA
            raise OSError(status, "RmGetList")
        entries = (ProcessInfo * needed.value)()
        count.value = needed.value
        status = rm.RmGetList(handle, ctypes.byref(needed), ctypes.byref(count), entries, ctypes.byref(reasons))
        if status:
            raise OSError(status, "RmGetList (snapshot mudou ou indisponível)")
        return [entries[i].process.pid for i in range(count.value)]
    finally:
        status = rm.RmEndSession(handle)
        if status:
            raise OSError(status, "RmEndSession")


def resource_snapshot(pid, log_path, phase, observed=None):
    """Snapshots are evidence, not proof of ownership and never termination targets."""
    try:
        if os.name == "nt":
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                 "Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId | ConvertTo-Json -Compress"],
                capture_output=True, text=True, timeout=5, check=True)
            rows = json.loads(result.stdout)
            parents = {int(r['ProcessId']): int(r['ParentProcessId']) for r in (rows if isinstance(rows, list) else [rows])}
        else:
            parents = {}
            for entry in Path('/proc').glob('[0-9]*/stat'):
                try:
                    fields = entry.read_text().rsplit(')', 1)[1].split()
                    parents[int(entry.parent.name)] = int(fields[1])
                except FileNotFoundError:
                    continue
        descendants = {pid}
        while True:
            expanded = descendants | {child for child, parent in parents.items() if parent in descendants}
            if expanded == descendants:
                break
            descendants = expanded
        if observed is not None:
            observed.update(descendants - {pid})
        remaining = sorted((observed or set()).intersection(parents))
        holders = log_holders(log_path)
        diagnostic(phase, pid=pid, descendentes=sorted(descendants - {pid}), log=str(log_path),
                   processos_com_log_aberto=holders, pids_descendentes_observados_ainda_presentes=remaining)
        return sorted(set(holders) | set(remaining))
    except Exception as exc:
        diagnostic(phase, pid=pid, diagnostico_indisponivel=repr(exc))


@contextmanager
def cleanup_after(action):
    """Keep both failures when a functional error is followed by a cleanup error."""
    try:
        yield
    except BaseException as original:
        try:
            action()
        except BaseException as secondary:
            raise BaseExceptionGroup("Falha original e falha de encerramento", [original, secondary]) from None
        raise
    else:
        action()


@contextmanager
def synthetic_directory(prefix):
    # Only a directory freshly created by this invocation can reach rmtree.
    root = Path(tempfile.mkdtemp(prefix=prefix))
    diagnostic('diretorio_criado', diretorio=str(root))

    def cleanup():
        try:
            if any(server.is_relative_to(root) for server in UNCONFIRMED_SERVERS):
                raise RuntimeError(f'Encerramento não confirmado; diretório sintético preservado: {root}')
            subprocess.run([sys.executable, '-B', '-c',
                            'import shutil,sys; shutil.rmtree(sys.argv[1])', str(root)],
                           check=True, timeout=15)
            if root.exists():
                raise AssertionError(f"Diretório sintético ainda existe: {root}")
            diagnostic('limpeza_concluida', diretorio=str(root))
        except BaseException:
            diagnostic('limpeza_falhou', diretorio=str(root))
            for path in root.glob('server-*.log'):
                resource_snapshot(os.getpid(), path, 'log_apos_falha_limpeza')
            raise

    with cleanup_after(cleanup):
        yield root


@contextmanager
def managed_browser(playwright):
    browser = playwright.chromium.launch(executable_path=shutil.which("chromium") or shutil.which("google-chrome"),
                                         args=["--no-sandbox"])

    def close():
        failures = []
        for context in list(browser.contexts):
            for page in list(context.pages):
                try:
                    page.close()
                except BaseException as exc:
                    failures.append(exc)
            try:
                context.close()
            except BaseException as exc:
                failures.append(exc)
        try:
            browser.close()
            if browser.is_connected():
                raise AssertionError("Navegador ainda conectado após close")
        except BaseException as exc:
            failures.append(exc)
        if failures:
            raise BaseExceptionGroup("Falhas ao fechar navegador/páginas/contextos", failures)
        diagnostic('navegador_fechado')

    with cleanup_after(close):
        yield browser


@contextmanager
def isolated_server(python, root):
    repo = Path(__file__).resolve().parents[1]
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    log_path = root.parent / f"server-{port}.log"
    with log_path.open("w+") as log:
        process = subprocess.Popen([python, str(repo / "app.py"), "--port", str(port), "--data-dir", str(root)],
                                   cwd=repo, stdout=log, stderr=log)
        diagnostic('servidor_criado', pid=process.pid, porta=port, diretorio=str(root), log=str(log_path))

        observed = set()

        def stop():
            UNCONFIRMED_SERVERS.add(root)
            resource_snapshot(process.pid, log_path, 'antes_encerramento', observed)
            def close_log():
                log.close()
                diagnostic('log_fechado', pid=process.pid, fechado=log.closed)
                holders = resource_snapshot(process.pid, log_path, 'apos_encerramento', observed)
                if holders:
                    raise AssertionError(f'Log ainda aberto ou descendente observado ainda presente: PIDs {holders}; nenhum deles será encerrado automaticamente.')

            with cleanup_after(close_log):
                if process.poll() is None:
                    process.terminate()  # Only the Popen-owned PID; shutdown policy unchanged.
                process.wait(timeout=10)
                diagnostic('processo_encerrado', pid=process.pid, retorno=process.returncode)
                deadline = time.monotonic() + 3
                while True:
                    with socket.socket() as probe:
                        probe.settimeout(0.2)
                        listening = probe.connect_ex(('127.0.0.1', port)) == 0
                    if not listening:
                        diagnostic('porta_fechada', pid=process.pid, porta=port)
                        break
                    if time.monotonic() >= deadline:
                        raise AssertionError(f"Porta {port} ainda responde após encerrar PID {process.pid}; nenhum outro processo será encerrado.")
                    time.sleep(0.05)
            UNCONFIRMED_SERVERS.discard(root)

        with cleanup_after(stop):
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
            resource_snapshot(process.pid, log_path, 'servidor_pronto', observed)
            yield base


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
    with synthetic_directory(prefix="leonan-v02-isolated-") as folder:
        root = Path(folder)
        with isolated_server(args.python, root / "original") as base, sync_playwright() as playwright, managed_browser(playwright) as browser:
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
            wait_video_progress(page.locator('video'))
            page.locator('video').evaluate('video => video.pause()')
            wait_card_images(page)
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
                wait_video_progress(restored_page.locator('video'))
                restored_page.locator('video').evaluate('video => video.pause()')
                restored_page.get_by_role('button',name='Excluir este take',exact=True).click()
                expect(restored_page.locator('#form-dialog')).to_be_visible()
                assert restored_page.evaluate('() => document.documentElement.scrollWidth <= window.innerWidth')
                restored_page.get_by_role('button',name='Cancelar',exact=True).click()
                restored_page.close()
            assert not failed_media, failed_media
            assert not errors, errors
            assert not outside, outside
    print('PASSOU V0.2: exclusão do PILOTO e TAKE, cancelamento, código/backup obrigatórios, erro na UI, biblioteca sem órfãos, mídias compartilhadas inclusive históricas, reversão, continuidade, vídeo/miniaturas, integridade SQLite e exportação/restauração em acervo vazio. Todos os dados eram sintéticos e temporários.')


if __name__ == '__main__':
    main()
