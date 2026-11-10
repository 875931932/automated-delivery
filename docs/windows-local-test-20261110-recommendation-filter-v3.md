# Windows 本地测试版：推荐筛选 v3

日期：2026-11-10。基于当前源码构建，程序版本元数据沿用 1.0.0。此版本在空搜索关键词的推荐流中，只有判定为 `in_scope` 的岗位进入 AI 评分；`out_of_scope` 直接跳过，`scope_review` 记录待复核且不调用 AI、不占 `TEST_LIMIT`。定向关键词搜索逻辑保持不变。

## 运行文件

- 主程序：`dist/local-test-20261110-recommendation-filter-v3/AutoDeliver/AutoDeliver.exe`
- 后台 worker：`dist/local-test-20261110-recommendation-filter-v3/AutoDeliver/auto_deliver_worker.exe`
- 便携包：`release/AutoDeliver-local-test-20261110-recommendation-filter-v3-win64-portable.zip`
- 构建目录：508 个文件，共 176,248,652 字节；ZIP 共 89,789,422 字节。

便携运行时须保留完整 `AutoDeliver` 目录，不要单独移动主 EXE。设置及运行数据仍保存在当前 Windows 用户的 `%APPDATA%/AutoDeliver`；岗位任务需要本机 Chrome 或 Edge。

## 验证结果

- 全量自动化测试：428 项通过；`py_compile` 与 `git diff --check` 通过。
- 冻结版 GUI 与 worker 在未设置 `AI_API_KEY` 的环境下通过离线自检；报告位于 `build/verification/local-test-20261110-recommendation-filter-v3/offline-self-check-no-key.json`。
- GUI 自检确认应用资源、AI 链、离线浏览器页面、平台限制状态与界面均可用；worker 自检通过。自检使用临时 APPDATA，不会调用外部 AI 接口或招聘平台。
- ZIP 包含 508 个文件，逐项与构建目录比较 SHA-256，全部一致；未包含 `.env`、简历、候选人/岗位画像或投递记录。
- 修正了未填写 API Key 时配置警告中的控制台编码问题，避免 GBK 环境下启动自检异常。
- 未登录真实招聘平台，未调用外部 AI，也未进行真实投递；平台实际推荐结果和筛选准确率尚未验证。

人工标记目前不会训练或自动更新模型。这次改动是让推荐模式的确定性范围判断约束 AI 调用；被标记为待复核的岗位仍需人工查看。若 `in_scope` 本身过宽，误筛仍可能进入 AI，需结合真实误筛样本继续收紧职位族规则。

## SHA-256

```text
B2837AE8A0A97AC72326B2584270452F9A63ECB163BEB779B8C00D5D7B9351B2  AutoDeliver.exe
8331AAD5FCF0C25FF2E08669917C1AEB9C7ACD8E56E8658E61F82E8AF80A6A70  auto_deliver_worker.exe
633CEBDFB84B79E397BF9BA742C392577528CE65AC0D83E9E1EDB97C67A752A9  AutoDeliver-local-test-20261110-recommendation-filter-v3-win64-portable.zip
```
