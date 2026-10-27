"""Local manga text segmentation; model architecture follows upstream inference.py."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")
os.environ.setdefault("GRADIO_TEMP_DIR", str(ROOT / "cache"))
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1,::1")

import time
import threading
import json
import re
import uuid
import zipfile
from datetime import datetime, timezone, timedelta
import cv2
import gradio as gr
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import segmentation_models_pytorch as smp
from PIL import Image, ImageOps

torch.set_num_threads(min(8, os.cpu_count() or 4))
MODEL = None
LOCK = threading.Lock()


def convert_batchnorm_to_groupnorm(module):
    for name, child in module.named_children():
        if isinstance(child, nn.BatchNorm2d):
            channels = child.num_features
            groups = next((i for i in range(min(channels, 8), 0, -1) if channels % i == 0), 1)
            setattr(module, name, nn.GroupNorm(groups, channels))
        else:
            convert_batchnorm_to_groupnorm(child)


def load_model():
    global MODEL
    if MODEL is None:
        path = ROOT / "model.pth"
        if not path.is_file():
            raise FileNotFoundError(f"缺少真实模型权重：{path}")
        model = smp.UnetPlusPlus(
            encoder_name="tu-efficientnetv2_rw_m", encoder_weights=None,
            in_channels=3, classes=1, activation=None, decoder_attention_type="scse",
        )
        convert_batchnorm_to_groupnorm(model.decoder)
        model.load_state_dict(torch.load(path, map_location="cpu", weights_only=True), strict=True)
        model.eval()
        MODEL = model
    return MODEL


def predict(image, max_side, horizontal=False, vertical=False, progress=None):
    start = time.perf_counter()
    image = np.asarray(ImageOps.exif_transpose(image).convert("RGB"))
    h, w = image.shape[:2]
    if h * w > 60_000_000:
        raise gr.Error("图片超过 6000 万像素，请先裁剪或缩小。")
    scale = min(1.0, int(max_side) / max(h, w))
    small = cv2.resize(image, (max(1, round(w * scale)), max(1, round(h * scale))), interpolation=cv2.INTER_AREA) if scale < 1 else image
    sh, sw = small.shape[:2]
    # Equivalent to the ImageNet A.Normalize + ToTensorV2 used upstream.
    data = (small.astype(np.float32) / 255.0 - np.array([.485, .456, .406], dtype=np.float32)) / np.array([.229, .224, .225], dtype=np.float32)
    tensor = torch.from_numpy(data.transpose(2, 0, 1).copy()).unsqueeze(0)
    tensor = F.pad(tensor, (0, (-sw) % 32, 0, (-sh) % 32))
    with LOCK, torch.inference_mode():
        net = load_model()
        if progress:
            progress(.1, desc="检测文字中…")
        probabilities = net(tensor).sigmoid()
        count = 1
        for enabled, dimension in [(horizontal, 3), (vertical, 2)]:
            if enabled:
                probabilities += net(tensor.flip([dimension])).sigmoid().flip([dimension])
                count += 1
        prob = (probabilities / count)[0, 0, :sh, :sw].numpy().copy()
    if scale < 1:
        prob = cv2.resize(prob, (w, h), interpolation=cv2.INTER_LINEAR)
    seconds = time.perf_counter() - start
    status = f"CPU · 输入 {w}×{h} · 推理 {sw}×{sh} · 耗时 {seconds:.2f} 秒。"
    if scale < 1:
        status += " 图片已缩小后检测，结果已还原到原图尺寸；小字漏检时可提高推理长边。"
    return (image, prob), status


def render(state, threshold, expansion, fill_holes, gap, alpha):
    if state is None:
        return None, None, None
    image, probabilities = state
    mask = (probabilities > threshold).astype(np.uint8) * 255
    if gap > 0:
        size = int(gap) | 1
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size)))
    if fill_holes:
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(mask, contours, -1, 255, -1)
    overlay = image.copy()
    selected = mask > 0
    overlay[selected] = (image[selected].astype(np.float32) * (1-alpha) + np.array([255, 0, 0]) * alpha).astype(np.uint8)
    expanded = cv2.dilate(mask, np.ones((3, 3), np.uint8), iterations=int(expansion)) if expansion else mask
    cleaned = image.copy()
    cleaned[expanded > 0] = 255
    return overlay, mask, cleaned


def run(image, max_side, horizontal, vertical, threshold, expansion, fill_holes, gap, alpha, progress=gr.Progress()):
    if image is None:
        raise gr.Error("请先上传一张漫画图片。")
    state, status = predict(image, max_side, horizontal, vertical, progress)
    return state, *render(state, threshold, expansion, fill_holes, gap, alpha), status


def run_batch(files, max_side, threshold, expansion, fill_holes, gap, horizontal, vertical, progress=gr.Progress()):
    if not files:
        raise gr.Error("请先选择多张漫画图片。")
    started = time.perf_counter()
    stamp = datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d_%H%M%S")
    folder = ROOT / "results" / f"{stamp}_{uuid.uuid4().hex[:6]}"
    folder.mkdir(parents=True)
    previews, records = [], []
    settings = dict(max_side=int(max_side), threshold=threshold, expansion=int(expansion), fill_holes=fill_holes, gap=int(gap), horizontal=horizontal, vertical=vertical)
    for index, filename in enumerate(files, 1):
        path = Path(filename)
        progress((index-1, len(files)), desc=f"处理 {index}/{len(files)}：{path.name}")
        try:
            with Image.open(path) as source:
                state, status = predict(source, max_side, horizontal, vertical)
            overlay, mask, cleaned = render(state, threshold, expansion, fill_holes, gap, .4)
            stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", path.stem)[:100]
            prefix = f"{index:04d}_{stem}"
            names = {}
            for kind, result in [("masks", mask), ("cleaned", cleaned), ("overlays", overlay)]:
                destination = folder / kind / f"{prefix}.png"
                destination.parent.mkdir(exist_ok=True)
                Image.fromarray(result).save(destination)
                names[kind] = destination.relative_to(folder).as_posix()
            if len(previews) < 8:
                preview = Image.fromarray(mask)
                preview.thumbnail((512, 512))
                previews.append((preview, path.name))
            records.append(dict(input=path.name, success=True, outputs=names, status=status))
            del state, overlay, mask, cleaned
        except Exception as error:
            records.append(dict(input=path.name, success=False, error=str(error)))
    (folder / "report.json").write_text(json.dumps(dict(settings=settings, files=records), ensure_ascii=False, indent=2), encoding="utf-8")
    archive = folder / "results.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as bundle:
        for path in sorted(folder.rglob("*")):
            if path.is_file() and path != archive:
                bundle.write(path, path.relative_to(folder).as_posix())
    succeeded = sum(record["success"] for record in records)
    summary = f"完成：成功 {succeeded}/{len(files)} 张，耗时 {time.perf_counter()-started:.2f} 秒。\n保存目录：{folder}\nZIP 内 masks 为文字掩膜，cleaned 为涂白图片，overlays 为检测标记。"
    failures = [record for record in records if not record["success"]]
    if failures:
        summary += "\n失败文件：\n" + "\n".join(f"{record['input']}：{record['error']}" for record in failures)
    progress(1, desc="批量处理完成")
    return str(archive), previews, summary


def build_ui():
    with gr.Blocks(title="漫画文字检测与去字", theme=gr.themes.Soft()) as ui:
        gr.Markdown("# 漫画文字检测与去字\n上传漫画图片，检测文字像素并生成掩膜。**去字方式是涂白，不会修复背景，也不负责识字或翻译。** 图片在本机处理。")
        with gr.Tabs():
            with gr.Tab("单张处理"):
                state = gr.State(None)
                with gr.Row():
                    with gr.Column(scale=1):
                        image = gr.Image(label="上传漫画图片", type="pil", image_mode="RGB", height=450, sources=["upload", "clipboard"])
                        max_side = gr.Slider(512, 2560, value=1600, step=128, label="推理长边上限（越大越慢，小字更清楚）")
                        button = gr.Button("开始检测", variant="primary")
                        with gr.Accordion("检测与去字设置", open=False):
                            threshold = gr.Slider(.1, .9, value=.5, step=.05, label="文字概率阈值（降低可检出更多文字）")
                            expansion = gr.Slider(0, 10, value=2, step=1, label="涂白扩张像素")
                            fill_holes = gr.Checkbox(False, label="填满文字内部孔洞")
                            gap = gr.Slider(0, 10, value=0, step=1, label="连接文字小间隙")
                            alpha = gr.Slider(.1, 1, value=.4, step=.1, label="红色标记透明度")
                            horizontal = gr.Checkbox(False, label="水平翻转增强（额外推理一次）")
                            vertical = gr.Checkbox(False, label="垂直翻转增强（额外推理一次）")
                    with gr.Column(scale=2):
                        status = gr.Textbox(label="运行信息", interactive=False, value="模型已载入 · CPU · 等待图片")
                        with gr.Tabs():
                            with gr.Tab("文字检测标记"):
                                overlay = gr.Image(label="红色为文字", format="png", height=650)
                            with gr.Tab("黑白文字掩膜"):
                                mask = gr.Image(label="白色为文字像素", format="png", height=650)
                            with gr.Tab("涂白后的图片"):
                                cleaned = gr.Image(label="去字结果", format="png", height=650)
                        gr.Markdown("各结果右上角可下载 PNG。修改阈值和去字设置会更新当前结果，无需重复推理。")
                outputs = [overlay, mask, cleaned]
                controls = [threshold, expansion, fill_holes, gap, alpha]
                button.click(run, [image, max_side, horizontal, vertical, *controls], [state, *outputs, status], api_name="segment", concurrency_limit=1, concurrency_id="model_jobs")
                for control in controls:
                    control.release(render, [state, *controls], outputs, api_name=False) if isinstance(control, gr.Slider) else control.change(render, [state, *controls], outputs, api_name=False)
                image.change(lambda: (None, None, None, None, "等待开始检测"), outputs=[state, *outputs, status], api_name=False)
            with gr.Tab("批量处理"):
                gr.Markdown("一次选择多张图片，逐张处理并保存到本地 results 目录。每张图片保留原图尺寸，ZIP 包含文字掩膜、涂白图和检测标记。")
                batch_files = gr.File(label="选择多张漫画图片（可按 Ctrl 或 Shift 多选）", file_count="multiple", file_types=["image"], type="filepath")
                with gr.Row():
                    batch_side = gr.Slider(512, 2560, value=1600, step=128, label="推理长边上限")
                    batch_threshold = gr.Slider(.1, .9, value=.5, step=.05, label="文字概率阈值")
                with gr.Accordion("批量去字与检测设置", open=False):
                    batch_expansion = gr.Slider(0, 10, value=2, step=1, label="涂白扩张像素")
                    batch_fill = gr.Checkbox(False, label="填满文字内部孔洞")
                    batch_gap = gr.Slider(0, 10, value=0, step=1, label="连接文字小间隙")
                    batch_horizontal = gr.Checkbox(False, label="水平翻转增强")
                    batch_vertical = gr.Checkbox(False, label="垂直翻转增强")
                batch_button = gr.Button("开始批量处理", variant="primary")
                batch_status = gr.Textbox(label="批量处理结果与保存位置", interactive=False, lines=5)
                batch_zip = gr.File(label="下载全部结果 ZIP", interactive=False)
                batch_preview = gr.Gallery(label="文字掩膜预览（最多显示前 8 张，完整结果见 ZIP）", columns=4, height=400, format="png")
                batch_button.click(run_batch, [batch_files, batch_side, batch_threshold, batch_expansion, batch_fill, batch_gap, batch_horizontal, batch_vertical], [batch_zip, batch_preview, batch_status], api_name="segment_batch", concurrency_limit=1, concurrency_id="model_jobs")
    return ui


def loopback_sockets(port):
    """Listen on IPv4 and, when available, IPv6 loopback only."""
    import logging
    import socket
    sockets = []
    for family, host in [(socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")]:
        try:
            sock = socket.socket(family, socket.SOCK_STREAM)
        except OSError:
            continue
        try:
            if family == socket.AF_INET6:
                sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            sock.bind((host, port))
        except OSError:
            sock.close()
            if family == socket.AF_INET:
                raise
            # PS connects to "localhost", which Windows tries as ::1 first; a refused
            # ::1 connection costs about 2 seconds before IPv4 is tried.
            logging.getLogger("uvicorn.error").warning("IPv6 loopback unavailable; localhost connections may be slower.")
            continue
        sock.set_inheritable(False)
        sockets.append(sock)
    return sockets


if __name__ == "__main__":
    print("Loading model weights...", flush=True)
    load_model()
    print("Model loaded successfully (CPU).", flush=True)
    (ROOT / "server.pid").write_text(str(os.getpid()), encoding="ascii")
    from ps_api import create_api
    from model_lifecycle import ModelLifecycle
    import uvicorn
    token = (ROOT / ".control-token").read_text(encoding="ascii").strip()
    lifecycle = ModelLifecycle(token, watch=os.environ.get("MANGA_WATCH_PHOTOSHOP") == "1")
    ui = build_ui().queue(max_size=4, default_concurrency_limit=1)
    service = gr.mount_gradio_app(create_api(predict, lifecycle), ui, path="/")
    server = uvicorn.Server(uvicorn.Config(service, host="127.0.0.1", port=7860))
    lifecycle.start(lambda: setattr(server, "should_exit", True))
    try:
        server.run(sockets=loopback_sockets(7860))
    finally:
        lifecycle.close()
