# Design:评测链 PR B(环境文档与模板化)

> 配套 `prd.md`。本文件记录边界、数据流、具体改造与取舍;实施时以
> `implement.md` 的顺序清单执行。

## 1. 涉及面与边界

| 文件 | 动作 |
|---|---|
| `scripts/benchmarks/verified-smoke/run_smoke.sh` | 新增(迁移 + 脱敏 + 权限守卫 + check-only) |
| `scripts/benchmarks/verified-smoke/build_catalog.py` | 新增(迁移 + `--output-dir`) |
| `scripts/benchmarks/verified-smoke/build_manifest.py` | 新增(迁移 + `--output-dir`、模型名显式参数) |
| `scripts/benchmarks/verified-smoke/smoke.env.example` | 新增(无凭证变量模板) |
| `scripts/benchmarks/verified-smoke/README.md` | 新增(复现步骤与约定) |
| `.gitignore` | 增加 `scripts/benchmarks/verified-smoke/smoke.env` |
| `docs/agent-e2e-verified-run.md` | "Linux 准备"增补(P0-2) |
| `tests/benchmarks/test_smoke_template_guard.py` | 新增(权限守卫子进程测试 + 脱敏静态断言) |
| `benchmarks/agent_e2e/results/smoke-flask-5014/*` | 不动(仍 gitignore,本机复盘) |

不触碰:`verified_runner.py`、Harbor/Harness/DeepEval/Opik 阶段、schema、
报告模型。

## 2. run_smoke.sh 模板化改造

迁移自 `results/smoke-flask-5014/run_smoke.sh`,逐项变更:

### 2.1 路径推导(消除本机绝对路径)

```bash
SMOKE_TOOL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"  # 模板自身目录
ROOT="$(cd "$SMOKE_TOOL_DIR/../../.." && pwd)"                  # 仓库根(上溯 3 级)
RESULT_ROOT="${SMOKE_RESULT_ROOT:-$ROOT/benchmarks/agent_e2e/results}"
WORK_DIR="$RESULT_ROOT/smoke-flask-5014"                        # 与既有布局一致
SMOKE_ENV_FILE="${SMOKE_ENV_FILE:-$SMOKE_TOOL_DIR/smoke.env}"   # 测试可覆写
PY="${PYTHON_BIN:-$ROOT/.venv/bin/python}"
HARBOR_BIN="${HARBOR_BIN:-$ROOT/.venv/bin/harbor}"
```

- `RESULT_ROOT`/`SMOKE_ENV_FILE`/`PYTHON_BIN`/`HARBOR_BIN` 均为 env 覆写点,
  默认值只含相对仓库的约定路径,不含本机字面量。
- 其余命令(`--catalog`、`--manifest`、`--output-dir`、`--harbor`)全部改用
  `$WORK_DIR` 派生,不再引用 `results/smoke-flask-5014` 绝对路径。

### 2.2 环境事实的可执行载体(P0-2 三项,顺序在凭证校验之后)

```bash
export HOME="$WORK_DIR/harbor-home"     # Harbor 硬编码 ~/.cache/harbor
export HF_HOME="$WORK_DIR/hf-home"      # harness 按 passwd 主目录写缓存
export XDG_CACHE_HOME="$WORK_DIR/xdg-cache"
export LITELLM_API_BASE="${LITELLM_API_BASE:-${OPENAI_BASE_URL:-}}"  # judge 端点
mkdir -p "$WORK_DIR/harbor-home" "$WORK_DIR/hf-home" "$WORK_DIR/xdg-cache"
```

### 2.3 凭证与模型校验(set -a source 之后)

- 必填(缺失 → 提示 + `exit 2`,沿用原语义):`OPENAI_API_KEY`,`LION_MODEL`,
  `OPIK_WORKSPACE`。
- 可选:`OPENAI_BASE_URL`(非官方端点)、`LITELLM_API_BASE`(显式覆盖)、
  `OPIK_API_KEY`。
- `--opik-workspace "$OPIK_WORKSPACE"`:删除原 `:-muyuzhong` 默认字面量。

### 2.4 权限守卫(在 source smoke.env 之前执行,P0-4)

```bash
guard_env_file() {
  local f="$1"
  [ -f "$f" ] || {
    echo "错误:缺少凭证文件 $f;从 $SMOKE_TOOL_DIR/smoke.env.example 复制并填写" >&2
    return 2
  }
  [ "$(stat -c %u "$f")" = "$(id -u)" ] || {
    echo "错误:$f 属主非当前用户,请 chown 或使用自己的副本" >&2; return 2
  }
  chmod 600 "$f" || { echo "错误:无法 chmod 600 $f" >&2; return 2; }
  [ "$(stat -c %a "$f")" = "600" ] || {
    echo "错误:$f 权限无法保证为 600(当前 $(stat -c %a "$f"))" >&2; return 2
  }
}
guard_env_file "$SMOKE_ENV_FILE" || exit $?
```

- 不变量:每次启动自动 `chmod 600` 并复核,属主不符或无权限写入时拒绝。
- 退出码 2 = 模板脚本自身配置/权限错误(沿用脚本既有约定)。

### 2.5 check-only 干跑模式(供第二主机预检与自动化测试)

```bash
# 校验通过后、启动评测前:
if [ "${SMOKE_CHECK_ONLY:-0}" = "1" ]; then
  echo "check-only:环境校验通过(凭证文件 600、必填变量齐备、目录可写)"
  exit 0
fi
```

- 只做 2.3/2.4 与目录可写检查,不生成 manifest、不启动 verified-run。

### 2.6 调用链

```
run_smoke.sh
├─ guard_env_file(source 前)
├─ source smoke.env(仅注入进程环境)
├─ "$PY" "$SMOKE_TOOL_DIR/build_catalog.py" --output-dir "$WORK_DIR"
│     # 每次运行重建 catalog/catalog.lock(幂等,同内容哈希稳定)
├─ "$PY" "$SMOKE_TOOL_DIR/build_manifest.py" \
│     --env OPENAI_API_KEY,OPENAI_BASE_URL \
│     --output-dir "$WORK_DIR" --model "$LION_MODEL" --run-id "$RUN_ID"
└─ "$PY" -m benchmarks.agent_e2e verified-run ...(退出码透传)
```

## 3. build_catalog.py 改造

- `sys.path.insert(0, parents[2])`(原 parents[4] 随目录层级变化)。
- 新增 `--output-dir`(必填时传给 run_smoke;默认脚本自身目录,兼容直接
  运行)。catalog/catalog.lock 写入该目录。
- 其余不变:INSTANCE_ID 固定 `pallets__flask-5014`(单题 smoke,不泛化
  多实例)。

## 4. build_manifest.py 改造

- `sys.path.insert(0, parents[2])`。
- 新增 `--output-dir`(默认脚本自身目录):catalog/lock 从该目录读取,
  manifest 写入该目录。
- 模型名收敛为显式输入:优先级 `--model` > 环境 `LION_MODEL` > 报错
  (退出 2);删除 `read_model_from_env_file()` 对同目录 smoke.env 的隐式
  文件探测——直接运行场景用 `LION_MODEL` env 即可。
- `_resolve_digest()`(docker inspect pinned image)与其余字段保持不动。

## 5. smoke.env.example 与 .gitignore

- `smoke.env.example`:只含变量名、分组注释、占位说明,值一律为空;
  注释注明「复制为 smoke.env 后填写;权限须 600,属主为运行用户」。
- `.gitignore` 增加一行 `scripts/benchmarks/verified-smoke/smoke.env`。

## 6. README.md 内容

前置(仓库 venv + `.[benchmark-online]`、harbor 0.22.0、swebench 5.0.1、
Docker daemon)→ smoke.env 准备(复制 example、变量语义表、权限)→
一键运行(`run_smoke.sh`)→ 预检(`SMOKE_CHECK_ONLY=1`)→ 输出与退出码 →
与 `docs/agent-e2e-verified-run.md` 的关系 → 脱敏说明(密钥只走 env,
模板不含任何凭证与个人字面量)。

## 7. docs/agent-e2e-verified-run.md 增补(P0-2)

在"Linux 准备"的凭证段之后新增两小节(基于 master 版本,与 PR A 的
telemetry 段落内容不重叠,合并冲突面小):

- **受限主目录与缓存重定向**:`HOME`(Harbor `~/.cache/harbor` 硬编码,
  只读/受限主目录必须挂可写区)、`HF_HOME`/`XDG_CACHE_HOME`(harness 按
  passwd 主目录解析缓存,复现 `PermissionError: /home/.../.cache/
  huggingface` 的现象与解法)。
- **DeepEval judge 端点**:`LITELLM_API_BASE` 与 `OPENAI_BASE_URL` 同源,
  judge 经 litellm 访问自定义 OpenAI-compatible 端点;不设时走官方端点。
- 两小节末尾均注明:一键脚本 `scripts/benchmarks/verified-smoke/
  run_smoke.sh` 自动执行以上重定向(文档为原理说明,脚本为可执行载体)。
- 同时补充 `smoke.env` 权限要求(600、属主为运行用户,脚本启动时强制)。

## 8. 测试设计(tests/benchmarks/test_smoke_template_guard.py)

子进程方式调用 `run_smoke.sh`(同一 Python 运行宿主,bash 可用):

| 用例 | 构造 | 期望 |
|---|---|---|
| 凭证文件缺失 | `SMOKE_ENV_FILE` 指向不存在路径 + `SMOKE_CHECK_ONLY=1` | rc=2,stderr 含"缺少" |
| 0644 自动修复 | tmp 目录 `smoke.env`(0644,仅变量名) + `SMOKE_CHECK_ONLY=1` + 必填变量经 **env 注入** | rc=0,且文件权限变为 600 |
| 非属主拒绝 | tmp 文件 `chown` 到其他 uid(仅 root 可构造,pytest `skipif`) | rc=2,stderr 含"属主" |
| 必填变量缺失 | 0600 空 env + `SMOKE_CHECK_ONLY=1` | rc=2,stderr 含缺哪个变量 |
| bash 语法 | `bash -n` | rc=0 |

关键点:`SMOKE_CHECK_ONLY=1` 保证测试不触发真实评测;必填变量通过进程
env 注入(不写真实密钥,只用占位值 `dummy`),避免 smoke.env 落盘密钥。

另含**脱敏静态断言**:读取模板目录内 3 个脚本 + example + README 源码,
断言不含 `/home/`、`muyuzhong`(正则按字面量)、占位符外的密钥模样
(`sk-[A-Za-z0-9]` 长串)。防未来回退。

## 9. 取舍记录

- **不做自动 `umask` 化**:smoke.env 由脚本显式 chmod,不隐式依赖 umask,
  行为可测。
- **不抽通用 shell 框架**:守卫函数内联在 run_smoke.sh,只有一处使用
  (无第二个使用场景,遵守防过度抽象)。
- **不迁移既有 results/ 脚本**:它们是 gitignore 的本机复盘产物;模板为
  迁移快照,README 说明来源;避免双份维护——后续以 scripts/ 模板为准,
  本机旧目录不再演进。
- **check-only 模式**:既是测试开关也是第二主机预检入口,一个用途两个
  场景,不算测试专用后门。
- **build_manifest 删除 smoke.env 文件探测**:隐式文件 IO 收敛为显式
  `--model`/`LION_MODEL`,符合"零兼容包袱"。run_smoke 调用时显式传
  `--model "$LION_MODEL"`。

## 10. 完成判定(与 prd.md A1–A5 对应)

- A1:docs 增补存在且与脚本三组重定向一一对应(评审核对)。
- A2:五个模板文件入库;静态断言 + README 完整。
- A3:上述子进程用例全绿。
- A4:`bash -n`、targeted pytest、`git diff --check` 通过。
- A5:第二主机线上复现为后续运维验收,归入任务 notes 而非 PR 门槛。