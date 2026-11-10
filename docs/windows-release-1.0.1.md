# AutoDeliver 1.0.1 Windows 发行验证

验证日期：2026-11-10。Windows x64。

构建及验证证据目录：`build/verification/v1.0.1/`。旧版本及本地测试版构建均保留。

更新内容见[发行说明](release-notes-1.0.1.md)，使用方式见[README](../README.md)。

## 交付文件

| 文件 | 大小（字节） | 用途 |
| --- | ---: | --- |
| `release/AutoDeliver-Setup-1.0.1-win64.exe` | 70,255,779 | 当前用户安装程序 |
| `release/AutoDeliver-1.0.1-win64-portable.zip` | 89,901,034 | 完整解压后运行 |
| `release/SHA256SUMS.txt` | 203 | 两个发行包的 SHA-256 |
| `dist/1.0.1/AutoDeliver/AutoDeliver.exe` | 16,387,075 | 主程序，依赖完整目录 |
| `dist/1.0.1/AutoDeliver/auto_deliver_worker.exe` | 16,430,998 | 后台任务程序 |

发行目录共 508 个文件、176,351,556 字节。应用元数据、两个 EXE 的文件及产品版本、安装器和安装注册版本均为 1.0.1。安装器沿用 v1.0.0 的 AppId。

```text
F45D1F14E27B76B4C4D482297C6264CF2D2A01CEAC4F569F16554CBA51D0D74E  AutoDeliver-Setup-1.0.1-win64.exe
EBCC3242F9B08A1404D013DD0D96441DF4EBA08B8F6812656CA7AAB9C25AE5B2  AutoDeliver-1.0.1-win64-portable.zip
```

## 实际验证

| 检查 | 结果 |
| --- | --- |
| 全量测试 | 513 项通过，231 个子测试通过 |
| 测试环境隔离 | 启动测试模拟浏览器占用检查，不读取本机真实浏览器状态；占用阻止启动的专项测试仍保留 |
| 敏感数据与差异检查 | 敏感信息扫描、`git diff --check` 通过 |
| 冻结程序 | GUI、worker 在临时工作目录、未设置 AI Key、清理 Python/Conda/Qt 环境且缩减 PATH 后通过离线自检 |
| 浏览器启动 | worker 使用临时资料目录打开本地 `data:` 页面后退出 |
| 界面 | 关于窗口已目视核对，显示版本 1.0.1；主界面及高级设置截图保留 |
| 便携包 | ZIP CRC 正常，508 个文件逐项与构建目录比对 SHA-256 一致 |
| 源码与资源 | 两个 EXE 内各 20 个相关模块编译内容与源码一致；随包 README、免责声明、元数据等资源哈希一致 |
| 私人文件 | 构建目录不含 `.env`、个人简历、画像、投递 CSV 或浏览器资料目录 |
| 安装卸载 | 工作区隔离目录静默安装，校验注册版本 1.0.1、快捷方式和安装后自检；随后成功卸载并清理目录、注册项和快捷方式 |
| 既有数据 | 安装前后 8 个非日志用户数据文件的路径、大小、SHA-256 一致；运行日志不纳入对比 |

首轮测试中 6 项启动单元测试受到本机项目浏览器占用状态影响；补齐这些单元测试的浏览器检查模拟后，全量通过。应用中的占用保护逻辑未改动。

证据包括 `pytest.log`、`pyinstaller.log`、`installer-build.log`、`offline-self-check-no-key*.json`、界面截图、`artifact-check.json` 和 `installer-verification/`。发布前源文件备份位于 `source-before-release/`，此前安装验证证据位于 `previous-installer-evidence/`。

## 范围与限制

验证没有登录招聘账号、访问真实岗位、调用外部 AI 或执行投递。智联仍为实验接入，猎聘自动化继续暂停。上述结果验证本机打包与离线功能，不代表真实平台可用性、匹配质量或投递成功率。

EXE 与安装包尚未代码签名，未在另一台全新 Windows 电脑上测试。安装器使用相同 AppId，但本次没有在真实 v1.0.0 安装目录执行覆盖升级；实际安装测试使用独立目录并确认用户数据保留。
