# 让 agent 帮你部署

先把整个压缩包解压，再让 agent 获得这个文件夹的读写和运行权限。只发截图或模型网页链接不够。可以把以下提示词复制给 Codex 或其他能访问本机文件、执行命令的 agent；网页聊天中的普通助手若没有电脑执行权限，只能指导你操作。

把 `[解压目录的绝对路径]` 换成你自己电脑的路径，然后复制整个提示词。

## 完整部署提示词

```text
请在我的电脑上部署这个“漫画文字选区”分享包，并安装 Photoshop 插件。
解压目录：[解压目录的绝对路径]

请直接完成部署和验证，不要只给我计划或下载链接。先读根目录说明及教程/01-手动部署与使用.md，查看 deploy.py、prepare_plugin.py、check_deployment.py 和包内源码。

目标：我在 Photoshop 中建立矩形或套索选区，点击“选中区域内文字”，插件选中该范围内的文字笔画像素。保留自动启动模型、关闭模型按钮和退出所有 Photoshop 进程后自动关闭功能。

请依次完成：
1. 检查操作系统、CPU、内存、磁盘空间、Photoshop 版本和 Creative Cloud 安装器。本包是 Windows x64、Photoshop 25.0+、Python 3.12 x64 的 CPU 方案。若是 macOS、Linux 或 Windows ARM，请先明确需要适配的部分，不能直接宣称兼容。
2. 权重不随包分发。deploy.py deploy 会按 model-source.json 从原作者仓库的固定 revision 下载 Manga-Text-Segmentation/model.pth 并校验 SHA256；不要换用其他来源或其他版本的权重。对应摘要为 a0a895dc385608554a81ca765b0c62d654462c2bac661abdff63634985ab37fc，来源是 https://huggingface.co/a-b-c-x-y-z/Manga-Text-Segmentation-2025 ，固定 revision 为 2dde9eeb03e81692c1562059451c2bf30e1a13da。
3. 找到完整的 Python 3.12 x64。可以使用 agent 自带的完整运行时，但要确认 venv、pip、pythonw.exe 可用；没有时帮我安装官方运行时。不要覆盖其他项目的 Python 环境。
4. 首选用该 Python 执行根目录 deploy.py deploy。它会新建独立 .venv，按 requirements-lock.txt 安装 CPU 版 torch 2.8.0+cpu / torchvision 0.23.0+cpu 等依赖，再生成本机插件并做真实模型检查。不要直接搬别人的 .venv，也不要随机升级模型依赖。
5. 网络安装失败时查看具体错误和环境代理，重试官方 PyPI / PyTorch CPU 源。不改全局安全设置。模型运行仅用本机地址，不上传我的漫画到外部服务。
6. 确认生成的 plugin/service-config.json 指向我的实际 start-hidden.vbs，且控制许可在我本机新生成，插件与模型一致。不要保留发送者的用户名路径或旧控制许可。安装前必须重新生成 .ccx；模板不能当作已部署安装包。
7. 保存已有文档并退出 Photoshop 后，安装 PS-Manga-Text-Selection/漫画文字选区.ccx。可使用 Adobe 的 UnifiedPluginInstallerAgent，或指导我在 Creative Cloud 完成安装。旧版本有冲突时只处理本插件，不删除其他插件。正常 CCX 安装不需要开启开发者模式。
8. 运行 deploy.py check（或 check_deployment.py）验证真实权重、依赖、掩膜尺寸、控制接口和本机路径。然后打开 PS 面板，测试建立选区、自动启动、检测、关闭按钮、关闭后再次启动，以及退出 PS 后后台进程是否自行结束。只改测试图片的选区；不要直接删除或填充原图像素。
9. 首次 Adobe 启动脚本授权弹窗由我自己点击允许，可提醒我勾选“记住我的选择”；不要绕过权限或系统安全提示。如果无法直接操作 PS，明确哪些后端检查通过，给我简短的 PS 测试步骤，不能声称未完成的原生测试已通过。
10. 结束后告诉我部署位置、插件版本、测试结果、如何启动/关闭、日志位置及实际限制。不要留下一份无人使用的测试模型进程；如我已退出 PS，验证模型也退出。

使用默认阈值 0.5、扩展 2、长边 1600。性能不足先缩小选区或长边，不要未经测试就切换 GPU / CUDA 后端。
```

## 已部署但不能连接时

```text
我已部署漫画文字选区分享包，但 Photoshop 插件无法连接。
解压部署目录：[解压目录的绝对路径]

请先诊断并修复，不要直接反复重装。检查 model.pth、.venv 是否完整、模型进程、7860 端口、/ps/v1/health、launch-error.log、server-error.log，以及插件安装版本。注意本机服务监听 127.0.0.1 和 ::1（仅回环地址），PS 插件通过 localhost:7860 连接，manifest 必须声明对应 localhost 域名。
检查 service-config.json 是否指向当前目录，控制许可是否匹配。如果文件夹移动过，运行 prepare_plugin.py 重新生成 CCX，再重新安装。模型加载失败时先读错误；代理可能使 Gradio 初始化失败，启动器应只在模型子进程中清除代理环境，不修改全局系统代理。
修复后验证真实检测、关闭按钮和 PS 退出后的自动关闭。首次启动授权由我自己操作。请区分已经完成的后端测试与实际 Photoshop 测试。
```

## 想改成其他系统或显卡时

```text
我想适配这个漫画文字选区分享包。
解压目录：[解压目录的绝对路径]
我的系统和显卡：[填写系统、CPU、内存、显卡、Photoshop 版本]

先检查源码和官方兼容信息，确认 PyTorch、Python、Photoshop UXP 和模型架构是否支持这套设备。当前包使用 Windows VBS 隐藏启动器、Windows 进程监控和 CPU 推理；需要逐项适配，不能只改一个启动命令就宣称完成。
保留原模型权重、原尺寸坐标、原选区交集、羽化限制、只改选区以及关闭/退出管理。先保留能工作的 CPU 配置，另建隔离环境测试新方案。完成后重新生成本机 CCX，并说明实际测试结果和速度，不用推测值冒充实测。
```
