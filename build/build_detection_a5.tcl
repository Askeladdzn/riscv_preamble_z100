set root [file normalize [file join [file dirname [info script]] ..]]
set version [string tolower [lindex $argv 0]]
if {![regexp {^[0-9A-Fa-f]{8}$} $version]} { error "Expected eight hexadecimal build ID digits" }
set work [file join $root build work riscv_$version]
set reports [file join $root build reports riscv_$version]
file mkdir $work
file mkdir $reports
file copy -force [file join $root build firmware $version firmware.hex] [file join $work firmware.hex]
cd $work
create_project -force riscv_$version $work -part xc7z100ffg900-2
read_verilog [file join $root src third_party picorv32 picorv32.v]
foreach name {uart_rx.v uart_tx.v dot_accel.v peak_selector.v window_multi_accel.v riscv_multi_soc.v riscv_top.v} { read_verilog [file join $root src rtl $name] }
add_files [file join $work firmware.hex]
read_xdc [file join $root board riscv.xdc]
synth_design -top riscv_top -part xc7z100ffg900-2
set reset_async_pins [get_pins -hierarchical -filter {NAME =~ *reset_sync_reg*/PRE}]
if {[llength $reset_async_pins] != 4} { error "Expected four reset synchronizer PRE pins" }
puts "INFO: Verified four asynchronous reset PRE pins; synchronous D paths remain timed"
opt_design
place_design
route_design
report_timing_summary -file [file join $reports timing_summary.rpt]
report_utilization -file [file join $reports utilization.rpt]
report_drc -file [file join $reports drc.rpt]
if {[llength [get_drc_violations -quiet -filter {NAME =~ REQP-1839*}]] != 0} { error "Asynchronous reset still reaches BRAM controls" }
report_io -file [file join $reports io.rpt]
report_clocks -file [file join $reports clocks.rpt]
check_timing -verbose -file [file join $reports check_timing.rpt]
report_exceptions -file [file join $reports exceptions.rpt]
set setup [get_timing_paths -delay_type max -max_paths 1]
set hold [get_timing_paths -delay_type min -max_paths 1]
if {[llength $setup] == 0 || [llength $hold] == 0} { error "No timing paths" }
if {[get_property SLACK $setup] < 0 || [get_property SLACK $hold] < 0} { error "RISC-V timing failed" }
write_checkpoint -force [file join $work riscv_routed.dcp]
write_bitstream -force [file join $work riscv.bit]
puts "PASS: RISC-V $version bitstream generated and setup/hold timing met"
close_project
exit 0
