`timescale 1ns/1ps
module uart_rx #(
    parameter integer CLK_HZ = 100_000_000,
    parameter integer BAUD = 115200
) (
    input wire clk,
    input wire rst,
    input wire rx,
    output reg [7:0] data,
    output reg valid,
    output reg frame_error
);
    localparam integer BIT_TICKS = (CLK_HZ + BAUD / 2) / BAUD;
    localparam integer TIMER_BITS = $clog2(BIT_TICKS);
    localparam [2:0] IDLE=0, START=1, DATA=2, STOP=3, WAIT_HIGH=4;
    (* ASYNC_REG = "TRUE" *) reg rx_meta;
    (* ASYNC_REG = "TRUE" *) reg rx_sync;
    reg [2:0] state;
    reg [TIMER_BITS-1:0] timer;
    reg [2:0] bit_index;
    reg [7:0] shift;

    always @(posedge clk) begin
        if (rst) begin
            rx_meta <= 1'b1;
            rx_sync <= 1'b1;
        end else begin
            rx_meta <= rx;
            rx_sync <= rx_meta;
        end
    end

    always @(posedge clk) begin
        if (rst) begin
            state <= IDLE;
            timer <= 0;
            bit_index <= 0;
            shift <= 0;
            data <= 0;
            valid <= 1'b0;
            frame_error <= 1'b0;
        end else begin
            valid <= 1'b0;
            frame_error <= 1'b0;
            case (state)
                IDLE: if (!rx_sync) begin
                    timer <= BIT_TICKS / 2 - 1;
                    state <= START;
                end
                START: if (timer != 0) timer <= timer - 1'b1;
                    else if (rx_sync) state <= IDLE;
                    else begin
                        timer <= BIT_TICKS - 1;
                        bit_index <= 0;
                        state <= DATA;
                    end
                DATA: if (timer != 0) timer <= timer - 1'b1;
                    else begin
                        shift[bit_index] <= rx_sync;
                        timer <= BIT_TICKS - 1;
                        if (bit_index == 7) state <= STOP;
                        else bit_index <= bit_index + 1'b1;
                    end
                STOP: if (timer != 0) timer <= timer - 1'b1;
                    else if (rx_sync) begin
                        data <= shift;
                        valid <= 1'b1;
                        state <= IDLE;
                    end else begin
                        frame_error <= 1'b1;
                        state <= WAIT_HIGH;
                    end
                WAIT_HIGH: if (rx_sync) state <= IDLE;
                default: state <= IDLE;
            endcase
        end
    end
endmodule
