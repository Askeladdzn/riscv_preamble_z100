`timescale 1ns/1ps
module riscv_top #(
    parameter integer BAUD = 115200
) (
    input wire sys_clk_p,
    input wire sys_clk_n,
    input wire sys_rst_n,
    input wire uart_rxd,
    output wire uart_txd,
    output wire [1:0] led
);
    wire clk_in, clk_feedback, clk_feedback_buf, clk_50_raw, clk_50, locked;
    IBUFDS u_clk_in (.I(sys_clk_p), .IB(sys_clk_n), .O(clk_in));
    MMCME2_BASE #(
        .BANDWIDTH("OPTIMIZED"), .CLKIN1_PERIOD(10.0),
        .CLKFBOUT_MULT_F(10.0), .DIVCLK_DIVIDE(1), .CLKOUT0_DIVIDE_F(20.0)
    ) u_mmcm (
        .CLKIN1(clk_in), .CLKFBIN(clk_feedback_buf), .CLKFBOUT(clk_feedback),
        .CLKOUT0(clk_50_raw), .LOCKED(locked), .PWRDWN(1'b0), .RST(!sys_rst_n),
        .CLKFBOUTB(), .CLKOUT0B(), .CLKOUT1(), .CLKOUT1B(),
        .CLKOUT2(), .CLKOUT2B(), .CLKOUT3(), .CLKOUT3B(), .CLKOUT4(), .CLKOUT5(), .CLKOUT6()
    );
    BUFG u_clk_feedback (.I(clk_feedback), .O(clk_feedback_buf));
    BUFG u_clk_system (.I(clk_50_raw), .O(clk_50));
    wire reset_async = !sys_rst_n || !locked;
    (* ASYNC_REG = "TRUE" *) reg [3:0] reset_sync = 4'b1111;
    always @(posedge clk_50 or posedge reset_async) begin
        if (reset_async) reset_sync <= 4'b1111;
        else reset_sync <= {reset_sync[2:0], 1'b0};
    end
    // BRAM enable/write controls must only see a clocked reset, including assertion.
    reg rst = 1'b1;
    always @(posedge clk_50) rst <= reset_sync[3];
    reg [25:0] heartbeat;
    always @(posedge clk_50) begin
        if (rst) heartbeat <= 0;
        else heartbeat <= heartbeat + 1'b1;
    end
    assign led[0] = heartbeat[25];
    riscv_soc #(.BAUD(BAUD)) u_soc (.clk(clk_50), .rst(rst), .uart_rxd(uart_rxd), .uart_txd(uart_txd), .fault(led[1]));
endmodule
