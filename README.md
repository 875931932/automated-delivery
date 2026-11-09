# AutoDeliver 求职工作台

Windows 桌面求职辅助工具，提供岗位检索、简历与 JD 匹配评估、招呼语起草、投递结果查看和配置管理。

## 作者与反馈

- 作者：**Gnahz**
- 邮箱：[875931932@qq.com](mailto:875931932@qq.com)
- GitHub：[github.com/875931932](https://github.com/875931932)
- Gitee：[yan-ace/automated-delivery](https://gitee.com/yan-ace/automated-delivery)

以上为作者主动公开的项目联系方式。反馈问题时请移除 API Key、登录信息及个人敏感内容。

## 安装与使用

在 Windows 10 1903 或更新版本、Windows 11 的 64 位系统上运行 `release/AutoDeliver-Setup-1.0.0-win64.exe`，按向导安装。安装版自带 Python 运行环境和项目依赖，无需安装 Python 或 Conda。运行岗位任务需要电脑安装 Chrome 或 Edge；如无法自动识别，可在高级设置中指定浏览器路径。

也可解压 `release/AutoDeliver-1.0.0-win64-portable.zip` 后运行其中的 `AutoDeliver.exe`。便携版需要保留整个解压目录，包含 `_internal` 和 `auto_deliver_worker.exe`；用户数据仍使用下述 AppData 路径。

首次使用时，在求职设置中填写 AI 接口、选择 Markdown/TXT 简历并设置目标岗位，保存后先用试运行检查评分与招呼语。正式投递可能按配置自动发送消息，请先阅读[使用说明与免责声明](DISCLAIMER.md)。应用侧栏底部的“关于”窗口也提供作者信息及完整说明。

## 数据位置

- 配置：`%APPDATA%\AutoDeliver\.env`
- 投递结果：`%APPDATA%\AutoDeliver\deliver_results.csv`
- 每日记录：`%APPDATA%\AutoDeliver\deliver_log.json`
- 候选人画像、摘要和访谈缓存：`%APPDATA%\AutoDeliver`
- 浏览器登录信息：`%USERPROFILE%\.boss-zhipin-scraper\chrome-profile`

安装和卸载默认保留上述用户数据。简历可以位于用户自行选择的路径。安装包不携带开发者的简历、密钥、画像、投递记录或浏览器登录数据。

## 源码运行与构建

使用 Python 3.11，在独立环境中安装 `requirements.txt` 后运行 `python desktop_panel.py`。本机现有无控制台启动方式为 `启动面板.vbs`，可通过 `AUTODELIVER_PYTHONW` 指定解释器。

安装 `requirements-build.txt` 和 Inno Setup 6.7.4 后运行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_windows.ps1 -Python python -Iscc "安装目录\ISCC.exe"
```

构建配置位于 `packaging/`，EXE 输出到 `dist/AutoDeliver/`，安装包与便携压缩包输出到 `release/`。构建使用资源白名单，不会打入整个项目目录。

离线自检可验证界面、资源、AI 客户端初始化、结果写入与后台程序，不发送真实消息、不调用外部 AI：

```powershell
.\dist\AutoDeliver\AutoDeliver.exe --self-check "完整路径\release-check.json"
```

第三方组件说明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。本项目的免责声明不等同于开源许可证，也不替代第三方组件各自的许可条款。
