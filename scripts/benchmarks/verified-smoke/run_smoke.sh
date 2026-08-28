#!/usr/bin/env bash
# flask-5014 真实单题评测(Linux Docker smoke)——脱敏模板,可换机复现。
# 前置:同目录 smoke.env(从 smoke.env.example 复制并填写):
#   OPENAI_API_KEY 必填;LION_MODEL 必填;OPIK_WORKSPACE 必填;
#   DEEPEVAL_JUDGE_MODEL 必填(固定 judge 模型,独立于 agent 模型);
#   OPENAI_BASE_URL/LITELLM_API_BASE/OPIK_API_KEY 可选。
# smoke.env 权限要求:属主为运行用户且权限 600(脚本启动时自动强制,
# 无法保证时拒绝启动)。
# 环境覆写点:SMOKE_RESULT_ROOT(结果根,默认仓库 benchmarks/agent_e2e/results)、
#   SMOKE_ENV_FILE(凭证文件路径)、PYTHON_BIN(仓库 venv python 的覆写)、
#   HARBOR_BIN(harbor 可执行文件覆写)、SMOKE_CHECK_ONLY=1(仅前置校验干跑)。
set -uo pipefail
SMOKE_TOOL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SMOKE_TOOL_DIR/../../.." && pwd)"
cd "$ROOT"
PY="${PYTHON_BIN:-$ROOT/.venv/bin/python}"
HARBOR_BIN="${HARBOR_BIN:-$ROOT/.venv/bin/harbor}"

# 结果与凭证路径(全部可被 env 覆写,默认不含任何本机字面量)
RESULT_ROOT="${SMOKE_RESULT_ROOT:-$ROOT/benchmarks/agent_e2e/results}"
WORK_DIR="$RESULT_ROOT/smoke-flask-5014"
SMOKE_ENV_FILE="${SMOKE_ENV_FILE:-$SMOKE_TOOL_DIR/smoke.env}"
# digest 寻迹账本(机器级;results/ 整体 gitignore,天然不入库)
LEDGER_FILE="${SMOKE_LEDGER_FILE:-$RESULT_ROOT/digest-ledger.jsonl}"

# 0) smoke.env 权限守卫(source 之前):属主必须为当前用户,权限强制 600;
#    违反任一条件即拒绝启动(退出码 2 = 模板脚本自身配置错误)。
guard_env_file() {
  local f="$1"
  if [ ! -f "$f" ]; then
    echo "错误:缺少凭证文件 $f;请从 $SMOKE_TOOL_DIR/smoke.env.example 复制并填写" >&2
    return 2
  fi
  if [ "$(stat -c %u "$f")" != "$(id -u)" ]; then
    echo "错误:$f 属主非当前用户,请 chown 到本用户或使用自己的副本" >&2
    return 2
  fi
  chmod 600 "$f" || {
    echo "错误:无法 chmod 600 $f" >&2
    return 2
  }
  if [ "$(stat -c %a "$f")" != "600" ]; then
    echo "错误:$f 权限无法保证为 600(当前 $(stat -c %a "$f"))" >&2
    return 2
  fi
}
guard_env_file "$SMOKE_ENV_FILE" || exit $?

# 1) 读取凭证(仅注入本次进程环境,不写入任何报告/manifest)
set -a
# shellcheck disable=SC1090
source "$SMOKE_ENV_FILE"
set +a

# 2) 必填项校验
for var in OPENAI_API_KEY LION_MODEL OPIK_WORKSPACE DEEPEVAL_JUDGE_MODEL; do
  if [ -z "${!var:-}" ]; then
    echo "错误:smoke.env 中未填写 $var" >&2
    exit 2
  fi
done

# 3) 受限主目录与缓存重定向(评测主机环境事实的可执行载体):
#    - Harbor 硬编码 ~/.cache/harbor,只读/受限主目录必须挂可写区;
#    - harness 等按 passwd 主目录解析缓存(HF_HOME/XDG_CACHE_HOME);
#    - DeepEval judge 经 litellm 访问自定义 OpenAI-compatible 端点。
export HOME="$WORK_DIR/harbor-home"
export HF_HOME="$WORK_DIR/hf-home"
export XDG_CACHE_HOME="$WORK_DIR/xdg-cache"
export LITELLM_API_BASE="${LITELLM_API_BASE:-${OPENAI_BASE_URL:-}}"
mkdir -p "$WORK_DIR/harbor-home" "$WORK_DIR/hf-home" "$WORK_DIR/xdg-cache"

# 4) check-only 干跑:仅前置校验(权限/凭证/目录可写),不启动评测;
#    供第二台评测主机预检与自动化测试使用。
if [ "${SMOKE_CHECK_ONLY:-0}" = "1" ]; then
  echo "check-only:环境校验通过(凭证文件 600、必填变量齐备、输出目录可写)"
  exit 0
fi

# 5) 生成冻结 manifest:run-id 带时间戳,保证输出目录唯一
RUN_ID="flask-5014-$(date +%Y%m%d-%H%M%S)"
"$PY" "$SMOKE_TOOL_DIR/build_catalog.py" --output-dir "$WORK_DIR" || exit 3
"$PY" "$SMOKE_TOOL_DIR/build_manifest.py" \
  --env OPENAI_API_KEY,OPENAI_BASE_URL --output-dir "$WORK_DIR" \
  --model "$LION_MODEL" --run-id "$RUN_ID" || exit 3
MANIFEST="$WORK_DIR/manifest.$RUN_ID.json"
OUTPUT_DIR="$WORK_DIR/run-$RUN_ID"

# 6) 真实单题闭环(artifact -> Harbor -> 官方 Harness -> DeepEval -> Opik)
TASK_ID="$("$PY" -c 'import json, sys; print(json.load(open(sys.argv[1]))["task_ids"][0])' "$MANIFEST")"
"$PY" -m benchmarks.agent_e2e verified-run \
  --catalog "$WORK_DIR/catalog.json" \
  --manifest "$MANIFEST" \
  --task-id "$TASK_ID" \
  --commit "$(git rev-parse HEAD)" \
  --repository-root "$ROOT" \
  --output-dir "$OUTPUT_DIR" \
  --python "$PY" \
  --harness-python "$PY" \
  --harbor "$HARBOR_BIN" \
  --deepeval-judge-model "$DEEPEVAL_JUDGE_MODEL" \
  --deepeval-samples "${DEEPEVAL_SAMPLES:-3}" \
  --digest-ledger "$LEDGER_FILE" \
  --opik-project lion-agent-e2e \
  --opik-workspace "$OPIK_WORKSPACE"
EXIT_CODE=$?
echo "verified-run 退出码=$EXIT_CODE(run-id=$RUN_ID)"
exit "$EXIT_CODE"