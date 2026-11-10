# AutoDeliver 求职工作台

一款基于 Python、PySide6 和大模型的 Windows 桌面求职辅助工具，将岗位检索、简历与 JD 匹配评估、招呼语起草和投递记录整理到一个工作台中。

**v1.0.1 可选择 BOSS 直聘和智联招聘，智联属于实验性接入；猎聘因用户反馈账号风险已暂停。** 猎聘入口会在启动浏览器和使用登录资料目录前拦截，待独立流程完成核验后再评估恢复。智联已接入检索、详情读取、匹配评估及结果记录，真实账号下的完整投递流程尚未验证。各平台能力与限制见[多平台接入说明](docs/multi-platform.md)。本项目为独立工具，与招聘平台不存在官方隶属、合作或授权关系。

v1.0.1 包含多关键词搜索、使用项目浏览器打开岗位链接，以及结果筛选、多选和删除管理。应用、EXE 与安装器统一使用 1.0.1 版本号。原 v1.0.0 仅支持 BOSS，未包含这些更新。

[Gitee 下载 v1.0.1](https://gitee.com/yan-ace/automated-delivery/releases/tag/v1.0.1) · [GitHub 下载 v1.0.1](https://github.com/875931932/automated-delivery/releases/tag/v1.0.1) · [更新说明](docs/release-notes-1.0.1.md) · [使用说明与免责声明](DISCLAIMER.md) · [反馈问题](https://gitee.com/yan-ace/automated-delivery/issues) · [发行验证](docs/windows-release-1.0.1.md)

## 界面预览

![AutoDeliver 求职设置界面](docs/images/workbench.png)

截图来自隔离自检环境，展示未填写个人信息的初始设置状态，不包含真实简历、API Key 或投递记录。

## 能做什么

| 功能 | 说明 |
| --- | --- |
| 岗位检索与筛选 | 多关键词独立搜索后合并去重，记录每词统计并停止重复翻页；可选择一个或多个平台，BOSS 的平台侧筛选仅对 BOSS 生效 |
| 简历与 JD 评估 | 对照岗位描述与候选人材料给出匹配分数、简历证据、硬性缺口和待核实要求 |
| 个性化招呼语 | 围绕 JD 的具体职责和真实项目经历起草首条消息，支持调整提示词 |
| 候选人画像 | 从简历建立基础信息，通过可选的访谈补充经历、能力和求职偏好 |
| 历史岗位去重 | 结合岗位标识和历史结果跳过已完成处理的岗位，减少重复工作 |
| 已沟通岗位识别 | 识别当前职位的“已沟通”“继续沟通”等状态，跳过重复评分、招呼语生成及发送 |
| 试运行与正式模式 | 先查看筛选、评分和招呼语结果，再决定是否启用真实发送 |
| 结果与日志 | 按状态、关键词和分数筛选，支持勾选与批量删除，删除列在最右侧；岗位链接沿用对应平台的项目浏览器登录信息 |
| 桌面配置管理 | 通过界面保存设置，提供保存结果提示及启动前检查 |

评分用于辅助判断，不代表招聘方评价，也不保证面试机会或录用结果。平台页面或接口变化可能影响功能可用性。

## 下载与安装

### 当前版本 v1.0.1

从 [Gitee 发行页](https://gitee.com/yan-ace/automated-delivery/releases/tag/v1.0.1) 或 [GitHub 发行页](https://github.com/875931932/automated-delivery/releases/tag/v1.0.1) 下载：

| 发行文件 | 适用场景 | 大小 |
| --- | --- | ---: |
| `AutoDeliver-Setup-1.0.1-win64.exe` | 推荐使用，提供安装向导、开始菜单入口及卸载功能 | 约 67 MiB |
| `AutoDeliver-1.0.1-win64-portable.zip` | 完整解压后运行 `AutoDeliver/AutoDeliver.exe` | 约 86 MiB |
| `SHA256SUMS.txt` | 核对两个发行包的 SHA-256 | 以发行页为准 |

发行文件不包含在 Git 源码中。本地构建产物位于 `release/`；本次已解包程序位于 `dist/1.0.1/AutoDeliver/AutoDeliver.exe`，需保留完整 `AutoDeliver` 文件夹。验证范围及校验值见[1.0.1 发行验证](docs/windows-release-1.0.1.md)。

升级前关闭工作台及项目浏览器，备份 `%APPDATA%\AutoDeliver` 后运行新安装包。安装器沿用原应用标识，默认保留用户数据；便携版应解压到完整的新目录。原 v1.0.0 及本地测试版记录保留在历史文档中。

### 运行要求

- Windows 10 1903 或更新版本、Windows 11，64 位。当前没有 macOS/Linux 安装包。
- 安装 Chrome 或 Edge，用于所选招聘平台的登录及岗位操作；本工具不附带浏览器。
- 准备可用的 OpenAI 兼容 AI 接口、API Key 和模型名称。
- 安装包与便携版自带 Python 运行环境，无需另装 Python 或 Conda。

安装版运行所选版本的安装程序后按向导操作。便携版完整解压 ZIP，运行 `AutoDeliver/AutoDeliver.exe`；不要单独移动主程序，需保留同目录的 `_internal` 和 `auto_deliver_worker.exe`。便携版也使用下文列出的 AppData 数据目录。

当前 EXE 和安装包尚未代码签名，Windows 可能显示“未知发布者”或信誉提示。请核对下载来源与校验值，无需关闭系统安全软件。

## 首次使用

1. 打开软件，在“求职设置”中填写 AI 接口地址、API Key 和模型名称。接口应支持 OpenAI 兼容的聊天调用。
2. 选择自己的 Markdown 或 TXT 简历、招聘平台和工作城市；默认仅选 BOSS，智联属于实验功能，猎聘已暂停。旧配置已选中猎聘时，请取消勾选后保存。搜索关键词可留空，多个词用逗号或分号分隔；BOSS 的平台侧筛选不传给其他平台。当前不直接解析 PDF 或 Word 简历。
3. 按需使用“增强画像”补充经历和求职偏好，检查画像中的事实。该步骤可在基础配置完成后继续完善。
4. 点击“保存配置”，确认保存提示。先启用试运行，再启动任务；所选平台按顺序运行，需要登录时，在各自浏览器中自行完成登录。遇到安全验证或限制提示时，本轮停止该平台，请在官方页面处理。
5. 在“投递结果”中查看评分、筛选理由、证据和招呼语。结束任务后可使用岗位链接打开项目浏览器；需要整理历史时，先筛选再勾选删除，行内删除按钮在最右侧。通过“运行日志”检查问题。
6. 确认简历、筛选条件、生成内容和运行范围后，再关闭试运行并启动正式任务。正式模式可能发送消息或触发平台简历投递，已执行的操作可能无法撤回。新平台遇到聊天、简历选择等未适配流程时会记录为需人工处理。

使用流程：配置与简历 → 按所选平台检索 → 去重及条件筛选 → JD 匹配评估 → 招呼语草稿 → 试运行记录或平台投递 → 结果保存。

## 主要配置

大部分设置可直接在桌面界面中修改，无需手动编辑文件。

| 配置 | 用途与注意事项 |
| --- | --- |
| 招聘平台 | 可多选 BOSS 直聘、智联招聘并按顺序运行；智联为实验接入，猎聘已暂停 |
| AI 接口 | 配置接口地址、密钥、模型、超时和重试；调用费用由对应服务商计收 |
| 简历与画像 | 使用本人真实资料，画像内容应人工核对，不能把岗位要求当作已有经历 |
| 搜索与筛选 | 统一设置关键词、城市及本地条件；平台侧区域、行业、职位类型等暂仅用于 BOSS；未收录的新平台城市代码需在高级设置填写 |
| 匹配阈值 | 控制进入后续处理的分数要求，分数仍需结合理由和证据判断 |
| 运行范围与节奏 | 调整处理数量、每日投递上限和间隔；页数、处理量和发送量是不同设置 |
| 试运行 | 保留检索、评估和结果记录，不发送消息或投递简历 |
| 浏览器路径 | 一般自动发现 Chrome/Edge；失败时可在高级设置指定 `BROWSER_PATH` |
| 后台浏览器 | 已有有效登录时可后台运行，需要登录或验证时仍可能显示浏览器 |
| Tavily 搜索 | 可选，用于画像访谈中的市场资料补充；主投递流程不依赖它，未配置时可继续基础访谈 |

AI 评分以本次任务设置的工作城市作为当前地点意向，优先于简历、结构化摘要和旧画像中的地点偏好；选择“全国”表示本轮不限求职城市。例如简历写深圳、本次选择上海时，评分规则要求按上海意向评估，不因旧地点偏好扣分。该设置不会改写简历，也不代表已经居住当地或能立即到岗；岗位实际地点与当前设置不符时仍需核实。规则适用于新的评分，已有结果不会自动重算。

历史去重会区分平台、完成状态与失败状态。普通失败记录可以重试；试运行结果在切换正式模式后仍可进入正式处理。已触发但未确认回执的投递会记录为“投递待核对”并阻止自动重试，请先核对官方投递记录。调整条件后看到某个历史岗位被跳过时，应先核对原记录，避免误删投递历史。

搜索关键词支持用中文或英文逗号、分号分开填写，例如 `AI应用开发；大模型应用；RAG；LangChain`。每个词独立查询并合并去重；`Python API` 中的空格保留为短语，留空仍使用平台推荐。正常结束时日志展示每词请求数、唯一岗位数、首次入队数和停止原因；同一词连续返回已见整页时会停止继续翻页，平台适配器的更严格检查仍优先生效。用法、统计口径和官方搜索建议见[岗位搜索策略与本次优化](docs/job-search-strategy-20261110.md)。

投递结果表的“岗位链接”图标和详情中的“打开岗位详情”均使用项目配置的 Chrome/Edge 及该平台独立登录目录，开启“保留登录信息”且登录仍有效时可沿用账号。任务运行期间请先结束任务再打开；查看完岗位后，先关闭该平台项目浏览器窗口，再启动任务。会话恢复可能同时恢复上次标签页；平台登录过期时仍需重新登录。猎聘链接仅供用户主动打开，自动化继续暂停。

结果表提供“选择”和“删除”列，删除列位于最右侧。可先筛选，再勾选记录并点击“删除所选”，也可直接点击行内垃圾桶。每页最多 200 项，“全选本页”仅选择当前页；切换筛选、翻页或刷新会清空勾选。删除需确认，执行前在结果 CSV 同目录生成 `.delete-日期时间-随机标识.bak` 备份。有岗位 ID 时同步删除该岗位所有历史，避免刷新后旧记录重新出现；无 ID 时按完整记录内容及所选数量删除。任务运行时不能删除，文件发生变化时需刷新后重新选择。删除只影响本地历史，不撤回平台投递，不改变今日投递计数，但可能使岗位在后续任务中再次被处理。详见[结果记录管理](docs/result-management.md)。

## 数据位置

以下为默认位置，自定义结果或简历路径时以实际配置为准：

| 内容 | 默认路径 |
| --- | --- |
| 配置 | `%APPDATA%\AutoDeliver\.env` |
| 投递结果 | `%APPDATA%\AutoDeliver\deliver_results.csv` |
| 每日记录 | `%APPDATA%\AutoDeliver\deliver_log.json` |
| 候选人画像、摘要和访谈缓存 | `%APPDATA%\AutoDeliver` |
| 面板启动日志 | `%APPDATA%\AutoDeliver\panel-startup.log` |
| BOSS 浏览器登录信息 | `%USERPROFILE%\.boss-zhipin-scraper\chrome-profile` |
| 智联浏览器登录信息 | `%USERPROFILE%\.autodeliver-zhilian\chrome-profile` |
| 猎聘旧登录资料目录（暂停期间不使用） | `%USERPROFILE%\.autodeliver-liepin\chrome-profile` |

可在资源管理器地址栏输入 `%APPDATA%\AutoDeliver` 打开数据目录。安装和卸载默认保留用户数据；迁移或清理前请先备份。简历保存在用户自行选择的位置。

API Key 当前保存在本地配置文件中，并非加密凭据库。进行 AI 评估、招呼语生成或画像访谈时，相关简历、JD 和访谈内容会发送到用户配置的服务；启用搜索时，相应查询会发送至搜索服务。

发行包不携带开发者的简历、密钥、画像、投递记录或浏览器登录数据。请勿将自己的 `.env`、结果文件、浏览器资料目录提交到仓库。

## 常见问题

**支持哪些招聘平台？**

v1.0.1 可在“求职设置 → 简历与搜索 → 招聘平台”中选择 BOSS 和实验性接入的智联招聘。猎聘因反馈账号风险已暂停；若旧配置包含猎聘，启动前会报错，需取消勾选后保存。新平台尚未完成真实账号登录和完整投递验证，详见[多平台接入说明](docs/multi-platform.md)和[猎聘独立流程核验记录](docs/liepin-integration-review-20261110.md)。原 v1.0.0 仅支持 BOSS。

**为什么还需要 AI 接口？**

简历与 JD 评估、招呼语生成和画像访谈依赖你配置的模型服务。软件不内置免费模型额度，API Key 也需要自行申请。

**试运行会发送消息吗？**

不会发送消息或投递简历，但会执行岗位检索及 AI 评估，因此仍可能消耗模型额度。正式模式才可能按配置执行投递。

**为什么仍会弹出浏览器？**

首次登录、登录失效或平台要求验证时，需要用户操作。后台浏览器设置不能代替登录，也不保证绕过平台限制。

**v1.0.1 对浏览动作和平台限制做了哪些调整？**

2026-11-09 的源码更新将额外浏览收敛为可见列表页的一次轻量滚动，后台模式不再穿插浏览；投递前额外滚动和逐字输入延迟已移除，配置中的请求节奏、岗位间隔及详情页停留仍生效。

识别到 HTTP 401/403/429、明确受限提示或已知安全验证页面后，任务会停止、保存已完成结果，并显示“平台限制”。请在官方页面处理后手动重启；若发送后出现限制，先核对会话。检测覆盖有边界，不代表防封承诺。详见[运行说明](docs/runtime-heartbeat.md)与[平台规则调研](docs/boss-platform-policy.md)。

**“继续沟通”的岗位会重复发送吗？**

当前流程会识别已沟通状态并跳过，发送前也会再次检查。若平台页面结构发生变化，识别可能失效；发现异常应停止任务并反馈。

**已有投递结果，为什么某些岗位还会处理？**

去重依据岗位标识及结果状态。失败记录允许重试；试运行结果转正式模式时也允许继续。若已完成岗位仍重复处理，可提交脱敏日志帮助定位。

**找不到浏览器或简历怎么办？**

安装 Chrome/Edge，或在高级设置中填写浏览器可执行文件路径。简历应重新通过“选择文件”指定有效的 Markdown/TXT 文件。

## 开发与构建

主要技术：Python 3.11、PySide6、DrissionPage、LangChain、Pydantic。配置使用 `.env`，投递结果使用 CSV，画像及缓存使用 JSON。

### 源码运行

在 Windows 上安装 Python 3.11，克隆项目并建立独立环境：

```powershell
git clone https://gitee.com/yan-ace/automated-delivery.git
cd automated-delivery
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe desktop_panel.py
```

也可双击 `启动面板.vbs` 无控制台启动。该入口优先检查 `AUTODELIVER_PYTHONW` 和项目 `.venv`，可用前者指定解释器。

### 自动化检查

测试额外需要 `pytest`，它不属于最终用户的运行依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install pytest
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python.exe -X utf8 -B -m pytest tests -q
Remove-Item Env:QT_QPA_PLATFORM
.\.venv\Scripts\python.exe -X utf8 -B scripts/check_sensitive_data.py
```

v1.0.0 发布时通过 402 项测试和 137 项子测试，并完成打包后界面、后台程序、浏览器启动、安装及卸载验证。测试没有发送真实投递消息，不构成匹配效果或平台可用性的保证。详细范围见[发行验证记录](docs/windows-release-1.0.0.md)。

v1.0.1 的测试、冻结程序离线自检、便携包逐项校验及隔离安装卸载结果见[发行验证记录](docs/windows-release-1.0.1.md)。此前的[本地构建记录](docs/windows-local-test-20261110-search-results.md)保留作历史证据；发布检查未执行真实招聘账号投递，也不代表实际匹配效果。

### Windows 打包

安装构建依赖、测试依赖和 Inno Setup 6.7.4 后运行：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt pytest
powershell -ExecutionPolicy Bypass -File scripts/build_windows.ps1 -Python ".\.venv\Scripts\python.exe" -Iscc "Inno Setup 安装目录\ISCC.exe"
```

EXE 输出到 `dist/AutoDeliver/`，安装包及便携 ZIP 输出到 `release/`。构建脚本默认执行测试及冻结程序自检，并使用资源白名单打包。

打包后可执行独立自检，不调用外部 AI 或发送真实消息：

```powershell
.\dist\AutoDeliver\AutoDeliver.exe --self-check "完整路径\release-check.json"
```

### 项目结构

```text
desktop_panel.py          桌面主窗口与配置管理
panel_*.py                画像、结果、日志及通用界面组件
auto_deliver.py           岗位处理与投递流程
platform_worker.py        多平台顺序调度与本轮数量分配
job_platforms.py          平台标识、城市代码、链接及岗位身份
platform_browser.py      智联实验性浏览器适配与已暂停的猎聘原型
platform_job_parser.py   平台岗位列表与详情解析
platform_deliverer.py    复用统一筛选、匹配及结果处理流程
boss_spider.py            BOSS 直聘浏览器及岗位数据访问
ai_chains.py / ai_client.py  模型调用与结构化输出
greeting_prompt.py        招呼语默认提示词
candidate_profiles.py     候选人画像及证据整理
job_profiles.py           岗位方向与检索配置
result_store.py           投递结果保存及历史去重
result_browser.py         使用项目浏览器和平台登录目录打开岗位链接
packaging/                Windows 打包与安装器配置
scripts/                  构建、敏感信息检查及验证工具
tests/                    自动化测试
docs/                     设计、运行说明和发行验证记录
```

浏览器运行机制可进一步阅读[后台浏览器与启动说明](docs/quiet-startup.md)、[运行协调与心跳说明](docs/runtime-heartbeat.md)。

## 反馈与贡献

欢迎通过 [Gitee Issues](https://gitee.com/yan-ace/automated-delivery/issues) 提交问题或改进建议。问题报告建议包含软件版本、Windows 与浏览器版本、试运行或正式模式、复现步骤，以及脱敏后的日志或截图。

请移除 API Key、Cookie、登录信息、完整个人简历和招聘方私聊内容。修改代码后运行相关测试；新增平台支持、发送逻辑或数据格式变更，建议先说明设计与验证范围。

## 作者与许可

- 作者：**Gnahz**
- 邮箱：[875931932@qq.com](mailto:875931932@qq.com)
- GitHub 个人主页：[github.com/875931932](https://github.com/875931932)
- Gitee 项目：[yan-ace/automated-delivery](https://gitee.com/yan-ace/automated-delivery)

以上为作者主动公开的项目联系方式。软件侧栏“关于”窗口也提供联系方式和完整免责声明。

项目代码许可见 [Academic Free License 3.0](LICENSE)。第三方组件依各自许可证使用，详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)；免责声明不替代代码许可证或第三方许可条款。

仅使用本人或已获得明确授权的账号与资料，并遵守平台规则。请合理设置运行范围与频率，遇到登录、验证或限制提示时按平台要求处理。完整说明见 [DISCLAIMER.md](DISCLAIMER.md)。
