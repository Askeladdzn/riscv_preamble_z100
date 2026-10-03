create_clock -period 10.000 -name sys_clk_p [get_ports sys_clk_p]
set_property -dict {PACKAGE_PIN D9 IOSTANDARD DIFF_SSTL135} [get_ports sys_clk_p]
set_property -dict {PACKAGE_PIN D8 IOSTANDARD DIFF_SSTL135} [get_ports sys_clk_n]
set_property -dict {PACKAGE_PIN AA25 IOSTANDARD LVCMOS33} [get_ports sys_rst_n]
set_property -dict {PACKAGE_PIN AA27 IOSTANDARD LVCMOS33} [get_ports uart_rxd]
set_property -dict {PACKAGE_PIN AA28 IOSTANDARD LVCMOS33} [get_ports uart_txd]
set_property -dict {PACKAGE_PIN U21 IOSTANDARD LVCMOS33} [get_ports {led[0]}]
set_property -dict {PACKAGE_PIN Y25 IOSTANDARD LVCMOS33} [get_ports {led[1]}]
set_false_path -from [get_ports sys_rst_n]
# MMCM lock and the button assert reset asynchronously; release crosses reset_sync.
# Exempt only asynchronous preset pins; shift-register D paths stay timed.
set_false_path -to [get_pins -hierarchical -filter {NAME =~ *reset_sync_reg*/PRE}]
set_false_path -from [get_ports uart_rxd] -to [get_pins -hierarchical -filter {NAME =~ */rx_meta_reg/D}]
set_false_path -to [get_ports {uart_txd led[*]}]
