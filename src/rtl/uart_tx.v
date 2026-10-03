`timescale 1ns/1ps
module uart_tx #(
    parameter integer CLK_HZ = 100_000_000,
    parameter integer BAUD = 115200
) (
    input wire clk,
    input wire rst,
    input wire [7:0] data,
    input wire valid,
    output wire ready,
    output reg tx
);
    localparam integer BIT_TICKS = (CLK_HZ + BAUD / 2) / BAUD;
    localparam integer TIMER_BITS = $clog2(BIT_TICKS);
    reg [TIMER_BITS-1:0] timer;
    reg [9:0] shift;
    reg [3:0] bit_index;
    reg busy;
    assign ready = !busy;

    always @(posedge clk) begin
        if (rst) begin
            tx <= 1'b1;
            busy <= 1'b0;
            timer <= 0;
            shift <= 10'h3ff;
            bit_index <= 0;
        end else if (!busy) begin
            if (valid) begin
                shift <= {1'b1, data, 1'b0};
                bit_index <= 0;
                timer <= BIT_TICKS - 1;
                tx <= 1'b0;
                busy <= 1'b1;
            end
        end else if (timer != 0) begin
            timer <= timer - 1'b1;
        end else if (bit_index == 9) begin
            tx <= 1'b1;
            busy <= 1'b0;
        end else begin
            timer <= BIT_TICKS - 1;
            shift <= {1'b1, shift[9:1]};
            tx <= shift[1];
            bit_index <= bit_index + 1'b1;
        end
    end
endmodule
