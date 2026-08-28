#!/usr/bin/env bash
# flask-5014 smoke 运行残留一键清理(仅本机运维,不入 CI)。
# 默认只删除可重建的缓存目录(harbor-home/hf-home/xdg-cache),
# 永不删除 run-* 证据目录;镜像清理需显式开启。
# env 覆写点:
#   SMOKE_RESULT_ROOT   结果根(默认仓库 benchmarks/agent_e2e/results,同 run_smoke.sh)
#   SMOKE_CLEAN_DRY_RUN=1  干跑:只打印将删除项,不执行删除
#   SMOKE_CLEAN_IMAGES=1   同时删除 swebench/sweb.eval* 镜像(docker,失败仅警告)
set -uo pipefail
SMOKE_TOOL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SMOKE_TOOL_DIR/../../.." && pwd)"
RESULT_ROOT="${SMOKE_RESULT_ROOT:-$ROOT/benchmarks/agent_e2e/results}"
WORK_DIR="$RESULT_ROOT/smoke-flask-5014"
DRY="${SMOKE_CLEAN_DRY_RUN:-0}"
IMAGES="${SMOKE_CLEAN_IMAGES:-0}"

# 0) 路径守卫:WORK_DIR 必须解析后位于 RESULT_ROOT 之内,拒绝越界。
#    pwd -P 取物理路径,防止符号链接把删除目标引到结果根之外。
RESULT_REAL="$(cd "$RESULT_ROOT" 2>/dev/null && pwd -P)" || {
  echo "错误:结果根目录不存在或不可访问:$RESULT_ROOT" >&2
  exit 2
}
WORK_REAL="$(cd "$WORK_DIR" 2>/dev/null && pwd -P || true)"
if [ -n "$WORK_REAL" ]; then
  case "$WORK_REAL" in
    "$RESULT_REAL"/*) ;;
    *)
      echo "错误:WORK_DIR($WORK_DIR)越出结果根,拒绝清理" >&2
      exit 2
      ;;
  esac
else
  case "$WORK_DIR" in
    "$RESULT_ROOT"/*) ;;
    *)
      echo "错误:WORK_DIR($WORK_DIR)越出结果根,拒绝清理" >&2
      exit 2
      ;;
  esac
fi

# 1) 缓存目录(可重建;run-* 证据永不删除)
CACHE_DIRS=("harbor-home" "hf-home" "xdg-cache")
for name in "${CACHE_DIRS[@]}"; do
  target="$WORK_DIR/$name"
  if [ ! -e "$target" ]; then
    echo "跳过:$name 不存在"
    continue
  fi
  size="$(du -sh "$target" 2>/dev/null | awk '{print $1}')"
  echo "$( [ "$DRY" = "1" ] && echo "[干跑]将删除" || echo "删除" ):$name($size) $target"
  if [ "$DRY" != "1" ]; then
    rm -rf "$target" || {
      echo "错误:无法删除 $target" >&2
      exit 2
    }
  fi
done

# 2) 镜像清理(显式开启;失败仅警告,不中断)
if [ "$IMAGES" = "1" ]; then
  if command -v docker >/dev/null 2>&1; then
    images="$(docker images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null | grep '^swebench/sweb\.eval' || true)"
    if [ -z "$images" ]; then
      echo "镜像:无 swebench/sweb.eval* 镜像"
    else
      while IFS= read -r image; do
        echo "$( [ "$DRY" = "1" ] && echo "[干跑]将删除镜像" || echo "删除镜像" ):$image"
        if [ "$DRY" != "1" ]; then
          docker image rm "$image" >/dev/null 2>&1 \
            || echo "警告:镜像 $image 删除失败(可稍后手动清理)" >&2
        fi
      done <<<"$images"
    fi
  else
    echo "警告:docker 不可用,跳过镜像清理" >&2
  fi
fi

echo "清理完成:缓存可重建,评测可无损重跑(run-* 证据目录未动)"
exit 0