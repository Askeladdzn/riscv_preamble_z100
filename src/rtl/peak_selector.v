`timescale 1ns/1ps
// Exact normalized-correlation peak reduction. Inputs arrive at most every 66 clocks.
// Legal scanner bounds: |S| <= 2^17 and E <= 2^28. Cross products fit 63 bits.
module peak_selector (
    input wire clk, rst, clear, valid, last,
    input wire [9:0] index,
    input wire signed [31:0] score,
    input wire [31:0] energy,
    output wire ready,
    output reg done, detected,
    output wire [31:0] position,
    output reg [31:0] candidate,
    output reg signed [31:0] best_score,
    output reg [31:0] best_energy
);
    reg [1:0] state;
    reg pending_last;
    reg [9:0] pending_index;
    reg signed [31:0] pending_score;
    reg [28:0] pending_energy;
    reg [17:0] magnitude;
    reg [34:0] pending_square, best_square;
    reg [63:0] left_product, right_product;
    reg [41:0] threshold_left, threshold_right;
    wire [31:0] abs_score = score[31] ? (~score + 1'b1) : score;
    assign ready = state == 0;
    assign position = detected ? candidate : 32'hffffffff;
    always @(posedge clk) begin
        if (rst || clear) begin
            state<=0; done<=0; detected<=0; candidate<=32'hffffffff;
            best_score<=0; best_energy<=0; best_square<=0;
            pending_last<=0; pending_index<=0; pending_score<=0; pending_energy<=0;
            magnitude<=0; pending_square<=0; left_product<=0; right_product<=0;
            threshold_left<=0; threshold_right<=0;
        end else case (state)
            0: if (valid) begin
                magnitude<=abs_score[17:0]; pending_index<=index;
                pending_score<=score; pending_energy<=energy[28:0]; pending_last<=last;
                state<=1;
            end
            1: begin
                pending_square<=magnitude*magnitude;
                state<=2;
            end
            2: begin
                left_product<=pending_square*best_energy[28:0];
                right_product<=best_square*pending_energy;
                threshold_left<={7'b0,pending_square}*42'd100;
                threshold_right<={13'b0,pending_energy}*42'd3136;
                state<=3;
            end
            3: begin
                if (pending_energy!=0 && (candidate==32'hffffffff || left_product>right_product)) begin
                    candidate<={22'b0,pending_index}; best_score<=pending_score;
                    best_energy<={3'b0,pending_energy}; best_square<=pending_square;
                    detected<=threshold_left>=threshold_right;
                end
                if (pending_last) done<=1;
                state<=0;
            end
        endcase
    end
endmodule
