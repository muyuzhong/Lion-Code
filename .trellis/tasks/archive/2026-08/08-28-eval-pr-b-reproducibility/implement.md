# Implement:评测链 PR B(环境文档与模板化)

> 配套 `prd.md` / `design.md`。按序执行;每步完成即核对,进入下一步前
> 工作区干净(仅本任务改动)。

## 0. 前置

- 分支:从 `master` 新建 `eval-pr-b-reproducibility`(PR A 未合并,独立
  base;若 PR A 先行合并,rebase 时仅 docs 一段可能冲突,手动合并不涉及
  本任务语义)。
- 迁移素材:`benchmarks/agent_e2e/results/smoke-flask-5014/`
  `run_smoke.sh`、`build_catalog.py`、`build_manifest.py`(gitignore,
  只读引用,不改动)。

## 1. 模板脚本迁移与改造

- [ ] 1.1 `scripts/benchmarks/verified-smoke/build_catalog.py`:自原目录
  迁移;`parents[4]` → `parents[2]`;新增 `--output-dir`(默认脚本自身
  目录),catalog/catalog.lock 写入参数目录;其余逻辑不动。
- [ ] 1.2 `scripts/benchmarks/verified-smoke/build_manifest.py`:迁移 +
  `parents[2]`;新增 `--output-dir`(默认自身目录);模型名收敛为
  `--model` > 环境 `LION_MODEL`(删除 `read_model_from_env_file` 的文件
  探测);`_resolve_digest` 不动。
- [ ] 1.3 `scripts/benchmarks/verified-smoke/run_smoke.sh`:按 design 2.1
  (路径推导)、2.2(环境重定向)、2.3(凭证校验,含 `OPIK_WORKSPACE`
  必填)、2.4(权限守卫)、2.5(check-only)、2.6(调用链,传
  `--model "$LION_MODEL"` 与 `--output-dir "$WORK_DIR"`)改造;`set -uo
  pipefail` 保持;删除一切本机绝对路径与个人字面量。
- [ ] 1.4 `scripts/benchmarks/verified-smoke/smoke.env.example`:变量名 +
  分组注释 +「复制为 smoke.env,权限 600,属主为运行用户」说明;值全空。
- [ ] 1.5 `.gitignore` 追加 `scripts/benchmarks/verified-smoke/smoke.env`。
- [ ] 1.6 `scripts/benchmarks/verified-smoke/README.md`:design 6 节内容。
- [ ] 1.7 静态自查:`grep -rnE "/home/|muyuzhong" scripts/benchmarks/
  verified-smoke/` 无命中;`bash -n run_smoke.sh` 通过。

## 2. 文档增补(P0-2)

- [ ] 2.1 `docs/agent-e2e-verified-run.md`"Linux 准备"新增"受限主目录与
  缓存重定向"与"DeepEval judge 端点"两小节(design 7 节内容)+
  smoke.env 权限要求 + 一键脚本引用。
- [ ] 2.2 核对:文档三组重定向与 run_smoke.sh 2.2 一一对应。

## 3. 测试

- [ ] 3.1 `tests/benchmarks/test_smoke_template_guard.py`:design 8 节
  用例(缺失/0644 修复/非属主 skipif/必填缺失/`bash -n` + 脱敏静态断言)。
- [ ] 3.2 运行: `python3 -m pytest -q tests/benchmarks/test_smoke_template_guard.py`
- [ ] 3.3 回归: `python3 -m pytest -q tests/benchmarks/test_verified_contracts.py
  tests/benchmarks/test_verified_cli_composition.py tests/benchmarks/test_trace.py`
- [ ] 3.4 门禁: `python3 -m compileall -q scripts/benchmarks/verified-smoke
  tests/benchmarks/test_smoke_template_guard.py`;`git diff --check`。

## 4. 收尾

- [ ] 4.1 实施后勾销:`improvements-backlog.md` 勾选 P0-2/P0-3/P0-4
  (该文件 gitignore 不入库,仅本机记录)。
- [ ] 4.2 提交(中文 message,按改动性质分组;不 push):
  - `feat(benchmark): 评测冒烟脚本脱敏模板化入库并加固 smoke.env 权限`
    (scripts/benchmarks/verified-smoke/*、.gitignore)
  - `docs(benchmark): Linux 准备补充主目录/缓存重定向与 judge 端点`
    (docs/agent-e2e-verified-run.md)
  - `test(benchmark): smoke 模板权限守卫与脱敏静态断言`
    (tests/benchmarks/test_smoke_template_guard.py)
- [ ] 4.3 更新 task.json:`branch=eval-pr-b-reproducibility`、
  `base_branch=master`(对齐 PR A 记录方式)。
- [ ] 4.4 A5 线上复现(第二主机按文档+模板+env 跑通)记入任务 notes,
  待运维执行;完成后 `/trellis:finish-work` 归档。

## 风险与回滚

- 与 PR A 的 docs 冲突:仅一处段落,合并时人工取舍,不影响本 PR 语义。
- 权限守卫在非 Linux(无 `stat -c`)环境不可用:文档与 README 注明
  脚本面向 Linux 评测主机,运行时提前报错。
- 任一阶段失败:回退仅限本任务文件,不触碰既有 results/ 产物。