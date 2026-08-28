# verified-smoke:SWE-bench Verified 单题一键评测(脱敏模板)

从 `benchmarks/agent_e2e/results/smoke-flask-5014/` 的本机冒烟脚本脱敏
迁移入库:仓库根由脚本自身位置推导,不含任何本机绝对路径与个人字面量;
密钥只通过环境变量注入,模板不含任何凭证值。本机旧目录仅供复盘,不再
演进;后续以本模板目录为准。

## 前置条件

- Linux 评测主机(脚本依赖 `stat -c`、`id -u`,面向 Linux);
- Docker daemon 可用,可访问模型提供商、Harbor 所需镜像与 Opik 服务;
- 仓库 venv 已就绪并安装评测链依赖:

  ```bash
  python3 -m venv .venv
  source .venv/bin/activate
  python -m pip install -e ".[benchmark-online]"
  python -m pip install "harbor==0.22.0" "swebench==5.0.1"
  ```

## smoke.env 准备

```bash
cp smoke.env.example smoke.env
chmod 600 smoke.env   # 脚本启动时也会自动强制 600 并校验属主
```

填写三个必填变量与两个可选变量:

| 变量 | 必填 | 说明 |
|---|---|---|
| `OPENAI_API_KEY` | ✅ | 模型 Provider 密钥(官方或 OpenAI-compatible 端点) |
| `LION_MODEL` | ✅ | 模型名,写入 `manifest.profile.model` |
| `OPIK_WORKSPACE` | ✅ | Opik 工作空间名 |
| `OPENAI_BASE_URL` | — | 非官方端点;与 DeepEval judge 端点同源 |
| `OPIK_API_KEY` | — | Opik 凭证(未配置时观测走 unavailable 分支) |

## 运行

```bash
./run_smoke.sh
```

脚本依次:校验/加固 `smoke.env`(600 + 属主) → source 凭证 → 重定向
受限主目录与缓存(`HOME`/`HF_HOME`/`XDG_CACHE_HOME`)与 judge 端点
(`LITELLM_API_BASE`) → 生成冻结 manifest → 执行真实单题闭环
(artifact → Harbor → 官方 Harness → DeepEval → Opik)。

结果默认输出到 `$ROOT/benchmarks/agent_e2e/results/smoke-flask-5014/`。
下述环境变量可覆写默认路径(均非必填):

| 变量 | 默认 |
|---|---|
| `SMOKE_RESULT_ROOT` | `$ROOT/benchmarks/agent_e2e/results` |
| `SMOKE_ENV_FILE` | 本目录 `smoke.env` |
| `PYTHON_BIN` / `HARBOR_BIN` | `$ROOT/.venv/bin/python` / `$ROOT/.venv/bin/harbor` |

## 预检(不启动评测)

```bash
SMOKE_CHECK_ONLY=1 ./run_smoke.sh
```

只做前置校验(凭证文件权限与属主、必填变量、输出目录可写),通过后
打印 `check-only:环境校验通过...` 并以退出码 0 结束;适合第二台评测
主机先验证环境再跑真实评测。

## 输出与退出码

- 输出目录:`verified-report.json` / `verified-report.md` 及受控的 patch、
  trajectory、DeepEval、Opik payload 引用(报告结构与字段说明见
  `docs/agent-e2e-verified-run.md`)。
- 退出码:`verified-run` 语义透传(0 完成且官方通过;1 subject 失败;
  2 基础设施/依赖阻塞;3 输入或结果无效);本脚本自身配置/权限/凭证
  错误一律 2 并带明确错误信息。

## 相关文档

- `docs/agent-e2e-verified-run.md` — Verified 单题运行的完整说明(schema、
  退出码约定、受限主目录与缓存重定向原理、DeepEval 上报关停约束);
  本脚本是其中"Linux 准备"章节所述环境重定向的可执行载体。