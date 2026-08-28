# PRD:评测链 PR B(环境文档与模板化)

> 来源:`benchmarks/agent_e2e/results/smoke-flask-5014/improvements-backlog.md`
> 推荐实施顺序第 2 项:P0-2 + P0-3 + P0-4(文档与模板化,便于换机复现)。
> 前序:PR A(#129,P0-1 + P1-1 + P1-2)已实施、未合并;本 PR 基于 master。

## 1. 背景与目标

2026-08-28 在评测主机完成 Verified 单题真实闭环(run_id
`flask-5014-20260828-033257`,PR #128 fix `ec837cf`),过程中确认三项
改进点,均属于"可复现性":

1. **P0-2**:跑通依赖 4 个环境事实,均不在 `docs/agent-e2e-verified-run.md`:
   ① `HOME` 重定向(Harbor 硬编码 `~/.cache/harbor`,只读/受限主目录必挂);
   ② `HF_HOME`/`XDG_CACHE_HOME` 重定向(harness 按 passwd 主目录写缓存,
   复现 `PermissionError: /home/ctyun/.cache/huggingface`);
   ③ `LITELLM_API_BASE`(DeepEval judge 走自定义 OpenAI-compatible 端点);
   ④ Harbor 容器为 Python 3.11、Lion 需 >=3.12(已在 `harbor_agent.py`
   内置独立 Python 3.12 修复,PR #128 发布级修复)。
2. **P0-3**:`build_catalog.py`/`build_manifest.py`/`run_smoke.sh` 躺在
   gitignore 的 `benchmarks/agent_e2e/results/smoke-flask-5014/` 下,其他
   评测主机无法复现;证据文档只记录了路径。
3. **P0-4**:密钥明文存于 gitignore 的 `smoke.env`,多用户主机上可被同属主
   进程误读,无权限不变量。

目标:一个独立 PR,把环境准备文档化、把冒烟脚本脱敏模板化入库、对
`smoke.env` 建立权限不变量;第二台评测主机按「文档 + 模板脚本 + env 凭证」
即可复现单题闭环。

## 2. 需求

### R1(P0-2)评测主机环境准备文档化

- R1.1 在 `docs/agent-e2e-verified-run.md` 的"Linux 准备"章节增补三项环境
  事实(原清单 1–3 项):Harbor 的 `HOME` 重定向;harness 的
  `HF_HOME`/`XDG_CACHE_HOME` 重定向(含 `PermissionError` 现象描述);
  DeepEval judge 的 `LITELLM_API_BASE` 端点说明(与 `OPENAI_BASE_URL`
  同源)。原第 4 项(Python 3.12 内置)属 PR #128 已落地修复,文档可提及
  不展开。
- R1.2 文档指出一键脚本 `scripts/benchmarks/verified-smoke/run_smoke.sh`
  是上述重定向的可执行载体(脚本自动执行,文档给出原理与手动等价做法),
  并注明 `smoke.env` 权限要求(600、属主为运行用户)。
- R1.3 验收:按文档从零环境可复现跑通单题闭环(第二台评测主机执行;
  本 PR 内以 check-only 模式与脚本行为一致性验证代替)。

### R2(P0-3)一键脚本模板化入库

- R2.1 无凭证模板提交到 `scripts/benchmarks/verified-smoke/`:
  `build_catalog.py`、`build_manifest.py`、`run_smoke.sh`、
  `smoke.env.example`、`README.md`(前置条件、用法、env 变量语义、
  权限要求、复现步骤)。
- R2.2 脱敏化约束:脚本不引用本机绝对路径(仓库根由脚本自身位置推导);
  不硬编码用户名/工作空间字面量(如 `muyuzhong`);不含任何密钥值
  (密钥只走环境变量);`smoke.env.example` 只含变量名与占位注释。
- R2.3 原 `results/smoke-flask-5014/` 下的脚本与产物保持原样(仍 gitignore,
  本机复盘使用);README 注明模板的迁移来源与本站脚本关系。
- R2.4 验收:第二台机器按模板 + env 可复现单题闭环;仓库内 grep 无本机
  绝对路径(`/home/...`)、无 `muyuzhong` 字面量、无样例密钥值(静态断言
  测试守护)。

### R3(P0-4)smoke.env 权限加固

- R3.1 模板 `run_smoke.sh` 启动时:定位 `smoke.env`(模板目录内,
  gitignore;路径可被 `SMOKE_ENV_FILE` 覆写);校验属主为当前用户,否则
  拒绝启动并说明;对属主文件执行 `chmod 600` 并复核,无法保证 600 时
  拒绝启动(退出码 2)。
- R3.2 文档/README 注明权限要求(600、属主、且脚本启动时自动强制)。
- R3.3 验收:`smoke.env` 权限恒为 600;凭证缺失/错误权限/属主不符时脚本
  拒绝启动并给出明确原因(自动化子进程测试守护;非属主分支在 root 环境
  验证)。

## 3. 非目标(本 PR 不做)

- 不修改 `verified-run` 主链路(artifact/Harbor/Harness/DeepEval/Opik
  阶段代码与 schema);不改 verdict、退出码语义(模板脚本自身错误沿用 2)。
- 不做多实例/多任务泛化、不引入配置系统或新抽象;保持单题 smoke 形态,
  仅做路径与凭证参数化。
- 不提交任何密钥;不删除或迁移 `results/` 下的本机运行产物。
- P1-3/P1-4/P1-5(judge 独立配置、可复现性、阈值门禁)与 P2 各项不在
  本 PR。

## 4. 约束与红线

- 最小实现:不新增第三方依赖;bash 仅用标准命令;Python 脚本遵守
  `scripts/` 现状与仓库 ruff(E/F/I/RUF/UP)规则。
- 脱敏红线:任何输出/文档/模板不含密钥值与个人标识;`smoke.env.example`
  只存变量名。
- 退出码约定:模板脚本自身配置/权限错误 = 2;`verified-run` 退出码透传。
- 文档语言与现有 `docs/agent-e2e-verified-run.md` 一致(中文)。
- 最小验证:只运行与本次修改直接相关的 targeted tests 与静态断言。

## 5. 验收标准

- **A1(P0-2)**:`docs/agent-e2e-verified-run.md` 增补 R1.1 三项环境事实与
  R1.2 脚本引用/权限说明;文档描述与模板脚本实际行为一致(HOME、
  HF_HOME/XDG_CACHE_HOME、LITELLM_API_BASE 三组重定向一一对应)。
- **A2(P0-3)**:`scripts/benchmarks/verified-smoke/` 五个文件入库且各自
  可独立运行/解释;静态断言通过(无 `/home/`、`muyuzhong`、样例密钥)。
- **A3(P0-4)**:子进程测试覆盖:凭证文件缺失 → 拒绝启动(rc=2);
  属主权限 0644 → 自动修复为 600 并继续;非属主 → 拒绝启动(rc=2,
  非 root 环境 skip);`SMOKE_CHECK_ONLY=1` 时校验通过退出 0。
- **A4**:`bash -n` 通过;既有评测链测试不回归
  (`test_verified_contracts.py`、`test_verified_cli_composition.py` 等
  targeted 范围);`git diff --check` 通过。
- **A5**:第二台评测主机按文档 + 模板 + env 复现单题闭环(线上运维验收,
  不在本 PR CI 内;本 PR 以 check-only 模式与静态/子进程断言兜底)。

## 6. 工作拆分建议

单任务单 PR(跨 docs + scripts + 一个测试文件,可独立理解与回滚),
不拆父子任务,与 PR A 一致。