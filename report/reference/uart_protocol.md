# 向量计算系统串口协议 v1

固件 `00004001`；PL_UART，115200 baud、8 数据位、无校验、1 停止位、无硬件流控。只允许一个未完成请求：电脑收到完整响应后才发下一个。上电不主动输出 ASCII 文字，由 INFO 请求获取状态。

## 帧结构

所有多字节整数为小端。CRC 使用 CRC-32/ISO-HDLC，与 Python `zlib.crc32` 一致；检验字符串 `123456789` 的 CRC 为 `0xcbf43926`。

| 偏移 / 字节 | 字段 | 内容 |
|---|---|---|
| 0 / 4 | MAGIC | ASCII `RVEC`，十六进制 `52 56 45 43` |
| 4 / 1 | VERSION | 1 |
| 5 / 1 | COMMAND | 请求 01 INFO、02 DOT；响应 81 INFO、82 DOT、ff ERROR |
| 6 / 2 | SEQUENCE | 请求序号，响应原样返回；允许从 65535 回绕到 0 |
| 8 / 2 | LENGTH | 有效载荷字节数，最大 4100 |
| 10 / 2 | FLAGS | 必须为 0 |
| 12 / LENGTH | PAYLOAD | 命令数据 |
| 12+LENGTH / 4 | CRC32 | 从 VERSION 到 PAYLOAD 最后一字节，不含 MAGIC 与 CRC 字段 |

序号用于关联请求与响应，不提供去重：相同序号的两次合法 DOT 会分别计算和计数。电脑应按当前请求校验序号、版本、CRC 和长度。

## INFO

请求不带载荷。响应为 8 个 uint32，共 32 字节：BUILD_ID、CLOCK_HZ、SYSTEM_ID、ACCEL_ID、MAX_N、SELFTEST_MASK、COMPLETED、RECEIVE_TIMEOUTS。

本版本预期为 `00004001`、50000000、`52563031`、`444f5431`、1024、15。COMPLETED 为本次上电后完成的 DOT 请求数；启动自检不计入。RECEIVE_TIMEOUTS 统计已识别完整 MAGIC 后的截断帧超时。这两个计数器为 uint32，复位清零。

SELFTEST_MASK：bit0 为 1 KiB 专用区的 word/byte/halfword RAM 测试，bit1 为 RV32IM 乘除法与余数，bit2 为 CRC 标准检验，bit3 为 MMIO 加速器与软件算出 32、核心周期为 5、设备 ID/时钟值正确。四位均为 1 才接受 DOT 运算。

## DOT

请求载荷：uint16 N、uint16 保留字段（必须为 0），随后是 N 对交错排列的 int16 A[i]、int16 B[i]。例如 A=[1,2,3]、B=[4,5,6]，顺序为 `N,0,1,4,2,5,3,6`。载荷必须恰好 `4+4*N` 字节，N 范围 1–1024。

响应载荷固定 40 字节：

| 载荷偏移 | 类型 | 内容 |
|---|---|---|
| 0 | uint16 | N |
| 2 | uint16 | 软件/硬件比较标志：0 一致、1 不一致；电脑还要独立验算 |
| 4 | int64 | RISC-V 软件点积 |
| 12 | int64 | FPGA 加速器点积 |
| 20 | uint32 | 软件计算周期 C_sw |
| 24 | uint32 | 硬件调用总周期 C_hw_total |
| 28 | uint32 | 加速器核心周期 C_hw_core |
| 32 | uint32 | 加速器 STATUS；成功必须为 2，即 DONE=1、BUSY=ERROR=0 |
| 36 | uint32 | 本次完成后的 COMPLETED 计数 |

软件基线使用 `-O2`、RV32IM 和真实 MUL 指令。两条路径均从相同 CPU RAM 数组出发。C_hw_total 包含 CLEAR、全部 A/B 搬运、配置长度、START、轮询、读取结果与核心周期。C_sw 和 C_hw_total 包含各自调用及计时边界开销；不扣除估算开销，不包含 UART 收发与输入解析。C_hw_core 仅覆盖 START 接受至 DONE。50 MHz 下一个周期为 20 ns。

周期差使用 uint32 模减，短于计数器一圈（约 85.9 秒）时跨越低位回绕仍有效。本项目一次合法计算远短于这个范围。PC 的 host_ms 由 Stopwatch 测量，含 USB/串口、传输、板内计算和接收处理，不等同于板内耗时。

## 错误与恢复

ERROR 载荷为 uint32 ERROR_CODE、uint32 DETAIL，共 8 字节。

| 码 | 含义 |
|---|---|
| 1 | CRC 错误 |
| 2 | 帧载荷越界、N 越界、命令长度不符或 DOT 保留字段非零 |
| 3 | 未知命令 |
| 4 | 版本错误或帧头 FLAGS 非零 |
| 5 | 已识别 MAGIC 后的帧接收超时 |
| 6 | UART 溢出或帧错误 |
| 7 | 启动自检未全通过 |
| 8 | 加速器状态错误或等待 DONE 超过 10 ms |

每个接收字节的等待上限为 100 ms。完整 MAGIC 之前的噪声逐字节丢弃；不完整 MAGIC 超时后重新寻找。已识别 MAGIC 后，截断帧超时返回 5，并重新寻找下一帧；序号字段未收齐时响应序号为 0，收齐时使用接收到的序号。

载荷大于 4100 时不写入缓冲区，持续丢弃到连续 100 ms 空闲后返回 2。UART 错误时清状态并持续丢弃到同样的空闲边界后返回 6。CRC、合法范围内的长度、版本、命令错误在消费当前帧后返回对应错误。电脑收到错误响应后再重试；不允许把重试帧紧接在尚未超时的截断帧后。

错误帧不启动点积、不增加 COMPLETED。异常后用 INFO 和合法 DOT 检查恢复。Python 参考采用任意精度整数，校验三个结果、状态、序号、CRC、周期关系和请求计数，不能仅凭固件的一致标志判定 PASS。
