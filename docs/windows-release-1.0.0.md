# AutoDeliver 1.0.0 Windows 发行验证

验证日期：2026-11-09。构建目标为 Windows 10 1903 及以上、Windows 11 x64。

## 交付文件

| 文件 | 大小（字节） | 用途 |
| --- | ---: | --- |
| `release/AutoDeliver-Setup-1.0.0-win64.exe` | 70,151,225 | 当前用户安装程序，创建开始菜单入口并提供卸载 |
| `release/AutoDeliver-1.0.0-win64-portable.zip` | 89,783,137 | 完整解压后运行 `AutoDeliver/AutoDeliver.exe` |
| `dist/AutoDeliver/AutoDeliver.exe` | 见运行目录 | 本地已解包的主程序，依赖同目录后台程序及 `_internal` |

两种发行形式均自带 Python 运行环境；岗位任务需要电脑安装 Chrome 或 Edge。便携版的数据同样保存在 `%APPDATA%/AutoDeliver`。

SHA-256：

```text
7354628B1D22305333E42BF5E4E86617053E965E134FD80407816CF7533B0A7A  AutoDeliver-Setup-1.0.0-win64.exe
55F3AA12665681D1EB39C352EB7EB541D2F90E12CC5E8649A768743E4F391BC9  AutoDeliver-1.0.0-win64-portable.zip
```

## 作者与说明

作者署名为 Gnahz。公开邮箱与 GitHub 使用作者本次提供的信息，Gitee 使用现有项目仓库地址，统一保存在 `author_info.json`。

应用侧栏的“关于”窗口提供可点击联系方式及完整免责声明，安装向导在安装前展示免责声明。随包附带 `README.md`、`DISCLAIMER.md`、`THIRD_PARTY_NOTICES.md` 及第三方许可文本。

## 实际验证

| 检查 | 结果与证据 |
| --- | --- |
| 全量自动化测试 | `402 passed, 137 subtests passed` |
| 源码差异格式 | `git diff --check` 通过 |
| 敏感信息扫描 | `scripts/check_sensitive_data.py` 通过；公开作者邮箱仅在指定文件中放行 |
| 冻结程序自检 | `build/verification/package-check.json`、`package-check-worker.json` 均通过 |
| 界面目视检查 | 主界面及“关于”窗口原生截图已检查，中文和作者链接可读 |
| 浏览器启动 | 后台程序通过临时用户目录启动本机 Chrome，打开本地 `data:` 页面并退出 |
| 实际安装与卸载 | `build/verification/installer-check.json` 通过；独立目录安装、开始菜单入口、作者元数据、安装后自检和卸载均正常 |
| 用户数据保留 | 安装测试前后 5 个数据文件的路径、大小和 SHA-256 一致；排除正在写入的 `*.log`、`*.log.*` 运行日志 |
| 独立运行环境 | 清除 Python/Conda 相关环境变量、将 PATH 缩减为 Windows 系统路径，从临时工作目录启动通过；见 `isolated-runtime-check.json` |
| 便携 ZIP 完整性 | ZIP 内 508 个文件逐一与 `dist/AutoDeliver` 比对 SHA-256，全部一致 |
| 发行内容 | 共 508 个文件，176,223,710 字节；资源白名单不包含个人简历、`.env`、画像、投递记录或浏览器登录目录 |

安装验证结束后，测试安装目录、测试创建的开始菜单入口及卸载注册项均已移除。既有运行中的源码面板保持运行。

自检使用隔离数据目录和本地页面，没有调用外部 AI 接口，也没有发送真实投递消息。以上结果不代表真实岗位匹配质量或平台投递成功率。

## 工作区整理

旧截图、网页样例、历史配置及中间数据已归档到：

```text
F:\实习准备\AutoDeliver-archive-20261109-155658
```

归档清单 `manifest.json` 中的 82 个文件已重新核对大小和 SHA-256，全部一致。当前配置仍引用的根目录 `resume.md` 保留在原处，未加入发行包。构建及测试缓存另外移入上述归档目录的 `build-intermediates-20261109` 子目录；这部分不计入原清单的 82 个文件。工作区保留 `build/verification` 中的日志、报告和截图作为验证证据。

## 复现

在安装了 `requirements-build.txt` 依赖的 Python 环境与 Inno Setup 6.7.4 下构建：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_windows.ps1 -Python python -Iscc "Inno Setup 安装目录\ISCC.exe"
```

执行安装验证：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/verify_windows_release.ps1
```

安装验证脚本在发现既有安装或目标目录时会停止，避免覆盖真实安装；测试完成后卸载本次测试副本。冻结程序的独立自检方式见根目录 README。

## 已知限制

- 安装包和应用 EXE 尚未进行代码签名，Windows 可能显示“未知发布者”或信誉提示。
- 已在本机进行安装和独立环境验证，尚未在另一台全新 Windows 电脑上测试。
- 构建排除了 Conda 中与 Windows 系统 ICU 不兼容的 DLL，由系统提供 Qt 所需的 ICU API；最低系统版本设置为 Windows 10 1903。
