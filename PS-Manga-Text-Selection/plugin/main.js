"use strict";
const {entrypoints} = require("uxp");
let panelRoot = null;
let busy = false;
let busyAction = "";
const VERSION = "1.0.0";

function element(id) {
  return panelRoot ? panelRoot.querySelector("#" + id) : null;
}

function status(text) {
  console.log("[MangaSelection " + VERSION + "] " + text);
  const label = element("status");
  if (label) label.textContent = text;
  const button = element("selectButton");
  if (busyAction === "detect" && button) button.textContent = /启动|加载/.test(text) ? "正在启动模型…" : "正在检测…";
}

function readSettings() {
  const value = (id, fallback) => element(id) ? element(id).value : fallback;
  return {threshold:value("threshold", .5), expand:value("expand", 2), maxSide:value("maxSide", 1600)};
}

function disableButtons(disabled) {
  ["selectButton", "checkButton", "stopButton"].forEach(id => {
    const button = element(id);
    if (button) button.disabled = disabled;
  });
  const mainButton = element("selectButton");
  if (mainButton) mainButton.textContent = disabled && busyAction === "detect" ? "正在检测…" : "选中区域内文字";
  const checkButton = element("checkButton"), stopButton = element("stopButton");
  if (checkButton) checkButton.textContent = disabled && busyAction === "check" ? "正在检查…" : "检查连接";
  if (stopButton) stopButton.textContent = disabled && busyAction === "shutdown" ? "正在关闭…" : "关闭模型";
}

async function run() {
  if (busy) return;
  busy = true;
  busyAction = "detect";
  try {
    status("已收到点击，正在连接模型…");
    disableButtons(true);
    const ps = require("photoshop");
    const selector = require("./selection.js");
    await selector.selectText(ps, fetch, readSettings(), status,
      report => require("./connection.js").ensureModel(fetch, require("uxp").shell, report));
  } catch (error) {
    console.error("[MangaSelection]", error);
    status("错误：" + (error.message || String(error)));
    if (!panelRoot) {
      try { await require("photoshop").app.showAlert(error.message || String(error)); } catch (_) {}
    }
  } finally {
    busy = false;
    busyAction = "";
    disableButtons(false);
  }
}

async function check() {
  if (busy) return;
  busy = true;
  busyAction = "check";
  try {
    disableButtons(true);
    status("正在检查模型连接…");
    await require("./connection.js").checkModel(fetch);
    status("模型连接正常，退出 PS 后会自动关闭。");
  } catch (error) {
    status(error.code === "MODEL_UNAVAILABLE"
      ? "模型未运行。点击“选中区域内文字”会自动启动模型。"
      : "错误：" + (error.message || String(error)));
  } finally {
    busy = false;
    busyAction = "";
    disableButtons(false);
  }
}

async function stop() {
  if (busy) return;
  busy = true;
  busyAction = "shutdown";
  try {
    disableButtons(true);
    await require("./connection.js").stopModel(fetch, status);
  } catch (error) { status("错误：" + (error.message || String(error))); }
  finally {
    busy = false;
    busyAction = "";
    disableButtons(false);
  }
}

function mount(rootNode) {
  panelRoot = rootNode;
  rootNode.style.height = "100%";
  rootNode.style.overflow = "auto";
  rootNode.innerHTML = `<div style="padding:12px;background-color:#3c3c3c;color:#eeeeee;">
    <sp-heading size="S" style="margin:0 0 6px 0;">漫画文字选区</sp-heading>
    <sp-body size="S" style="display:block;margin:0;color:#eeeeee;">先建立选区，再检测其中的文字。</sp-body>
    <div id="status" style="font-size:12px;line-height:16px;margin:8px 0;padding:8px;background-color:#282828;color:#f4f4f4;white-space:pre-wrap;"></div>
    <sp-button id="selectButton" variant="cta" style="display:block;width:100%;margin:0;">选中区域内文字</sp-button>
    <div style="display:flex;margin-top:6px;">
      <sp-button id="checkButton" variant="secondary" style="display:block;flex:1;">检查连接</sp-button>
      <sp-button id="stopButton" variant="secondary" style="display:block;flex:1;margin-left:6px;">关闭模型</sp-button>
    </div>
    <div style="display:flex;align-items:center;margin-top:10px;">
      <sp-body size="S" style="width:118px;margin:0;color:#eeeeee;">文字阈值 0.1–0.9</sp-body>
      <sp-textfield id="threshold" type="number" value="0.5" style="width:110px;flex:1;"></sp-textfield>
    </div>
    <div style="display:flex;align-items:center;margin-top:6px;">
      <sp-body size="S" style="width:118px;margin:0;color:#eeeeee;">扩展像素 0–10</sp-body>
      <sp-textfield id="expand" type="number" value="2" style="width:110px;flex:1;"></sp-textfield>
    </div>
    <div style="display:flex;align-items:center;margin-top:6px;">
      <sp-body size="S" style="width:118px;margin:0;color:#eeeeee;">长边 512–2560</sp-body>
      <sp-textfield id="maxSide" type="number" value="1600" style="width:110px;flex:1;"></sp-textfield>
    </div>
    <sp-body size="S" style="display:block;margin-top:8px;color:#cccccc;">退出 PS 后自动关闭模型。Ctrl+Z 撤销选区。</sp-body>
  </div>`;
  element("selectButton").addEventListener("click", run);
  element("checkButton").addEventListener("click", check);
  element("stopButton").addEventListener("click", stop);
  const connection = require("./connection.js");
  status(connection.configured() ? "插件 v" + VERSION + " 已就绪。请先建立选区。"
    : "请先运行分享包的 01-安装部署.cmd，再安装重新生成的插件。");
  connection.registerIfRunning(fetch);
}

entrypoints.setup({
  panels: {mangaTextPanel: {create:mount, show(rootNode) {if (panelRoot !== rootNode || !element("selectButton")) mount(rootNode);}}},
  commands: {selectMangaText: run}
});
