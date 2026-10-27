"""Binary localhost bridge for Photoshop UXP; no document/file access."""
import time
import secrets

import cv2
import numpy as np
from PIL import Image
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool

MAX_PIXELS = 16_000_000


def create_api(predictor, lifecycle=None):
    service = FastAPI(title="Manga text selection bridge")
    service.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-Manga-Control-Token"], expose_headers=["X-Mask-Width", "X-Mask-Height", "X-Inference-Seconds", "X-Selected-Pixels"],
    )

    @service.get("/ps/v1/health")
    async def health():
        return dict(service="manga-text-selection", protocol=1, device="cpu", max_pixels=MAX_PIXELS,
                    lifecycle=lifecycle is not None, **(lifecycle.state() if lifecycle else {}))

    def authorize_control(request):
        if lifecycle is None:
            raise HTTPException(503, "模型服务需要重启才能启用关闭功能。")
        supplied = request.headers.get("X-Manga-Control-Token", "")
        if not supplied or not secrets.compare_digest(supplied.encode("utf-8"), lifecycle.token.encode("ascii")):
            raise HTTPException(403, "模型控制许可不匹配，请重新安装当前插件。")

    @service.post("/ps/v1/attach")
    async def attach(request: Request):
        authorize_control(request)
        if not lifecycle.attach():
            raise HTTPException(503, "模型正在关闭，请稍后重新检测。")
        return lifecycle.state()

    @service.post("/ps/v1/shutdown", status_code=202)
    async def shutdown(request: Request):
        authorize_control(request)
        lifecycle.request_shutdown("Plugin close-model button")
        return {"status": "closing"}

    @service.post("/ps/v1/segment")
    async def segment(
        request: Request, width: int = Query(ge=1, le=16000), height: int = Query(ge=1, le=16000),
        threshold: float = Query(default=.5, ge=.1, le=.9), expand: int = Query(default=2, ge=0, le=10),
        max_side: int = Query(default=1600, ge=512, le=2560),
    ):
        if lifecycle and lifecycle.state()["stopping"]:
            raise HTTPException(503, "模型正在关闭，请稍后重新检测。")
        if width * height > MAX_PIXELS:
            raise HTTPException(413, "选区超过 1600 万像素，请缩小选区。")
        expected = width * height * 3
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > expected:
                raise HTTPException(400, "RGB 数据长度超过图片尺寸。")
            body.extend(chunk)
        if len(body) != expected:
            raise HTTPException(400, "RGB 数据长度与图片尺寸不一致。")

        def infer():
            started = time.perf_counter()
            rgb = np.frombuffer(body, dtype=np.uint8).reshape(height, width, 3)
            state, _ = predictor(Image.fromarray(rgb), max_side)
            mask = (state[1] > threshold).astype(np.uint8) * 255
            if expand:
                mask = cv2.dilate(mask, np.ones((3, 3), np.uint8), iterations=expand)
            return mask.tobytes(), int(np.count_nonzero(mask)), time.perf_counter() - started

        data, selected, seconds = await run_in_threadpool(infer)
        return Response(data, media_type="application/octet-stream", headers={
            "X-Mask-Width": str(width), "X-Mask-Height": str(height),
            "X-Selected-Pixels": str(selected), "X-Inference-Seconds": f"{seconds:.3f}",
            "Cache-Control": "no-store",
        })

    return service
