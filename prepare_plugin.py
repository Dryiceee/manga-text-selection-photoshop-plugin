"""Generate a Photoshop package bound to the recipient's model folder."""
import json
from pathlib import Path
import re
import secrets
import zipfile

ROOT = Path(__file__).resolve().parent
MODEL = ROOT / "Manga-Text-Segmentation"
PLUGIN = ROOT / "PS-Manga-Text-Selection"


def prepare():
    launcher = MODEL / "start-hidden.vbs"
    if not launcher.is_file():
        raise RuntimeError("缺少模型启动脚本，请完整解压分享包。")
    token_file = MODEL / ".control-token"
    token = token_file.read_text(encoding="ascii").strip() if token_file.exists() else ""
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", token):
        token = secrets.token_urlsafe(32)
        token_file.write_text(token, encoding="ascii")
    source = PLUGIN / "plugin"
    config = {"launcherPath": str(launcher.resolve()), "controlToken": token}
    (source / "service-config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    if not (source / manifest["main"]).is_file():
        raise RuntimeError("插件源码缺少入口文件。")
    destination = PLUGIN / "漫画文字选区.ccx"
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for item in sorted(source.iterdir()):
            if item.is_file() and item.suffix in {".js", ".json"}:
                archive.write(item, item.name)
    with zipfile.ZipFile(destination) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("插件安装包校验失败。")
        saved = json.loads(archive.read("service-config.json"))
        if saved != config:
            raise RuntimeError("插件路径写入失败。")
    print("已生成本机插件安装包：", destination, flush=True)
    print("移动模型文件夹后，请重新生成并重新安装插件。", flush=True)
    return destination


if __name__ == "__main__":
    prepare()
