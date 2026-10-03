# 报告与证据对应

| 报告内容 | 提交包内证据 | 复核方式 |
|---|---|---|
| 1.90616 / 1.06968 ms 点积基线 | board/results/baseline_v1 | 30 组原始收发片段，Python 整数参考与周期中位数 |
| A3 数据驻留 13.95976 ms、读取判决 12.09066 ms | board/results/baseline_a3 | 两种流程各 30 组 N=1024 原始记录 |
| A4 硬件首峰 1.87052 ms | board/results/baseline_a4 | 三种模式各 30 组 N=1024 原始记录 |
| A5 主功能回归 | board/results/detection_a5_all_20260925_165051_873902 | 4088 帧原始计划与响应 |
| 物理复位与重下载恢复 | board/results/detection_a5_button_20260925_171123_025947；detection_a5_clean_reprogram_20260925_171217_332944 | 各 30 帧，fresh 标志与计数、计算结果 |
| 最终应用正确性与 41.51 倍板内加速 | board/results/application_preamble_batch_20260925_174436_888233 | 1704 块、60 次计时，保留全部失败边界 |
| 输入预先冻结与数学参考 | data/application_preamble | 生成器、配置、输入哈希及参考结果一致性 |
| RTL 与生产固件集成 | sim/results/detection_a5_* | 1009 组选峰、3487 帧扫描、94 次集成事务 |
| 资源比较与最终时序 | build/reports | 各版本 utilization.rpt，A5 完整实现报告 |
| 原干净构建与下载 | build/clean_a5_manifest.json；build/logs | 2026-09-25 的 BIN/HEX 一致性检查与下载日志 |
| AI 技术协作 | report/ai_records | 23 条真实可见技术摘录、六个案例及字节不变的故障/修正源文件 |
| 可复用技能 | skill | 15 项独立示例检查与 1704 项目输入适配 |

V1/A3/A4 性能片段附有原运行目录、文件哈希和记录下标。A5 包含主批次 4088 帧及两次恢复测试各 30 帧，共 4148 帧，不含另行执行的九次网页演示。

使用 sim/verify_submission.py 重新计算并核对这些结果；report/packaging_provenance.json 记录路径映射及不变文件，report/package_manifest.json 记录最终文件清单。
