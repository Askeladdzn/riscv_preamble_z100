# AI 技术协作附件

建议先阅读 [技术协作记录](cases.md)。该文件按六个工程问题组织，说明技术任务、方案推导、失败修正与验证结果，覆盖软硬件划分、整数位宽、协议契约、综合实现、恢复复现和应用试验。

| 材料 | 入口 | 用途 |
|---|---|---|
| 技术案例分析 | [cases.md](cases.md) | 结合交互与工程产物解释六个问题的处理过程 |
| 原始交互摘录 | [dialogue.md](dialogue.md)、[dialogue.jsonl](dialogue.jsonl) | 23 条与技术过程相关的真实消息或连续原文片段 |
| 产物与来源清单 | [artifact_excerpts.json](artifact_excerpts.json)、[provenance.json](provenance.json)、[integrity.json](integrity.json) | 失败日志、修复前后代码、源行与完整性指纹 |

cases.md 为案例分析，dialogue 为交互原文摘录。性能数据分别注明版本和测试条件，单目标与多目标任务的计时分开比较。

使用平台为 Codex，辅助完成 RTL、固件、主机软件、测试和故障分析；实物接线与按键操作由团队完成。
