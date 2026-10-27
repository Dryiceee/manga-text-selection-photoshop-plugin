"""Validate the recipient's environment, local binding, and real model forward pass."""
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import struct
import sys
import zipfile

ROOT = Path(__file__).resolve().parent
MODEL = ROOT / "Manga-Text-Segmentation"
PLUGIN = ROOT / "PS-Manga-Text-Selection"


def main():
    assert sys.version_info[:2] == (3, 12) and struct.calcsize("P") == 8, "需要 Python 3.12 x64"
    assert Path(sys.prefix).resolve() == (MODEL / ".venv").resolve(), "请使用分享包内新建的 .venv 执行检查"
    source = json.loads((MODEL / "model-source.json").read_text(encoding="utf-8"))
    assert (MODEL / "model.pth").is_file(), "缺少模型权重 model.pth，请运行 01-安装部署.cmd 自动下载"
    with (MODEL / "model.pth").open("rb") as weight_file:
        assert hashlib.file_digest(weight_file, "sha256").hexdigest() == source["sha256"], "权重校验失败"
    for line in (MODEL / "requirements-lock.txt").read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        name, expected = line.split("==", 1)
        assert importlib.metadata.version(name) == expected, "依赖版本不匹配：" + name
    config = json.loads((PLUGIN / "plugin" / "service-config.json").read_text(encoding="utf-8"))
    token = (MODEL / ".control-token").read_text(encoding="ascii").strip()
    assert re.fullmatch(r"[A-Za-z0-9_-]{32,128}", token), "控制许可不完整"
    assert config["controlToken"] == token, "插件和模型控制许可不一致"
    assert Path(config["launcherPath"]).resolve() == (MODEL / "start-hidden.vbs").resolve(), "插件仍绑定了其他位置"
    with zipfile.ZipFile(PLUGIN / "漫画文字选区.ccx") as archive:
        assert archive.testzip() is None
        assert json.loads(archive.read("service-config.json")) == config, "请重新生成插件安装包"
    print("环境、权重、本机路径和插件安装包检查通过。", flush=True)
    for name in list(os.environ):
        if name.lower() in {"http_proxy", "https_proxy", "all_proxy"}:
            os.environ.pop(name)
    os.environ["NO_PROXY"] = "localhost,127.0.0.1,::1"
    sys.path.insert(0, str(MODEL))
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
    from fastapi.testclient import TestClient
    from app import load_model, predict
    from model_lifecycle import ModelLifecycle
    from ps_api import create_api
    print("加载真实模型并检测一张合成测试图…", flush=True)
    load_model()
    sample = Image.new("RGB", (512, 256), "white")
    font_file = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "arialbd.ttf"
    font = ImageFont.truetype(str(font_file), 48) if font_file.exists() else ImageFont.load_default(size=48)
    ImageDraw.Draw(sample).text((40, 90), "MANGA 123", font=font, fill="black")
    runtime = ModelLifecycle(token)
    with TestClient(create_api(predict, runtime)) as client:
        health = client.get("/ps/v1/health").json()
        assert health["protocol"] == 1 and health["lifecycle"]
        result = client.post("/ps/v1/segment?width=512&height=256&max_side=512", content=np.asarray(sample).tobytes())
        assert result.status_code == 200, result.text
        mask = np.frombuffer(result.content, np.uint8).reshape(256, 512)
        assert set(np.unique(mask)).issubset({0, 255})
        assert result.headers["X-Mask-Width"] == "512"
        assert client.post("/ps/v1/shutdown").status_code == 403
        headers = {"X-Manga-Control-Token": token}
        assert client.post("/ps/v1/attach", headers=headers).json()["auto_close_on_ps_exit"]
        assert client.post("/ps/v1/shutdown", headers=headers).status_code == 202
        print("真实模型接口检查通过，测试图选中字像素：", np.count_nonzero(mask), flush=True)
    print("这是独立测试，没有启动常驻服务。PS 内的实际选区效果请按教程再测。", flush=True)


if __name__ == "__main__":
    main()
