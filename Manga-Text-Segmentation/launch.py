"""Start or reuse the local model, including hidden launches from Photoshop."""
from contextlib import contextmanager
import json
import msvcrt
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parent
URL = "http://127.0.0.1:7860"
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def ready():
    try:
        with opener.open(URL + "/ps/v1/health", timeout=1) as response:
            data = json.load(response)
            return data.get("service") == "manga-text-selection" and data.get("protocol") == 1
    except Exception:
        return False


@contextmanager
def startup_lock():
    # Serialize launches from PS, the browser shortcut, or another PS instance.
    with (ROOT / "startup.lock").open("a+b") as lock:
        lock.seek(0, os.SEEK_END)
        if not lock.tell():
            lock.write(b"0")
            lock.flush()
        deadline = time.monotonic() + 100
        while True:
            lock.seek(0)
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("另一启动任务尚未完成，请查看服务日志。")
                time.sleep(.5)
        try:
            yield
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def start_service():
    env = os.environ.copy()
    # The model is offline. PS may inherit a SOCKS proxy that breaks Gradio's
    # HTTP client during import even when NO_PROXY includes loopback addresses.
    for name in list(env):
        if name.lower() in {"http_proxy", "https_proxy", "all_proxy"}:
            env.pop(name)
    env["NO_PROXY"] = "localhost,127.0.0.1,::1"
    env["PYTHONUTF8"] = "1"
    env["MANGA_WATCH_PHOTOSHOP"] = "1" if "--photoshop" in sys.argv else "0"
    with (ROOT / "server.log").open("w", encoding="utf-8") as output, (ROOT / "server-error.log").open("w", encoding="utf-8") as error:
        process = subprocess.Popen(
            [str(ROOT / ".venv" / "Scripts" / "python.exe"), "-u", str(ROOT / "app.py")], cwd=ROOT, env=env,
            stdout=output, stderr=error, stdin=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if ready():
            return
        if process.poll() is not None:
            raise RuntimeError("服务启动失败，请查看 server-error.log。")
        time.sleep(1)
    raise RuntimeError("服务尚未就绪，请查看 server-error.log。")


def main():
    if not ready():
        with startup_lock():
            if not ready():
                (ROOT / "launch-error.log").write_text("", encoding="utf-8")
                start_service()
    if "--no-browser" not in sys.argv:
        webbrowser.open(URL)
    if sys.stdout:
        print("Ready: " + URL)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        (ROOT / "launch-error.log").write_text(traceback.format_exc(), encoding="utf-8")
        if sys.stderr:
            print(str(error), file=sys.stderr)
        sys.exit(1)
