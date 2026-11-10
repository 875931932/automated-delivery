# Windows 本地测试版：搜索与结果管理

日期：2026-11-10。基于当前源码构建，版本元数据沿用 1.0.0，通过 `local-test-20261110-search-results` 文件名区分本次构建；旧构建保留。

## 本次包含

- 多关键词搜索、每个关键词的搜索统计及重复页面停止机制。
- 投递结果中的岗位链接使用项目浏览器及对应平台的登录配置打开。
- 结果筛选、多选和删除管理，删除列位于最右侧。
- 智联招聘为实验性接入；猎聘自动化继续暂停。

## 运行文件

- 主程序：`dist/local-test-20261110-search-results/AutoDeliver/AutoDeliver.exe`
- 后台 worker：`dist/local-test-20261110-search-results/AutoDeliver/auto_deliver_worker.exe`
- 安装包：`release/AutoDeliver-Setup-local-test-20261110-search-results-win64.exe`
- 便携包：`release/AutoDeliver-local-test-20261110-search-results-win64-portable.zip`
- 校验文件：`release/SHA256SUMS-local-test-20261110-search-results.txt`

构建目录共 508 个文件、176,350,275 字节。安装包为 70,267,699 字节，便携包为 89,899,955 字节。便携运行须保留完整 `AutoDeliver` 目录，不能单独移动 EXE；岗位任务仍需本机 Chrome 或 Edge。

## 验证结果

- 全量测试：513 项通过、231 个子测试通过；敏感数据扫描与 `git diff --check` 通过。
- 冻结版 GUI 与 worker 在未设置 `AI_API_KEY`、清理 Python/Conda/Qt 环境及缩减系统 PATH 后，通过离线自检。浏览器使用临时配置打开本地页面，未访问真实招聘平台。
- 主界面、高级设置及关于窗口截图已检查；猎聘显示为已暂停。
- ZIP CRC 校验通过，508 个文件的文件集合与逐项 SHA-256 均与构建目录一致。
- 两个 EXE 内的 20 个相关模块编译内容与当前源码一致；随包说明及配置资源与源文件哈希一致。
- 构建目录未包含 `.env`、简历、候选人画像、岗位画像、投递结果 CSV 或浏览器登录配置。
- 安装包已在工作区隔离目录中静默安装，确认注册信息、开始菜单快捷方式、安装后的 GUI/worker 自检及浏览器启动正常；随后卸载成功，临时安装目录、注册信息和快捷方式均已清理。
- 安装测试前后，现有用户数据中 6 个非日志文件的哈希一致；运行日志 `*.log`、`*.log.*` 不纳入对比。

本次没有登录招聘账号、调用外部 AI 或执行真实投递；上述检查不代表真实平台搜索、登录或投递已验证。未发布到远端，也未覆盖已有安装。

## 验证记录

记录目录：`build/verification/local-test-20261110-search-results/`。

- `pyinstaller.log`、`installer-build.log`：构建日志。
- `offline-self-check-no-key.json`、`offline-self-check-no-key-worker.json`：冻结版离线自检及截图路径。
- `artifact-check.json`：文件数量、源码及资源一致性、ZIP 校验和产物哈希。
- `installer-verification/`：本次安装、安装后自检与卸载报告、日志及截图。
- `previous-installer-evidence/`：运行安装验证前备份的历史报告，复制后已逐项校验 SHA-256。

## SHA-256

```text
FD16DA75D1669F8B8028D77564C09BD4BECC9B975C9AC01FFEDDD3326B69C56E  AutoDeliver.exe
7EA25FCFE5F506F6BC3F9BFAE7CCD48C94A7095B9B1653E72D6D5E689CB96695  auto_deliver_worker.exe
424C199E46C6B6580D5BE48DEAE6226E6961D5A250B1AE7A5CF33509CE2934B8  AutoDeliver-Setup-local-test-20261110-search-results-win64.exe
5AA4B29DE9F006FD4772C55AA1C415183FCD351CC297866FD5D71A620CB013B3  AutoDeliver-local-test-20261110-search-results-win64-portable.zip
```
