# 猎聘独立接入核验记录

日期：2026-11-10。

## 当前结论

猎聘自动化暂停。用户反馈尚未完成登录即出现安全验证，并已提示账号风险。现有通用浏览器原型缺少猎聘独立登录、检索与投递的验证证据，不能继续作为可用接入运行。

本次修改只做本地保护、离线回归测试和公开参考资料阅读。未访问猎聘域名、账号、Cookie 或用户浏览器资料目录，未调用 AI，未发送消息或投递简历，未运行参考仓库的检查或采集命令，未重建发行包。此前接入阶段的公开页观察属于历史操作，不属于本次验证。

## 日志与本地代码证据

用户提供的日志显示：列表岗位、进入 AI 评分及投递计数均为 0，随后以“页面要求安全验证或限制访问”停止，退出码为 3。这说明该次任务在采集前停止；日志本身不能确定平台账号风险的全部成因。

`BrowserJobPlatform.wait_login()` 先构造搜索地址并执行页面跳转，随后 `check_page()` 检查安全验证，再进入登录等待和后台转可见窗口的分支。首次搜索跳转若被平台导向验证页，会在提示登录或显示登录窗口前退出。先前已通过本地替身复现这一执行顺序；未通过真实账号复测。

原型未把登录入口、公开搜索、身份确认和投递分别建模，复用按钮文字也不足以确认猎聘的实际申请步骤。独立浏览器资料目录只能隔离本地数据，不能证明账号操作可用或降低平台风控。

## 参考资料

### 1. CSDN 博客

来源：[猎聘网职位数据爬取实战：逆向 API 接口获取招聘信息](https://blog.csdn.net/qq_65787661/article/details/160146221)。本次可读取，HTTP 200。它是第三方实践文章，接口描述不是官方承诺。

文章讨论搜索接口 `api-c.liepin.com/api/com.liepin.searchfront4c.pc-search-job`，JSON 中使用 `data.mainSearchPcConditionForm` 和 `data.passThroughForm`；搜索条件包括城市、关键词、从 0 开始的 `currentPage`、页大小、年限、薪资与学历。岗位结果位于 `data.data.jobCardList`，公司、岗位等有各自结构。

可参考其猎聘专用数据模型和分页含义。示例中的固定 XSRF、追踪和会话值不能当作本项目的有效凭据。文章未提供账号登录身份确认或简历投递流程，也不能证明当前接口可用、获官方授权或账号安全。

### 2. CSDN 问答

来源：[用户提供的问答链接](https://ask.csdn.net/questions/9574792)。两次只读请求均返回 HTTP 521，未取得正文，因此本记录不引用其内容或据此推断方案。

### 3. TheQY71/liepin-scraper

来源：[仓库及 README](https://github.com/TheQY71/liepin-scraper)、[主程序源文件](https://github.com/TheQY71/liepin-scraper/blob/main/scripts/liepin_cdp_raw.py)。本次读取主分支公开源文件，共 1916 行；以下行号对应 2026-11-10 所读版本，主分支后续可能变化。仅做源码阅读，没有安装或执行该项目。

| 发现 | 源码依据 | 对本项目的影响 |
| --- | --- | --- |
| HTTP 客户端独立维护会话、XSRF 与搜索 JSON | [256-350 行](https://github.com/TheQY71/liepin-scraper/blob/main/scripts/liepin_cdp_raw.py#L256-L350) | 猎聘检索需要独立协议与响应解析，不能套用 BOSS 数据接口 |
| 浏览器模式通过页面上下文执行搜索请求 | [412-443 行](https://github.com/TheQY71/liepin-scraper/blob/main/scripts/liepin_cdp_raw.py#L412-L443) | 与纯 DOM 列表原型不同，当前可用性仍待证据支持 |
| 搜索地址使用 `city`、`currentPage` | [473-475 行](https://github.com/TheQY71/liepin-scraper/blob/main/scripts/liepin_cdp_raw.py#L473-L475) | 与原型 `dqs`、`curPage` 有差异，不能直接推断哪种当前有效 |
| 详情限定读取岗位介绍区域 | [445-469 行](https://github.com/TheQY71/liepin-scraper/blob/main/scripts/liepin_cdp_raw.py#L445-L469) | JD 抽取应保持岗位范围，避免混入整页无关内容 |
| 登录探测在 Cookie 检查后，可用搜索结果中的薪资作为成功条件 | [1532-1587 行](https://github.com/TheQY71/liepin-scraper/blob/main/scripts/liepin_cdp_raw.py#L1532-L1587) | 公开岗位可读不能证明本人账号已登录，不能沿用此成功判据 |
| CLI 提供 HTTP、CDP、检查与 smoke-test | [1750-1786 行](https://github.com/TheQY71/liepin-scraper/blob/main/scripts/liepin_cdp_raw.py#L1750-L1786) | `--check`、`--smoke-test` 会访问猎聘，本次均未执行 |
| 主流程围绕采集、详情、导出及分析 | [1789-1916 行](https://github.com/TheQY71/liepin-scraper/blob/main/scripts/liepin_cdp_raw.py#L1789-L1916) | 未提供可复用的简历投递、招呼发送及成功回执流程 |

该项目的 `warm()` 未检查首页响应是否受限；HTTP 搜索依赖 `raise_for_status()`，不能覆盖所有 HTTP 200 的业务限制或验证页。README 建议受限后切换 HTTP/CDP，但账号已提示风险时不应自动切换渠道继续尝试。它提供了结构参考，不能直接证明有完整风险控制。

其[城市代码表](https://github.com/TheQY71/liepin-scraper/blob/main/data/city_codes.json)存在济南与昆明同为 `250020` 的疑点，未整表复制。仓库采用 MIT 许可；本次未复制源码或新增依赖。

## 独立流程边界

可继续共享简历与画像、标准化后的岗位字段、本地筛选、AI 评分、草稿、结果存储、去重和额度计算。平台访问必须有独立实现与证据。

| 步骤 | 猎聘需要独立确认的内容 | 未确认时的行为 |
| --- | --- | --- |
| 登录入口 | 官方入口、用户主动完成登录、有效身份标识；公开搜索成功不算登录成功 | 不启动采集或申请 |
| 列表检索 | 城市、关键词、筛选码、分页、岗位身份与响应结构 | 不把结构错误当成没有岗位 |
| 详情读取 | 岗位身份、JD 区域、已申请标识、访问状态 | 停止或记录明确原因 |
| 验证与限制 | HTTP 状态、跳转地址、业务错误、弹窗和账号风险 | 停止当前平台，不自动重试或切换 HTTP/CDP |
| 简历申请 | 申请与聊天入口的区别、简历选择、提交步骤和回执 | 保持人工处理，不根据按钮文字推定投递成功 |
| 恢复运行 | 账号状态由用户在官方渠道处理；独立适配完成验证后显式恢复 | 保留暂停，不自动解除 |

以上是后续实现要求，尚未实现新的猎聘 HTTP 或 CDP 在线采集器，也未完成真实账号投递验证。

## 本次保护修改

- `job_platforms.py` 统一记录暂停原因，保留 `liepin` 与中文名称解析，兼容旧配置和历史结果。
- `platform_worker.py` 在读取匹配配置前检查所有选中平台；包含猎聘时返回配置错误 2，任何平台工作器均不启动。
- `platform_deliverer.py` 与 `platform_browser.py` 拦截直接调用，发生在公共初始化、浏览器启动和资料目录创建之前。
- 面板显示“猎聘（已暂停）”，默认不可选；旧配置已勾选时允许取消，取消后禁用；猎聘城市配置禁用。
- 回归覆盖旧配置、工作器工厂、直接构造、浏览器构造及界面状态。本地 Chromium 模拟检查保留为原型检查，不能作为在线可用证据。

## 验证记录

使用项目 `autodeliver` 环境执行最终检查：

- `pytest tests -q`：462 项测试、190 项子测试通过，包括猎聘启动前拦截及旧配置界面行为。
- `scripts/verify_multiplatform.py`：9 项 localhost Chromium 检查通过。使用临时浏览器目录，不访问招聘平台。
- `scripts/check_sensitive_data.py`：通过。
- `git diff --check`：通过。

以上仅验证本地保护与原型行为，不证明真实账号已恢复正常、平台允许自动化访问或在线接入可用。
