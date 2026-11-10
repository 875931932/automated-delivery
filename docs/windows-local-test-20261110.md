# Windows 本地测试版 2026-11-10

由当前源码构建，程序版本元数据沿用 1.0.0。该测试版允许搜索关键词留空，并在无关键词时使用平台推荐岗位查询；留空值会覆盖继承环境中的旧关键词。

## 运行入口

- 主程序：`dist/local-test-20261110/AutoDeliver/AutoDeliver.exe`
- 后台 worker：`dist/local-test-20261110/AutoDeliver/auto_deliver_worker.exe`
- 便携包：`release/AutoDeliver-local-test-20261110-win64-portable.zip`
- 完整目录：508 个文件，共 176,246,894 字节；ZIP 为 89,801,481 字节。

便携运行时保留完整 `AutoDeliver` 目录，不要单独移动主 EXE。程序设置和数据仍使用当前 Windows 用户的 `%APPDATA%/AutoDeliver`；岗位任务需要本机 Chrome 或 Edge。

本次没有替换正式安装包、旧测试版或远端发行文件，也没有制作安装程序。

## 验证结果

- 全量自动化测试：427 项测试、176 项子测试通过。
- 空关键词经配置、画像队列、浏览器 URL 和列表 API 传递；API 请求保留 `scene=1`、`query=""`，浏览器地址不带 `query` 参数。
- 无关键词时生成单条空关键词推荐队列；没有已配置岗位画像时使用通用简历匹配画像，已有评分画像仍保留。
- 在隔离 APPDATA 且未设置 `DELIVER_KEYWORD` 的进程中，运行配置默认值为 `""`；worker 环境测试确认 `.env` 中的空值会覆盖父进程中的旧值。
- 冻结版 GUI 与 worker 离线自检通过，包含资源、关于页、浏览器离线页面及平台限制状态检查。报告与截图位于 `build/verification/local-test-20261110/`。
- 便携 ZIP 的 508 个文件逐一与构建目录比较 SHA-256，全部一致；未发现 `.env`、简历、画像、投递记录或 CSV 文件。
- 未登录真实招聘平台，未调用外部 AI 接口，也未发送真实投递。实际平台推荐结果和排序未在本次离线测试中验证。

## SHA-256

```text
862CE2425A66E4552A9A4156C2F02060488217CC9AB0F1E7A1C654410E1FBAF0  AutoDeliver.exe
B48FCFB5C1BDA4B797C6D0A655E1D7C7024C2AA29330081AA3D58EB0F4548DA0  auto_deliver_worker.exe
10671082E01EE52E50489A4A3246596B2075393EC4C9E9E1634CA1437E0B66D8  AutoDeliver-local-test-20261110-win64-portable.zip
```
