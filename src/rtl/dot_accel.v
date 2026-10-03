`timescale 1ns/1ps
module dot_accel (
    input wire clk,
    input wire rst,
    input wire access,
    input wire [13:0] addr,
    input wire [31:0] wdata,
    input wire [3:0] wstrb,
    output reg [31:0] rdata
);
    reg busy, done, error;
    reg [31:0] length, error_code, core_cycles;
    reg signed [63:0] result, accumulator;
    (* ram_style = "block" *) reg signed [15:0] a_mem [0:1023];
    (* ram_style = "block" *) reg signed [15:0] b_mem [0:1023];
    reg signed [15:0] a_read, b_read;
    (* use_dsp = "yes" *) reg signed [31:0] product;
    reg [10:0] issued;
    reg read_valid, read_last, product_valid, product_last;
    wire write_access = access && (|wstrb);
    wire select_a = addr[13:12] == 2'b01;
    wire select_b = addr[13:12] == 2'b10;
    wire signed [63:0] next_sum = accumulator + {{32{product[31]}}, product};

    // No reset of memory arrays: initialization is supplied by the CPU before START.
    always @(posedge clk) begin
        if (!rst && write_access && !busy && addr[1:0] == 0) begin
            if (select_a) begin
                if (wstrb[0]) a_mem[addr[11:2]][7:0] <= wdata[7:0];
                if (wstrb[1]) a_mem[addr[11:2]][15:8] <= wdata[15:8];
            end
            if (select_b) begin
                if (wstrb[0]) b_mem[addr[11:2]][7:0] <= wdata[7:0];
                if (wstrb[1]) b_mem[addr[11:2]][15:8] <= wdata[15:8];
            end
        end
        if (!rst && busy && issued < length) begin
            a_read <= a_mem[issued[9:0]];
            b_read <= b_mem[issued[9:0]];
        end
    end
    always @* begin
        case (addr)
            14'h0004: rdata = {29'b0, error, done, busy};
            14'h0008: rdata = length;
            14'h000c: rdata = error_code;
            14'h0010: rdata = result[31:0];
            14'h0014: rdata = result[63:32];
            14'h0018: rdata = core_cycles;
            14'h001c: rdata = 32'h444f5431;
            default: rdata = 0;
        endcase
    end
    always @(posedge clk) begin
        if (rst) begin
            busy <= 0; done <= 0; error <= 0;
            length <= 0; error_code <= 0; core_cycles <= 0;
            result <= 0; accumulator <= 0; product <= 0;
            issued <= 0; read_valid <= 0; read_last <= 0;
            product_valid <= 0; product_last <= 0;
        end else begin
            read_valid <= 0;
            product_valid <= read_valid;
            product_last <= read_last;
            if (read_valid) product <= a_read * b_read;
            if (busy) begin
                core_cycles <= core_cycles + 1'b1;
                if (issued < length) begin
                    issued <= issued + 1'b1;
                    read_valid <= 1;
                    read_last <= (issued + 1'b1 == length);
                end
                if (product_valid) begin
                    accumulator <= next_sum;
                    if (product_last) begin
                        result <= next_sum;
                        busy <= 0;
                        done <= 1;
                    end
                end
            end
            if (write_access) begin
                if (busy) begin
                    error <= 1; error_code <= 2;
                end else if (addr[1:0] != 0) begin
                    error <= 1; error_code <= 4;
                end else if (select_a || select_b) begin
                    if (!(|wstrb[1:0])) begin error <= 1; error_code <= 4; end
                end else if ((addr == 14'h0000 || addr == 14'h0008) && wstrb != 4'hf) begin
                    error <= 1; error_code <= 4;
                end else case (addr)
                    14'h0000: begin
                        if (wdata == 2) begin done <= 0; error <= 0; error_code <= 0; end
                        else if (wdata != 1) begin error <= 1; error_code <= 4; end
                        else if (length == 0 || length > 1024) begin error <= 1; error_code <= 1; end
                        else begin
                            busy <= 1; done <= 0; error <= 0; error_code <= 0;
                            issued <= 0; read_valid <= 0; product_valid <= 0;
                            read_last <= 0; product_last <= 0;
                            accumulator <= 0; result <= 0; core_cycles <= 0;
                        end
                    end
                    14'h0008: length <= wdata;
                    default: begin error <= 1; error_code <= 3; end
                endcase
            end
        end
    end
endmodule
