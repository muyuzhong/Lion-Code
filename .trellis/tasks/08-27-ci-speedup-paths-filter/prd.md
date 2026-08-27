# CI 提速：去除重复 pytest 与按变更范围分层执行

## Goal

CI 优化：删除 quality-gates 中重复的普通 pytest；新增 changes 判断 job 按变更范围 gate 各 job；NSIS 打包/烟测/上传仅 push master 执行；desktop job 迁出到独立 desktop.yml

## Requirements

- 删除 `quality-gates` 中独立的 `python -m pytest -q` 步骤（全量测试由 coverage 一步承担）。
- workflow 在 `pull_request` 上始终触发（不使用 `paths`/`paths-ignore`，避免 required check 因 skip 而 Pending 阻塞 merge）。
- 新增极轻量 `changes` job，用 `git diff` 判断本次变更范围（python / desktop），其余 job 用 `needs.changes.outputs.*` + `if` 决定是否执行。
- desktop job 从 ci.yml 迁出到独立的 desktop.yml；`desktop-windows` 仅在 desktop 相关文件变化（或 push master）时执行。
- NSIS 打包、安装态烟测、上传安装包三步仅在 `push`（master）时执行。
- push master 时两个 workflow 均全量执行（含完整 coverage 与 Windows 打包）。

## Acceptance Criteria

- [ ] ci.yml 中不再有独立的 `pytest -q` 步骤，coverage 步骤仍跑全量 pytest。
- [ ] ci.yml / desktop.yml 均有 changes job，事件为 push 时直接输出 true。
- [ ] quality-gates 的 `if` 为 `github.event_name == 'push' || needs.changes.outputs.python == 'true'`。
- [ ] desktop-windows 的 `if` 为 `github.event_name == 'push' || needs.changes.outputs.desktop == 'true'`。
- [ ] NSIS 打包 / 安装态烟测 / 上传安装包三步带有 `if: github.event_name == 'push'`。
- [ ] desktop job 不再存在于 ci.yml；desktop.yml 为新建独立 workflow（`on.pull_request` 无 paths）。
- [ ] YAML 语法校验通过（python -c "import yaml..." 或 actionlint 可用则用）。

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
