set root [file normalize [file join [file dirname [info script]] ..]]
set version [string tolower [lindex $argv 0]]
if {![regexp {^[0-9A-Fa-f]{8}$} $version]} { error "Expected eight hexadecimal build ID digits" }
set bitfile [file join $root build work riscv_$version riscv.bit]
if {![file isfile $bitfile]} { error "RISC-V bitstream is missing" }
open_hw_manager
connect_hw_server -url localhost:3121
set targets [get_hw_targets -quiet]
if {[llength $targets] != 1} { error "Expected exactly one JTAG target" }
current_hw_target [lindex $targets 0]
open_hw_target
set devices [get_hw_devices -quiet -filter {PART == xc7z100}]
if {[llength $devices] != 1} { error "Expected exactly one XC7Z100" }
set device [lindex $devices 0]
current_hw_device $device
set_property PROGRAM.FILE $bitfile $device
program_hw_devices $device
refresh_hw_device $device
puts "PASS: RISC-V $version programmed into volatile FPGA configuration"
close_hw_target
disconnect_hw_server
close_hw_manager
exit 0
