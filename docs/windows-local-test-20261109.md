# Windows 本地测试版 2026-11-09

构建时间：2026-11-09 19:36（Asia/Shanghai）。由当前工作区源码构建，包含轻量浏览、平台限制停止及岗位范围过滤等尚未发布的改动。

## 运行入口

- 主程序：`dist/local-test-20261109/AutoDeliver/AutoDeliver.exe`
- 便携包：`release/AutoDeliver-local-test-20261109-win64-portable.zip`
- 完整程序目录：508 个文件，共 176,247,633 字节；ZIP 为 89,801,100 字节。

双击主程序即可使用。移动或分发时保留完整 `AutoDeliver` 目录，包括 `auto_deliver_worker.exe` 和 `_internal`。程序自带 Python 运行环境，岗位任务仍需要本机 Chrome 或 Edge。正常运行沿用 `%APPDATA%/AutoDeliver` 中的设置和记录。

本次为独立目录下的本地测试构建，程序版本元数据沿用 1.0.0；以目录及 ZIP 中的 `local-test-20261109` 标识区别于旧发行版。原 v1.0.0 EXE、安装包和远端发行文件没有替换，本次没有制作安装程序或发布到远端。

## 验证结果

- 自动化测试：425 项测试、176 项子测试通过。
- 新增离线自检：可见列表单次滚动与冷却、后台不滚动、429 后停止所有后续请求、面板平台限制状态均通过。
- 冻结 GUI 与后台程序自检均通过，确认运行对象为本次生成的 EXE。
- 清除 Python、Conda、Qt 及模型服务环境变量，将 PATH 缩减为 Windows 系统目录，从隔离工作目录启动通过。
- 后台程序使用临时浏览器目录启动本机 Chrome，打开离线 `data:` 页面并正常退出。
- 已目视检查主界面、高级设置与“关于”窗口截图，作者署名为 Gnahz。
- 敏感信息扫描通过，包内未发现个人配置、简历、画像或投递记录文件名。
- ZIP 内 508 个文件逐一校验大小和 SHA-256，全部与构建目录一致。
- 测试只使用隔离数据目录、模拟请求和离线浏览器页面，没有调用外部 AI 接口或发送真实投递消息。

验证报告、截图、逐文件清单保存在 `build/verification/local-test-20261109/`；构建日志保存在 `build/local-test-20261109/pyinstaller.log`。

## SHA-256

```text
876CBF21D9694918F433A96985A5DB3C4D0D914BCE69132521307AC4893D63A7  AutoDeliver.exe
CF2733CCEE0AE8402C3319B620596D7DEF831D499F8DD09BAFE7657B5EFE3ED3  auto_deliver_worker.exe
BB9EE44AFFD2E1723E1E814284C2428CF1CC72ECCE8A79F9212655BE6988F7B0  AutoDeliver-local-test-20261109-win64-portable.zip
```

## 复现

使用 `requirements-build.txt` 对应环境，目标输出目录应为新的测试目录：

```powershell
python -X utf8 -B -m PyInstaller --noconfirm --distpath dist/local-test-20261109 --workpath build/local-test-20261109/pyinstaller packaging/AutoDeliver.spec
```

对生成的 `AutoDeliver.exe` 执行 `--self-check <报告绝对路径>`，会在临时数据目录中检查 GUI 并启动同目录后台程序的自检。当前构建没有代码签名；以上检查未覆盖其他电脑或平台真实投递结果。
