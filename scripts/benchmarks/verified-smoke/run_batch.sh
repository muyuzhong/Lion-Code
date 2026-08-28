#!/usr/bin/env bash
# SWE-bench Verified 批量评测(Linux Docker):多实例逐题闭环。
# 与 run_smoke.sh 同一套环境与凭证约定,差异在批量:一次生成多任务
# catalog,每题独立 manifest / run-id / 输出目录,逐题串行运行。
#
# 用法:
#   INSTANCES="psf__requests-5414,pytest-dev__pytest-6202" ./run_batch.sh
# 或:./run_batch.sh psf__requests-5414 pytest-dev__pytest-6202
#
# 环境覆写点同 run_smoke.sh:SMOKE_RESULT_ROOT / SMOKE_ENV_FILE /
#   PYTHON_BIN / HARBOR_BIN / SMOKE_CHECK_ONLY;新增 SMOKE_BATCH_DIR
#   (批量工作目录,默认 results/smoke-batch-<日期>)。
set -uo pipefail
SMOKE_TOOL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SMOKE_TOOL_DIR/../../.." && pwd)"
cd "$ROOT"
PY="${PYTHON_BIN:-$ROOT/.venv/bin/python}"
HARBOR_BIN="${HARBOR_BIN:-$ROOT/.venv/bin/harbor}"

RESULT_ROOT="${SMOKE_RESULT_ROOT:-$ROOT/benchmarks/agent_e2e/results}"
BATCH_TAG="$(date +%Y%m%d-%H%M%S)"
WORK_DIR="${SMOKE_BATCH_DIR:-$RESULT_ROOT/smoke-batch-$BATCH_TAG}"
SMOKE_ENV_FILE="${SMOKE_ENV_FILE:-$SMOKE_TOOL_DIR/smoke.env}"
LEDGER_FILE="${SMOKE_LEDGER_FILE:-$RESULT_ROOT/digest-ledger.jsonl}"

if [ $# -gt 0 ]; then
  INSTANCES=("$@")
elif [ -n "${INSTANCES:-}" ]; then
  IFS=',' read -r -a INSTANCES <<< "$INSTANCES"
else
  echo "错误:未指定实例;用法 INSTANCES=\"id1,id2\" 或位置参数传入" >&2
  exit 2
fi

# 0) smoke.env 权限守卫(source 之前)
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
  chmod 600 "$f" || { echo "错误:无法 chmod 600 $f" >&2; return 2; }
  if [ "$(stat -c %a "$f")" != "600" ]; then
    echo "错误:$f 权限无法保证为 600(当前 $(stat -c %a "$f"))" >&2
    return 2
  fi
}
guard_env_file "$SMOKE_ENV_FILE" || exit $?

set -a
# shellcheck disable=SC1090
source "$SMOKE_ENV_FILE"
set +a

for var in OPENAI_API_KEY LION_MODEL OPIK_WORKSPACE DEEPEVAL_JUDGE_MODEL; do
  if [ -z "${!var:-}" ]; then
    echo "错误:smoke.env 中未填写 $var" >&2
    exit 2
  fi
done

export HOME="$WORK_DIR/harbor-home"
export HF_HOME="$WORK_DIR/hf-home"
export XDG_CACHE_HOME="$WORK_DIR/xdg-cache"
export LITELLM_API_BASE="${LITELLM_API_BASE:-${OPENAI_BASE_URL:-}}"
mkdir -p "$WORK_DIR/harbor-home" "$WORK_DIR/hf-home" "$WORK_DIR/xdg-cache"

if [ "${SMOKE_CHECK_ONLY:-0}" = "1" ]; then
  echo "check-only:环境校验通过(凭证 600、必填变量齐备、工作目录 $WORK_DIR 可写)"
  exit 0
fi

# 1) 一次生成多任务 catalog
"$PY" "$SMOKE_TOOL_DIR/build_catalog.py" \
  --output-dir "$WORK_DIR" \
  --instances "$(IFS=,; echo "${INSTANCES[*]}")" || exit 3

# 2) 逐题闭环串行;每题独立 run-id / manifest / 输出目录
FAILED=0
for INSTANCE in "${INSTANCES[@]}"; do
  TASK_ID="verified-${INSTANCE//__/-}"
  RUN_ID="$(echo "$INSTANCE" | tr '__' '-')-$(date +%Y%m%d-%H%M%S)"
  echo "==== [$INSTANCE] manifest/run-id=$RUN_ID ===="
  # 预拉取该题 verifier 镜像(已存在则秒过);镜像名来自 catalog 扩展
  IMAGE="$("$PY" -c 'import json, sys; c=json.load(open(sys.argv[1])); print(next(t for t in c["tasks"] if t["task_id"] == sys.argv[2])["extensions"]["swebench_image"])' "$WORK_DIR/catalog.json" "$TASK_ID")" || { echo "错误:[$INSTANCE] 读取镜像名失败" >&2; FAILED=1; continue; }
  echo "[$INSTANCE] 预拉取镜像 $IMAGE"
  docker pull -q "$IMAGE" >/dev/null 2>&1 || { echo "错误:[$INSTANCE] 镜像拉取失败" >&2; FAILED=1; continue; }
  if ! "$PY" "$SMOKE_TOOL_DIR/build_manifest.py" \
    --env OPENAI_API_KEY,OPENAI_BASE_URL --output-dir "$WORK_DIR" \
    --model "$LION_MODEL" --run-id "$RUN_ID" \
    --task-id "$TASK_ID"; then
    echo "错误:[$INSTANCE] manifest 生成失败" >&2
    FAILED=1
    continue
  fi
  MANIFEST="$WORK_DIR/manifest.$RUN_ID.json"
  OUTPUT_DIR="$WORK_DIR/run-$RUN_ID"
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
  echo "[$INSTANCE] verified-run 退出码=$EXIT_CODE(run-id=$RUN_ID)"
  if [ "$EXIT_CODE" -ne 0 ]; then FAILED=1; fi
done

echo "==== 批量结束:失败标记=$FAILED,工作目录=$WORK_DIR ===="
exit "$FAILED"