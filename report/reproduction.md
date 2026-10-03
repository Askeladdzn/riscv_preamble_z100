# 最终版本复现步骤

## 环境

Windows 与 PowerShell，Python 3.12、NumPy 2.3.5、ReportLab 4.4.9；Vivado 2023.1，安装 xc7z100ffg900-2 器件支持并具备有效许可。串口使用 .NET SerialPort，115200、8N1。Vivado 2023.1 已验证，未验证其他版本。请把工作副本放在短英文目录，例如 E:\fpga_review\riscv_preamble_z100；避免 Windows 旧目录联接或重定向的临时目录。

保留原始包供文件校验，所有重建和新板测在工作副本执行。原始输入、原始响应和旧版本清单不因重新运行而重写。

## 只读核验

```powershell
python -m pip install -r src/host/requirements.txt
python -B -X utf8 sim/verify_submission.py
```

脚本不连接串口。核验范围：精确文件清单；V1/A3/A4 的 N=1024 性能原始片段；A5 主批次 4088 帧和按键/重下载恢复各 30 帧；生产固件集成 94 次事务；冻结应用 1704 块加 60 次性能调用；技能示例、报告、真实技术对话摘录及排错证据。

## 编译器与固件

固定 xPack RISC-V GCC 15.2.0-1：

https://github.com/xpack-dev-tools/riscv-none-elf-gcc-xpack/releases/download/v15.2.0-1/xpack-riscv-none-elf-gcc-15.2.0-1-win32-x64.zip

ZIP SHA256：85ef714dacd273b1dadf4af4892774520ac01915bfa6da816a56e7e41591e09e。

校验下载后解压到 build/tools，使 build/tools/xpack-riscv-none-elf-gcc-15.2.0-1/bin/riscv-none-elf-gcc.exe 存在；也可用 -CompilerBin 指定实际 bin 目录。安装包不随提交分发。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File build/build_detection_a5_firmware.ps1 -BuildId 0000a501
```

编译使用 RV32IM、ILP32、-O2，检查合法指令和 64 KiB RAM 容量，生成 build/firmware/0000a501/ 下 BIN、HEX、ELF、反汇编及清单。BIN/HEX 应与原包逐字节相同；ELF 中的路径元数据可能不同。

## 仿真

Python 可执行文件与 Vivado bin 路径均可通过参数指定，默认 Python 从 PATH 查找。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File build/simulate_detection_a5.ps1 -Mode selector -Python python -VivadoBin E:/Xilinx/Vivado/2023.1/bin
powershell -NoProfile -ExecutionPolicy Bypass -File build/simulate_detection_a5.ps1 -Mode unit -Python python -VivadoBin E:/Xilinx/Vivado/2023.1/bin
powershell -NoProfile -ExecutionPolicy Bypass -File build/simulate_detection_a5.ps1 -Mode system -Python python -VivadoBin E:/Xilinx/Vivado/2023.1/bin
```

selector 检查 1009 组、16488 项统计；unit 检查 3487 帧、3249185 窗口与 19 项错误条件；system 使用生产固件 HEX，检查 94 次 UART/CPU/MMIO 事务。日志必须含 PASS 且无 FAIL。

## 综合实现

```powershell
$vivado = 'E:\Xilinx\Vivado\2023.1\bin\vivado.bat'
& $vivado -mode batch -source build/build_detection_a5.tcl -tclargs 0000a501
```

检查 setup/hold 非负、四个异步复位同步器 PRE 引脚、BRAM 复位检查及约束报告。结果在 build/reports/riscv_0000a501，下载文件在 build/work/riscv_0000a501/riscv.bit。目录内附带的是原来已经过实板验证的下载文件；重新实现可能因元数据或布局变化得到不同 bitstream 哈希，仍需新板测确认。

## 上板与演示

Z100 使用原配电源、JTAG 下载器与 PL_UART J20 USB。时钟 D9/D8，PL_RST AA25，UART RX AA27/TX AA28，LED U21/Y25；以 board/riscv.xdc 为准。关闭其他串口助手，确认 COM 号。

```powershell
& $vivado -mode batch -source build/program_riscv.tcl -tclargs 0000a501
python -B -X utf8 src/host/serve_application_preamble.py --port COM9 --http-port 8767
```

本机打开 http://127.0.0.1:8767/ 。页面选择四报文、无目标、弱信号、相似序列边界并执行实板请求，确认返回版本 0000A501 和新记录。服务仅绑定本机；手机的 127.0.0.1 不是运行服务的电脑。

完整应用复测：python -B -X utf8 src/host/application_preamble.py batch --port COM9 。每次生成新的时间戳目录，勿把旧统计当成新结果。正常结束并释放串口后，短按 PL_RST 再验证计数归零和计算恢复；原包附带两项恢复证据。

## 证据与限制

report/package_manifest.json 是当前包清单。build/firmware/0000a501/source_manifest.json 与 build/clean_a5_manifest.json 保留历史绑定，其旧路径描述原开发状态，不能当作当前包文件目录。构建与接口验证记录见 report/package_validation.json。
