"""Optional browser test: python tests/browser_smoke.py --python .venv/bin/python.

Requires Playwright and Chromium only for this test, not to run the application.
Uses a temporary registry; never opens the operator's project.
"""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

from PIL import Image
from playwright.sync_api import sync_playwright, expect


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--screenshot", type=Path)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory() as temporary:
        work = Path(temporary)
        log = (work / "server.log").open("w+")
        process = subprocess.Popen([args.python, str(repo / "app.py"), "--port", str(port), "--data-dir", str(work / "registry")],
                                   stdout=log, stderr=log, cwd=repo)
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
                raise RuntimeError("Servidor não iniciou.")
            with sync_playwright() as playwright:
                executable = shutil.which("chromium") or shutil.which("google-chrome")
                browser = playwright.chromium.launch(executable_path=executable, args=["--no-sandbox"])
                page = browser.new_page(viewport={"width":1440, "height":1100}, device_scale_factor=1)
                errors, external = [], []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
                page.on("request", lambda request: external.append(request.url) if not request.url.startswith(base + "/") else None)
                page.goto(base)
                expect(page.get_by_role("heading", name="Seu episódio, take por take.")).to_be_visible()
                page.get_by_role("button", name="Conhecer com um piloto").click()
                expect(page.locator(".take-card")).to_have_count(3)
                expect(page.locator(".take-detail h2")).to_contain_text("TAKE-01")
                expect(page.locator(".warning")).to_contain_text("Visualmente parecida")
                page.locator(".media-stage.enlarge").click()
                expect(page.locator("#lightbox")).to_be_visible()
                page.get_by_role("button", name="Fechar imagem").click()
                page.locator("video").evaluate("async video => { await video.play(); }")
                page.wait_for_function("document.querySelector('video').currentTime > 0")
                page.locator("video").evaluate("video => video.pause()")
                if args.screenshot:
                    args.screenshot.parent.mkdir(parents=True, exist_ok=True)
                    expect(page.locator("#toast")).to_be_hidden(timeout=8000)
                    assert page.locator("#restore-file").is_hidden()
                    page.screenshot(path=str(args.screenshot), full_page=True)
                page.get_by_role("button", name="🟢 APROVADO", exact=True).click()
                expect(page.locator(".take-detail .status-chip")).to_have_text("APROVADO")
                page.locator(".take-card").nth(1).click()
                expect(page.locator(".take-detail h2")).to_contain_text("TAKE-02")
                expect(page.locator(".media-panel").nth(1)).to_contain_text("Nenhum vídeo importado")
                # New operator episode, unknown original name, metadata save while navigating.
                page.locator("#new-episode").click()
                page.locator("#form-dialog input[name=code]").fill("EP04")
                page.locator("#form-dialog input[name=title]").fill("Teste do operador")
                page.get_by_role("button", name="Salvar", exact=True).click()
                page.get_by_role("button", name="Adicionar TAKE-01").click()
                page.locator("#form-dialog input[name=number]").fill("4")
                page.locator("#form-dialog input[name=title]").fill("Caramela dá a ordem")
                page.get_by_role("button", name="Salvar", exact=True).click()
                page.locator("#take-form textarea[name=notes]").fill("Conferir mão e enquadramento")
                image = work / "Flow output sem identificação.png"
                Image.new("RGB", (400, 225), "#d98a59").save(image)
                original_hash = hashlib.sha256(image.read_bytes()).hexdigest()
                page.locator('[data-action=upload][data-kind=image]').click()
                page.locator("#form-dialog input[type=file]").set_input_files(image)
                page.locator("#form-dialog input[name=version]").fill("3")
                page.locator("#form-dialog input[name=label]").fill("Caramela manda limpar a cozinha")
                page.get_by_role("button", name="Salvar", exact=True).click()
                expect(page.locator(".friendly-name")).to_contain_text("EP04 IMG-04 V3 — Caramela manda limpar a cozinha")
                expect(page.locator("#take-form textarea[name=notes]")).to_have_value("Conferir mão e enquadramento")
                expect(page.locator(".original-name").first).to_contain_text(image.name)
                assert hashlib.sha256(image.read_bytes()).hexdigest() == original_hash
                page.get_by_role("button", name="🟢 APROVADO", exact=True).click()
                expect(page.locator(".take-detail .status-chip")).to_have_text("APROVADO")
                page.locator('[data-action=upload][data-kind=image]').click()
                page.locator("#form-dialog input[type=file]").set_input_files(image)
                page.locator("#form-dialog input[name=version]").fill("3.1")
                page.get_by_role("button", name="Salvar", exact=True).click()
                expect(page.locator(".take-detail .status-chip")).to_have_text("EM INVESTIGAÇÃO")
                expect(page.locator(".warning")).to_contain_text("Arquivo idêntico")
                page.locator(".version-list").first.locator("summary").click()
                page.get_by_role("button", name="Desvincular", exact=True).click()
                expect(page.locator(".media-panel").first).to_contain_text("Vincule a imagem deste take")
                page.locator(".version-list").first.locator("summary").click()
                page.get_by_role("button", name="Usar", exact=True).first.click()
                expect(page.locator(".friendly-name")).to_contain_text("V3.1")
                # Portable ZIP export and additive restore using the visible UI.
                with page.expect_download() as download_info:
                    page.locator("#export").click()
                backup = work / "backup.zip"
                download_info.value.save_as(backup)
                page.locator("#restore-file").set_input_files(backup)
                expect(page.locator(".episode-button")).to_have_count(4)
                page.reload()
                expect(page.locator(".episode-button")).to_have_count(4)
                # Responsive layout: no horizontal body overflow, usable take navigation.
                page.set_viewport_size({"width":390,"height":844})
                page.locator(".episode-button").filter(has_text="EP04").first.click()
                expect(page.locator(".take-detail h2")).to_contain_text("TAKE-04")
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "Overflow horizontal"
                assert not external, f"Requests externos: {external}"
                assert not errors, f"Erros no navegador: {errors}"
                browser.close()
                print("PASSOU: piloto, reprodução de vídeo, ampliação, episódio/take, importação, versões, aprovação, desvinculação, backup/restauração e layout móvel. Sem requests externos ou erros de JavaScript.")
        finally:
            process.terminate()
            process.wait(timeout=10)
            log.close()


if __name__ == "__main__":
    main()
