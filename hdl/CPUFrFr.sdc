set_time_format -unit ns -decimal_places 3

create_clock -name clock -period 20.000 -waveform {0.000 10.000} [get_ports clock]

derive_pll_clocks
derive_clock_uncertainty

set vga_clock [get_clocks {*generic_pll1~PLL_OUTPUT_COUNTER|divclk}]
set cpu_clock [get_clocks {*generic_pll2~PLL_OUTPUT_COUNTER|divclk}]


set_clock_groups -asynchronous \
    -group [get_clocks clock] \
    -group $vga_clock \
    -group $cpu_clock

set fp_launch [get_registers {*|fp_a_r[*] *|fp_b_r[*] *|fp_op_r[*] *divider|quotient[*] *divider|rem_nonzero}]
set fp_capture [get_registers {*|data_in_registers[*][*] *|data_in_cpsr[*] \
                               *|data_in_pc[*] *|data_in_ledr[*] *|data_in_hex[*] \
                               *|last_written_value[*] *|last_written_value2[*]}]

set_multicycle_path -setup 2 -from $fp_launch -to $fp_capture
set_multicycle_path -hold  1 -from $fp_launch -to $fp_capture

set_false_path -from [get_ports {KEY[*]}] -to [all_registers]

set_false_path -to [get_ports {LEDR[*]}]
set_false_path -to [get_ports {HEX0[*] HEX1[*] HEX2[*] HEX3[*] HEX4[*] HEX5[*]}]

set vga_data [get_ports {VGA_R[*] VGA_G[*] VGA_B[*] VGA_HS VGA_VS VGA_BLANK_N VGA_SYNC_N}]
set_output_delay -clock $vga_clock -max  3.000 $vga_data
set_output_delay -clock $vga_clock -min -1.000 $vga_data
set_false_path -to [get_ports {VGA_CLK}]
