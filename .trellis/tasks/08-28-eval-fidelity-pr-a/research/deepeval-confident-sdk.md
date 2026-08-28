# DeepEval 4.2.0 Confident 上报行为(源码确认)

> 研究对象:`.venv/lib/python3.12/site-packages/deepeval`(版本 4.2.0,
> `benchmark-online` extra 固定版本)。

## 1. 上报判定

- `deepeval/confident/api.py:119` `get_confident_api_key()` 读取 pydantic
  Settings 的 `CONFIDENT_API_KEY`(env / dotenv)。
- `api.py:146` `is_confident() = get_confident_api_key() is not None`。
- `test_run/test_run.py:1163-1164`:`confident_enabled = is_confident()`;
  仅当 `confident_enabled and disable_request is False` 才 `post_test_run`
  (POST 到 Confident AI)。
- 运行时清除:`set_confident_api_key(None)`(`api.py:119-143`)经
  `s.edit(persist=False)` 只改内存不改磁盘,可用于显式关停。

## 2. 误导提示的两个来源(SDK 内无条件打印)

| 文案 | 位置 | 触发条件 | 官方关闭开关 |
|---|---|---|---|
| `⚠ WARNING: All metrics errored ... Posting the run anyway so you can inspect ... on the Confident AI dashboard` | `test_run.py:1128` | `construct_metrics_scores() == 0`(所有 metric 无分)时打印,与是否配置 key 无关 | 无 |
| `» Run 'deepeval view' to analyze and save testing results on Confident AI` | `test_run.py:1183` | 非 confident 分支(未配置 key)收尾时打印 | 无 |

结论:4.2.0 无"禁用横幅"官方开关;第一条横幅只有在全部指标失败时
出现(本 PR P1-1/P1-2 修复保真度后指标有分,自然消失);第二条
`deepeval view` 建议是 SDK 固定文案,不可配置消除,只能作为已知 SDK
噪音在日志/文档中说明,或通过 monkeypatch(不取,易碎)。

## 3. 本项目现实

- 评测主机跑测日志出现第一条横幅(`smoke-flask-5014`),根因是三项指标
  全部失败——失败根源即 P1-1/P1-2 的保真度问题(tool_name 全 null 等),
  并非 Confident 配置问题。
- 本项目从未配置 `CONFIDENT_API_KEY`,实际上报未发生(源码确认),但
  承诺"离线分析不上报"应变成代码内显式不变量,而不是环境巧合。

## 4. 落地要点

- `analyze_verified_report` 入口(或 `DeepEvalSdkJudge.__init__`):
  1. 断言/显式清除 `CONFIDENT_API_KEY`(env + settings),
  2. 分析结果中记录"telemetry off"状态(reason 或扩展字段),
  3. 单元测试覆盖"未配置 key 分支"。
- 保持 `disable_request` 默认,不调用任何 `set_confident_api_key(非None)`。