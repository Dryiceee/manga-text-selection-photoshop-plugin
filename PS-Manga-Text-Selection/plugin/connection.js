"use strict";

const {SERVICE, timedFetch, checkConnection} = require("./selection.js");
const {launcherPath, controlToken} = require("./service-config.json");
let starting = null;
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
function configured() { return Boolean(launcherPath && controlToken); }
function requireConfiguration() {
  if (!configured()) throw new Error("尚未完成本机部署。请先运行 01-安装部署.cmd，再安装新生成的漫画文字选区.ccx。");
}

async function control(fetchFn, action) {
  const response = await timedFetch(fetchFn, SERVICE+"/ps/v1/"+action, {
    method:"POST", headers:{"X-Manga-Control-Token":controlToken}
  }, 5000);
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "模型控制失败，请重新启动模型后重试。");
  return data;
}

async function armAutoClose(fetchFn, health) {
  if (!health.lifecycle) throw new Error("模型服务需要重启才能启用退出 PS 后自动关闭和关闭按钮。");
  const result = await control(fetchFn, "attach");
  if (!result.auto_close_on_ps_exit || result.stopping) throw new Error("模型正在关闭，请稍后重新检测。");
  return {...health, ...result};
}

async function checkModel(fetchFn) {
  requireConfiguration();
  return armAutoClose(fetchFn, await checkConnection(fetchFn));
}

async function registerIfRunning(fetchFn) {
  if (!configured()) return;
  try {
    const health = await checkConnection(fetchFn, 1000, true);
    if (health.lifecycle) await armAutoClose(fetchFn, health);
  } catch (error) {
    // Opening a panel must neither launch a model nor show an offline error.
    if (error.code !== "MODEL_UNAVAILABLE") console.log("[MangaSelection lifecycle]", error.message);
  }
}

async function stopModel(fetchFn, report = () => {}) {
  requireConfiguration();
  let health;
  report("正在确认模型连接…");
  try { health = await checkConnection(fetchFn, 5000, true); }
  catch (error) {
    if (error.code !== "MODEL_UNAVAILABLE") throw error;
    report("未连接到模型，无法确认关闭状态。若模型已停止，下一次检测会自动启动。");
    return;
  }
  if (!health.lifecycle) throw new Error("模型服务需要重启才能使用关闭按钮。");
  report("正在关闭模型…");
  const response = await control(fetchFn, "shutdown");
  if (response.status !== "closing") throw new Error("模型未确认关闭请求，请稍后检查连接。");
  // After an authenticated acknowledgement, the service exits itself. Do not
  // turn the expected loss of its socket into an error or infer exit from a timeout.
  report("模型已确认关闭请求，正在退出。下次检测会自动启动。");
}

async function connectOrStart(fetchFn, shell, report, timing) {
  try { return await armAutoClose(fetchFn, await checkConnection(fetchFn, 5000, true)); }
  catch (error) {
    // A responding but incompatible service must not trigger another process.
    if (error.code !== "MODEL_UNAVAILABLE") throw error;
  }
  report("模型未运行，正在启动本地模型…首次启动请允许 Photoshop 打开启动脚本。");
  let launchError;
  try {
    launchError = await shell.openPath(launcherPath, "启动本机漫画文字模型，加载完成后继续检测当前选区。图片只在本机处理。");
  } catch (error) {
    throw new Error("无法启动本地模型：" + (error.message || String(error)) + "。可手动运行 start-model.cmd 后重试。");
  }
  if (launchError) throw new Error("模型启动未获允许或启动脚本无法打开：" + launchError + "。可手动运行 start-model.cmd 后重试。");

  const startedAt = Date.now();
  const deadline = startedAt + (timing.timeoutMs ?? 120000);
  while (Date.now() < deadline) {
    report(`正在加载本地模型…已等待 ${Math.floor((Date.now()-startedAt)/1000)} 秒。`);
    try {
      // A fresh "localhost" connection can take about 2 seconds on Windows, so a
      // short per-poll timeout would keep failing after the model is ready.
      const health = await checkConnection(fetchFn, Math.min(timing.probeMs ?? 5000, Math.max(1, deadline-Date.now())), true);
      const attached = await armAutoClose(fetchFn, health);
      report("模型已就绪，继续检测…");
      return attached;
    } catch (error) {
      if (!["MODEL_UNAVAILABLE", "MODEL_CONNECTION_TIMEOUT"].includes(error.code)) throw error;
    }
    await sleep(Math.min(timing.pollMs ?? 1000, Math.max(0, deadline-Date.now())));
  }
  throw new Error("模型启动超时。请查看模型文件夹中的 launch-error.log 和 server-error.log，或运行 start-model.cmd 后重试。");
}

function ensureModel(fetchFn, shell, report = () => {}, timing = {}) {
  requireConfiguration();
  if (!starting) {
    starting = connectOrStart(fetchFn, shell, report, timing).finally(() => {starting = null;});
  }
  return starting;
}

module.exports = {configured, ensureModel, checkModel, registerIfRunning, stopModel};
