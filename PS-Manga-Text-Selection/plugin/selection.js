"use strict";

const SERVICE = "http://localhost:7860";
const MAX_PIXELS = 16000000;

function settings(values) {
  const threshold = Number(values.threshold);
  const expand = Number(values.expand);
  const maxSide = Number(values.maxSide);
  if (!Number.isFinite(threshold) || threshold < .1 || threshold > .9) throw new Error("文字概率阈值需为 0.1–0.9。");
  if (!Number.isInteger(expand) || expand < 0 || expand > 10) throw new Error("扩展像素需为 0–10 的整数。");
  if (!Number.isInteger(maxSide) || maxSide < 512 || maxSide > 2560) throw new Error("推理长边需为 512–2560 的整数。");
  return {threshold, expand, maxSide};
}

function clippedBounds(bounds, width, height) {
  if (!bounds) throw new Error("请先在图片上建立选区。");
  const out = {
    left: Math.max(0, Math.floor(bounds.left)), top: Math.max(0, Math.floor(bounds.top)),
    right: Math.min(width, Math.ceil(bounds.right)), bottom: Math.min(height, Math.ceil(bounds.bottom))
  };
  if (out.right <= out.left || out.bottom <= out.top) throw new Error("选区不在画布内。");
  if ((out.right-out.left)*(out.bottom-out.top) > MAX_PIXELS) throw new Error("选区超过 1600 万像素，请缩小选区。");
  return out;
}

function alignSelection(data, metadata, target) {
  const width = target.right-target.left, height = target.bottom-target.top;
  const result = new Uint8Array(width*height);
  const source = metadata.sourceBounds;
  if (metadata.width !== source.right-source.left || metadata.height !== source.bottom-source.top || metadata.components !== 1) {
    throw new Error("Photoshop 返回的选区尺寸不匹配，未修改选区。");
  }
  const divisor = metadata.componentSize === 16 ? 32768 : metadata.componentSize === 32 ? 1 : 255;
  for (let y = 0; y < metadata.height; y++) {
    const dy = y + source.top - target.top;
    if (dy < 0 || dy >= height) continue;
    for (let x = 0; x < metadata.width; x++) {
      const dx = x + source.left - target.left;
      if (dx >= 0 && dx < width) {
        result[dy*width+dx] = Math.max(0, Math.min(255, Math.round(data[y*metadata.width+x]*255/divisor)));
      }
    }
  }
  return result;
}

function intersect(mask, original) {
  if (mask.length !== original.length) throw new Error("模型返回的掩膜尺寸不匹配。");
  const result = new Uint8Array(mask.length);
  let selected = 0;
  for (let i = 0; i < result.length; i++) {
    // Preserve original feathering and exclude every pixel outside the original selection.
    result[i] = Math.round(mask[i]*original[i]/255);
    if (result[i]) selected++;
  }
  return {data: result, selected};
}

async function responseError(response) {
  let detail = "";
  try {
    const data = await response.json();
    detail = typeof data.detail === "string" ? data.detail : "参数或图片数据不正确。";
  } catch (_) {}
  return new Error(`模型服务返回 ${response.status}。${detail}`);
}

async function timedFetch(fetchFn, url, options, timeout = 120000) {
  let timer;
  try {
    return await Promise.race([
      fetchFn(url, options),
      new Promise((_, reject) => { timer = setTimeout(() => {
        const error = new Error("模型响应超时，请稍后重试或缩小选区。");
        error.code = "MODEL_TIMEOUT";
        reject(error);
      }, timeout); })
    ]);
  } finally { clearTimeout(timer); }
}

async function checkConnection(fetchFn, timeout = 5000, quiet = false) {
  let response;
  try { response = await timedFetch(fetchFn, SERVICE+"/ps/v1/health", {}, timeout); }
  catch (error) {
    if (!quiet) console.error("[MangaSelection network]", error);
    const unavailable = new Error("无法连接本地模型：" + (error.message || String(error)));
    unavailable.code = error.code === "MODEL_TIMEOUT" ? "MODEL_CONNECTION_TIMEOUT" : "MODEL_UNAVAILABLE";
    throw unavailable;
  }
  if (!response.ok) throw new Error("模型接口尚未就绪，请更新并重新启动本地模型服务。");
  const data = await response.json();
  if (data.service !== "manga-text-selection" || data.protocol !== 1) throw new Error("本地模型接口版本不匹配。");
  return data;
}

async function capture(ps) {
  return ps.core.executeAsModal(async context => {
    if (!ps.app.documents.length) throw new Error("请先打开一张漫画图片。");
    const doc = ps.app.activeDocument;
    if (doc.quickMaskMode) throw new Error("请先退出快速蒙版模式。");
    const request = clippedBounds(doc.selection.bounds, doc.width, doc.height);
    let pixels, selection;
    try {
      pixels = await ps.imaging.getPixels({
        documentID: doc.id, sourceBounds: request, componentSize: 8,
        colorSpace: "RGB", colorProfile: "sRGB IEC61966-2.1", applyAlpha: true
      });
      const info = pixels.imageData;
      if (!info || info.width <= 0 || info.height <= 0) throw new Error("选区中没有可读取的图像。");
      if (pixels.level !== undefined && pixels.level !== 0) throw new Error("Photoshop 未返回原尺寸像素，未修改选区。");
      const bounds = pixels.sourceBounds;
      if (info.width !== bounds.right-bounds.left || info.height !== bounds.bottom-bounds.top || info.components !== 3 || info.componentSize !== 8) throw new Error("读取的 RGB 图片尺寸或格式不匹配。");
      const rgb = new Uint8Array(await info.getData({chunky: true}));
      selection = await ps.imaging.getSelection({documentID: doc.id, sourceBounds: bounds});
      if (!selection.imageData) throw new Error("无法读取当前选区。");
      const selectionInfo = selection.imageData;
      const original = alignSelection(await selectionInfo.getData({chunky: true}), {
        sourceBounds: selection.sourceBounds, width: selectionInfo.width, height: selectionInfo.height,
        componentSize: selectionInfo.componentSize, components: selectionInfo.components
      }, bounds);
      if (context.isCancelled) throw new Error("操作已取消。");
      // Photoshop Bounds exposes getters; object spread does not copy these coordinates.
      const nativeBounds = doc.selection.bounds;
      const selectionBounds = {left:nativeBounds.left, top:nativeBounds.top, right:nativeBounds.right, bottom:nativeBounds.bottom};
      return {documentID: doc.id, historyID: doc.activeHistoryState.id, selectionBounds, bounds, width: info.width, height: info.height, rgb, original};
    } finally {
      if (pixels && pixels.imageData) pixels.imageData.dispose();
      if (selection && selection.imageData) selection.imageData.dispose();
    }
  }, {commandName: "读取漫画选区"});
}

async function apply(ps, captured, mask) {
  return ps.core.executeAsModal(async context => {
    if (!ps.app.documents.length || ps.app.activeDocument.id !== captured.documentID) throw new Error("当前文档已改变，请返回原文档重新检测。");
    const doc = ps.app.activeDocument;
    if (doc.activeHistoryState.id !== captured.historyID) throw new Error("检测期间图片或选区已改变，请重新检测。");
    const bounds = doc.selection.bounds;
    if (!bounds || ["left", "top", "right", "bottom"].some(key => bounds[key] !== captured.selectionBounds[key])) throw new Error("原选区已改变，请重新检测。");
    let currentSelection, gray, suspension;
    let applied = false;
    try {
      // Check the selection itself as well: some selection changes may not add a history entry.
      currentSelection = await ps.imaging.getSelection({documentID: doc.id, sourceBounds: captured.bounds});
      if (!doc.selection.bounds || !currentSelection.imageData) throw new Error("原选区已改变，请重新检测。");
      const info = currentSelection.imageData;
      const current = alignSelection(await info.getData({chunky:true}), {
        sourceBounds: currentSelection.sourceBounds, width: info.width, height: info.height,
        componentSize: info.componentSize, components: info.components
      }, captured.bounds);
      if (current.some((value, index) => value !== captured.original[index])) throw new Error("原选区已改变，请重新检测。");
      gray = await ps.imaging.createImageDataFromBuffer(mask, {
        width: captured.width, height: captured.height, components: 1,
        colorSpace: "Grayscale", colorProfile: "Gray Gamma 2.2"
      });
      if (context.isCancelled) throw new Error("操作已取消。");
      suspension = await context.hostControl.suspendHistory({documentID: doc.id, name: "选中区域内文字"});
      await ps.imaging.putSelection({
        documentID: doc.id, imageData: gray, replace: true,
        targetBounds: {left: captured.bounds.left, top: captured.bounds.top}, commandName: "选中区域内文字"
      });
      applied = true;
    } finally {
      if (suspension !== undefined) await context.hostControl.resumeHistory(suspension, applied);
      if (currentSelection && currentSelection.imageData) currentSelection.imageData.dispose();
      if (gray) gray.dispose();
    }
  }, {commandName: "选中区域内文字"});
}

async function selectText(ps, fetchFn, values, report = () => {}, connect = () => checkConnection(fetchFn)) {
  const options = settings(values);
  report("正在读取原选区…");
  const captured = await capture(ps);
  report("正在连接本地模型…");
  await connect(report);
  report("正在检测选区内文字…");
  const query = `width=${captured.width}&height=${captured.height}&threshold=${options.threshold}&expand=${options.expand}&max_side=${options.maxSide}`;
  const response = await timedFetch(fetchFn, SERVICE+"/ps/v1/segment?"+query, {
    method: "POST", headers: {"Content-Type": "application/octet-stream"}, body: captured.rgb.buffer
  });
  if (!response.ok) throw await responseError(response);
  if (Number(response.headers.get("X-Mask-Width")) !== captured.width || Number(response.headers.get("X-Mask-Height")) !== captured.height) throw new Error("模型返回的掩膜尺寸不匹配。");
  const result = intersect(new Uint8Array(await response.arrayBuffer()), captured.original);
  if (!result.selected) {
    report("未检测到文字，已保留原选区。可降低阈值后重试。");
    return {selected: 0, applied: false};
  }
  report("正在创建文字选区…");
  await apply(ps, captured, result.data);
  report(`已建立文字选区：${result.selected.toLocaleString()} 个像素。可按 Ctrl+Z 撤销。`);
  return {selected: result.selected, applied: true};
}

module.exports = {SERVICE, timedFetch, settings, clippedBounds, alignSelection, intersect, checkConnection, capture, apply, selectText};
