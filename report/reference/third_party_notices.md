# 来源与许可证

## PicoRV32

- 仓库：https://github.com/YosysHQ/picorv32
- 固定提交：ef203c2b0a3fb793280f5114941416c425c5b461。
- 未改动上游 CPU 源码；原许可证内容完整保留在 src/third_party/picorv32/copying，原 README 与来源哈希也保留。
- 上游许可证为 ISC。实际文件名按提交规范转为小写，文件内容未修改。

## 工具与其他依赖

Vivado、Python、NumPy、ReportLab 和 xPack GCC 为外部依赖，安装方法见 report/reproduction.md。RISC-V 固件构建脚本包含 -lgcc。对正式 0000A501 的源码分别保留和省略该参数重新链接，两次 BIN 均与包内已验证固件逐字节一致，链接映射中没有从 libgcc.a 提取的对象。本版固件未因该参数引入 libgcc 运行库代码，记录见 [链接核查](runtime_link_check.json)。工具链附带的 GCC Runtime Library Exception 3.1 已核对，其原文见 https://www.gnu.org/licenses/gcc-exception-3.1.html 。后续固件若实际使用运行库，须按相应文件的许可与例外处理，不能将其改标为 MIT。

引脚约束和接线依据 Z100 开发板资料核对。

## 项目自有部分

除另有声明，项目自有 RTL、固件、上位机、构建与核验脚本、技能包及自有文档采用 [MIT 许可证](license_mit.txt)，版权声明为 Copyright (c) 2026 Project contributors。第三方文件和引用材料按各自原许可与来源声明处理；本声明不重新许可 PicoRV32 等第三方作品。


