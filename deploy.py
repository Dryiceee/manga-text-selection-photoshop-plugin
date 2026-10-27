"""Recipient-side deployment; never copies an existing virtual environment."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import struct
import subprocess
import sys
import traceback
import venv

from prepare_plugin import prepare

ROOT = Path(__file__).resolve().parent
MODEL = ROOT / "Manga-Text-Segmentation"
PYTHON = MODEL / ".venv" / "Scripts" / "python.exe"


def run(args, *, local=False):
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    if local:
        for name in list(environment):
            if name.lower() in {"http_proxy", "https_proxy", "all_proxy"}:
                environment.pop(name)
        environment["NO_PROXY"] = "localhost,127.0.0.1,::1"
    print("\n> " + subprocess.list2cmdline([str(item) for item in args]), flush=True)
    with (ROOT / "deploy.log").open("a", encoding="utf-8") as log:
        process = subprocess.Popen([str(item) for item in args], cwd=ROOT, env=environment,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, encoding="utf-8", errors="replace")
        for line in process.stdout:
            print(line, end="", flush=True)
            log.write(line)
        if process.wait():
            raise RuntimeError("命令失败，请查看解压目录的 deploy.log。")


def verify_payload():
    records = json.loads((ROOT / "payload-sha256.json").read_text(encoding="utf-8"))
    for name, expected in records.items():
        path = ROOT / name
        if ROOT not in path.resolve().parents or not path.is_file():
            raise RuntimeError("文件缺失或路径无效：" + name)
        checksum = hashlib.file_digest(path.open("rb"), "sha256").hexdigest()
        if checksum != expected:
            raise RuntimeError("文件校验失败，请重新完整解压：" + name)
    print("分享包文件校验通过。", flush=True)


def ensure_weights():
    """Download the upstream weights at the pinned revision; they are not redistributed."""
    source = json.loads((MODEL / "model-source.json").read_text(encoding="utf-8"))
    target = MODEL / "model.pth"
    def digest(path):
        # Close the file before Windows renames or deletes it.
        with path.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()
    if target.is_file():
        if digest(target) != source["sha256"]:
            raise RuntimeError("现有 model.pth 校验失败。请把它改名或删除后重新运行部署。")
        print("模型权重已存在，SHA256 校验通过。", flush=True)
        return
    url = source["repository"].rstrip("/") + "/resolve/" + source["revision"] + "/model.pth"
    partial = MODEL / "model.pth.part"
    print("正在从 Hugging Face 下载原作者模型权重（约 217 MB）：\n" + url, flush=True)
    curl = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "curl.exe"
    downloaded = False
    if curl.is_file():
        try:
            run([curl, "-L", "--fail", "-sS", "--retry", "3", "--continue-at", "-", "-o", partial, url])
            downloaded = True
        except RuntimeError:
            print("curl 下载失败，改用 Python 下载（会使用系统代理设置）…", flush=True)
    if not downloaded:
        import urllib.request
        try:
            urllib.request.urlretrieve(url, partial)
        except Exception as error:
            raise RuntimeError("模型权重下载失败：" + str(error) + "。请检查网络或代理；也可以用浏览器从上面的地址下载 model.pth，放到 Manga-Text-Segmentation 文件夹后重新运行部署。")
    if digest(partial) != source["sha256"]:
        partial.unlink()
        raise RuntimeError("下载的模型权重校验失败，已删除不完整文件，请重新运行部署。")
    partial.replace(target)
    print("模型权重下载完成，SHA256 校验通过。", flush=True)


def check_platform():
    if os.name != "nt" or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise RuntimeError("本分享包适用于 Windows x64；其他系统需要适配启动器和退出监控。")
    if sys.version_info[:2] != (3, 12) or struct.calcsize("P") != 8:
        raise RuntimeError("请使用 Python 3.12 的 64 位版本。")


def install_environment():
    longest_known = MODEL / ".venv" / "Lib" / "site-packages" / "pkg_resources" / "tests" / "data" / "my-test-package_unpacked-egg" / "my_test_package-1.0-py3.7.egg"
    if len(str(longest_known)) >= 245:
        raise RuntimeError("解压路径过长，Windows 可能无法安装依赖。请把包含 01-安装部署.cmd 的整个目录移到较短的位置，例如 D:\\MangaText，再运行部署；不需要改系统长路径设置。")
    if not PYTHON.exists():
        if (MODEL / ".venv").exists():
            raise RuntimeError("发现不完整的 .venv。请先将该文件夹改名，然后重试。")
        print("创建独立 Python 环境…", flush=True)
        venv.EnvBuilder(with_pip=True).create(MODEL / ".venv")
    run([PYTHON, "-c", "import sys,struct;assert sys.version_info[:2]==(3,12) and struct.calcsize('P')==8"])
    run([PYTHON, "-m", "pip", "install", "--disable-pip-version-check", "--retries", "3",
         "--no-deps", "torch==2.8.0+cpu", "torchvision==0.23.0+cpu", "--index-url", "https://download.pytorch.org/whl/cpu"])
    run([PYTHON, "-m", "pip", "install", "--disable-pip-version-check", "--retries", "3",
         "-r", MODEL / "requirements-app.txt"])
    run([PYTHON, "-m", "pip", "check"])


def verify_environment():
    if not PYTHON.is_file():
        raise RuntimeError("尚未部署运行环境，请先运行 01-安装部署.cmd。")
    run([PYTHON, ROOT / "check_deployment.py"], local=True)


def install_plugin():
    package = prepare()
    installer = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Common Files" / "Adobe" / "Adobe Desktop Common" / "RemoteComponents" / "UPI" / "UnifiedPluginInstallerAgent" / "UnifiedPluginInstallerAgent.exe"
    if not installer.is_file():
        raise RuntimeError("未找到 Adobe 安装器。请安装或修复 Creative Cloud Desktop，然后双击生成的 .ccx 安装包。")
    run([installer, "/install", package])
    print("安装器执行完毕。请在 Creative Cloud 中确认插件已安装；打开 Photoshop 的“增效工具”菜单。", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", nargs="?", choices=["deploy", "check", "prepare", "install"], default="deploy")
    options = parser.parse_args()
    check_platform()
    verify_payload()
    if options.mode == "deploy":
        ensure_weights()
        install_environment()
        prepare()
        verify_environment()
        print("\n部署检查通过。接下来运行 03-安装PS插件.cmd，或双击新生成的漫画文字选区.ccx。", flush=True)
    elif options.mode == "check":
        verify_environment()
    elif options.mode == "prepare":
        prepare()
    else:
        verify_environment()
        install_plugin()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        with (ROOT / "deploy.log").open("a", encoding="utf-8") as log:
            log.write(traceback.format_exc())
        print("\n错误：" + str(error), file=sys.stderr, flush=True)
        raise SystemExit(1)
