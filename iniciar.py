"""Start locally. Installs the pinned Python dependencies only when needed."""
import argparse
import hashlib
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request
import venv
import webbrowser


def main():
    parser = argparse.ArgumentParser(description="Abrir LEONAN MEDIA MANAGER neste computador")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-dir", help="Outra pasta para o registro e as cópias de mídia")
    parser.add_argument("--no-browser", action="store_true", help="Iniciar sem abrir o navegador automaticamente")
    args = parser.parse_args()
    if sys.version_info < (3, 10):
        raise SystemExit("Instale Python 3.10 ou superior (3.12 recomendado).")
    if not 1 <= args.port <= 65535:
        raise SystemExit("Escolha uma porta entre 1 e 65535.")
    repo = Path(__file__).resolve().parent
    environment = repo / ".venv"
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.is_file():
        print("Preparando ambiente Python local…", flush=True)
        venv.EnvBuilder(with_pip=True).create(environment)
    requirements = repo / "requirements.txt"
    fingerprint = hashlib.sha256(requirements.read_bytes()).hexdigest()
    marker = environment / ".leonan-requirements"
    probe = subprocess.run([str(python), "-c", "import flask, PIL"], capture_output=True)
    if probe.returncode or not marker.is_file() or marker.read_text() != fingerprint:
        print("Instalando/conferindo dependências. A primeira execução precisa de internet…", flush=True)
        subprocess.run([str(python), "-m", "pip", "install", "-r", str(requirements)], check=True)
        marker.write_text(fingerprint)
    try:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", args.port))
    except OSError:
        raise SystemExit(f"A porta {args.port} já está ocupada. Feche a outra instância ou use --port {args.port + 1}.")
    command = [str(python), str(repo / "app.py"), "--port", str(args.port)]
    if args.data_dir:
        command += ["--data-dir", str(Path(args.data_dir).resolve())]
    process = subprocess.Popen(command, cwd=repo)
    address = f"http://127.0.0.1:{args.port}"
    try:
        for _ in range(150):
            if process.poll() is not None:
                raise SystemExit("Não foi possível iniciar. Confira a mensagem do servidor acima.")
            try:
                with urllib.request.urlopen(address + "/api/state", timeout=1) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(.1)
        else:
            raise SystemExit("O servidor demorou a iniciar. Confira as mensagens acima.")
        print(f"\nLEONAN MEDIA MANAGER aberto em {address}\nMantenha este terminal aberto. Ctrl+C encerra o aplicativo.\n", flush=True)
        if not args.no_browser:
            webbrowser.open(address)
        process.wait()
    except KeyboardInterrupt:
        print("\nEncerrando. Seu registro e as cópias estão salvos.")
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)


if __name__ == "__main__":
    main()
