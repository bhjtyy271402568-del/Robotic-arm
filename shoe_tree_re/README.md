# 双调节鞋撑机芯 · 逆向建模协作

原始资料：仓库根目录的 `鞋撑机芯_模型与实拍_Claude交接_20261128.zip`（Git LFS）。

## 分工与流程

| 谁 | 做什么 |
|---|---|
| 用户 | 拆实物、按测量清单量尺寸、拍照、回答是否题 |
| Claude | 读照片和模型，列缺尺寸和卡尺放法，写 Codex 任务卡，核对 Codex 交付的 STEP |
| Codex | 在 SolidWorks 里按任务卡建模、装配，导出 STEP |

每一轮：Claude 发任务卡 → Codex 建模并把交付推到 `codex交付/v<轮次>/` → Claude 跑核对、写 `核对报告/` → 下一张任务卡。

## 目录

| 目录 | 内容 |
|---|---|
| `第1轮_对照与缺尺寸/` | 实拍→零件→模型→缺尺寸对照表、测量清单、圈注照片、核对图 |
| `Codex任务卡/` | 按顺序编号的任务卡 |
| `codex交付/` | Codex 每轮的 SLDPRT/SLDASM/STEP 和说明（由 Codex 推送） |
| `核对报告/` | Claude 对每轮交付的核对结果 |
| `tools/` | 核对工具 |

## 工具

需要 Python 3、`cadquery-ocp`、`numpy`、`matplotlib`；渲染另需 Node 和 Playwright。

```bash
python tools/step_check.py info      模型.step                # 实体清单、体积、包围盒
python tools/step_check.py holes     模型.step --min 2 --max 30   # 圆柱面：直径、轴线（孔、销、轴）
python tools/step_check.py interfere 模型.step                # 两两干涉体积，以及间隙 < 0.5 mm 的零件对
python tools/step_check.py section   模型.step --axis x --at 108.75 --out 截面.png
python tools/step_check.py distance  模型.step "零件A" "零件B"
python tools/render_step.py 模型.step 输出前缀 --views iso,top --ghost 黑壳   # 带编号的多视角渲染
```

工具只做几何核对，不能证明强度、装配可行或全行程无干涉。
