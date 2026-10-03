`timescale 1ns/1ps
// Resident frame/template scanner. Result BRAM reads are latched by RESULT_INDEX.
module window_multi_accel (
    input wire clk, rst, access,
    input wire [13:0] addr,
    input wire [31:0] wdata,
    input wire [3:0] wstrb,
    output reg [31:0] rdata
);
    reg busy, done, error, result_valid;
    reg multi_enable;
    reg [2:0] reduce_state, target_count;
    reg [9:0] reduce_index;
    reg [31:0] first_detected, first_position, first_candidate, first_score, first_energy;
    reg [31:0] target_position[0:3], target_score[0:3], target_energy[0:3];
    reg suppressed;
    integer t, i;
    always @* begin
        suppressed=0;
        for(i=0;i<4;i=i+1)
            if(i<target_count && {22'b0,reduce_index}<target_position[i]+64 &&
               {22'b0,reduce_index}+64>target_position[i]) suppressed=1;
    end
    reg [31:0] length, error_code, core_cycles, starts, template_writes;
    reg [10:0] frame_count;
    reg [63:0] template_bits, template_mask;
    (* ram_style = "block" *) reg signed [15:0] frame_mem [0:1023];
    (* ram_style = "block" *) reg [31:0] scores [0:1023];
    (* ram_style = "block" *) reg [31:0] energies [0:1023];
    reg [31:0] selected_score, selected_energy;
    reg [9:0] window_index;
    reg [6:0] issued;
    reg [5:0] read_index, product_index;
    reg read_valid, product_valid, sign_read;
    reg signed [15:0] sample_read;
    reg signed [31:0] term, score_sum;
    (* use_dsp = "yes" *) reg signed [31:0] square;
    reg [31:0] initial_energy, previous_energy, first_square, outgoing_square;
    wire write_access = access && (|wstrb);
    wire format_ok = addr[1:0] == 0 && wstrb == 4'hf;
    wire frame_select = addr[13:12] == 1;
    wire template_select = addr >= 14'h2000 && addr < 14'h2100;
    wire sample_ok = wdata[15:11] == {5{wdata[11]}};
    wire frame_write = !rst && write_access && !busy && format_ok && frame_select &&
                       frame_count < 1024 && {1'b0,addr[11:2]} == frame_count && sample_ok;
    wire select_result = !rst && write_access && !busy && format_ok && addr == 14'h0020 &&
                         done && wdata < length-63;
    wire commit_window = !rst && busy && reduce_state==0 && product_valid && product_index == 63;
    wire signed [31:0] next_score = score_sum + term;
    wire [31:0] next_energy = window_index == 0 ? initial_energy + square :
                             previous_energy - outgoing_square + square;
    wire [9:0] sample_address = window_index + {3'b0,issued};
    wire accepted_clear = !rst && write_access && !busy && format_ok && addr==0 && wdata==2;
    wire accepted_start = !rst && write_access && !busy && format_ok && addr==0 && wdata==1 &&
                          length>=64 && length<=1024 && (&template_mask) && frame_count==length && !error;
    wire peak_done, peak_detected, peak_ready;
    wire [31:0] peak_position, peak_candidate, peak_score, peak_energy;
    peak_selector u_peak (
        .clk(clk), .rst(rst), .clear(accepted_clear || accepted_start || (busy && reduce_state==1)),
        .valid(commit_window || (busy && reduce_state==3)),
        .last(reduce_state==0 ? {22'b0,window_index}==length-64 : {22'b0,reduce_index}==length-64),
        .index(reduce_state==0 ? window_index : reduce_index),
        .score(reduce_state==0 ? next_score : selected_score),
        .energy(reduce_state==0 ? next_energy : (suppressed ? 32'b0 : selected_energy)), .ready(peak_ready),
        .done(peak_done), .detected(peak_detected), .position(peak_position),
        .candidate(peak_candidate), .best_score(peak_score), .best_energy(peak_energy)
    );
    // No array reset: load tracking prevents access to uninitialized samples.
    always @(posedge clk) begin
        if (frame_write) frame_mem[addr[11:2]] <= wdata[15:0];
        if (!rst && busy && reduce_state==0 && issued < 64) begin
            sample_read <= frame_mem[sample_address];
            sign_read <= template_bits[issued[5:0]];
        end
        if (commit_window) begin
            scores[window_index] <= next_score;
            energies[window_index] <= next_energy;
        end
        if (select_result || (!rst && busy && reduce_state==2)) begin
            selected_score <= scores[busy ? reduce_index : wdata[9:0]];
            selected_energy <= energies[busy ? reduce_index : wdata[9:0]];
        end
    end
    always @* begin
        case (addr)
            14'h0004: rdata = {29'b0,error,done,busy};
            14'h0008: rdata = length;
            14'h000c: rdata = error_code;
            14'h0010: rdata = done ? length-63 : 0;
            14'h0014: rdata = {31'b0,(&template_mask)};
            14'h0018: rdata = core_cycles;
            14'h001c: rdata = 32'h57494e31;
            14'h0024: rdata = result_valid ? selected_score : 0;
            14'h0028: rdata = result_valid ? selected_energy : 0;
            14'h002c: rdata = {21'b0,frame_count};
            14'h0030: rdata = template_writes;
            14'h0034: rdata = starts;
            14'h0038: rdata = done ? first_detected : 0;
            14'h003c: rdata = done ? first_position : 32'hffffffff;
            14'h0040: rdata = done ? first_candidate : 32'hffffffff;
            14'h0044: rdata = done ? first_score : 0;
            14'h0048: rdata = done ? first_energy : 0;
            14'h0050: rdata = {31'b0,multi_enable};
            14'h0054: rdata = done ? {29'b0,target_count} : 0;
            14'h0060: rdata = done ? target_position[0] : 32'hffffffff;
            14'h0064: rdata = done ? target_score[0] : 0;
            14'h0068: rdata = done ? target_energy[0] : 0;
            14'h006c: rdata = done ? target_position[1] : 32'hffffffff;
            14'h0070: rdata = done ? target_score[1] : 0;
            14'h0074: rdata = done ? target_energy[1] : 0;
            14'h0078: rdata = done ? target_position[2] : 32'hffffffff;
            14'h007c: rdata = done ? target_score[2] : 0;
            14'h0080: rdata = done ? target_energy[2] : 0;
            14'h0084: rdata = done ? target_position[3] : 32'hffffffff;
            14'h0088: rdata = done ? target_score[3] : 0;
            14'h008c: rdata = done ? target_energy[3] : 0;
            default: rdata = 0;
        endcase
    end
    always @(posedge clk) begin
        if (rst) begin
            busy<=0; done<=0; error<=0; result_valid<=0;
            multi_enable<=0; reduce_state<=0; reduce_index<=0; target_count<=0;
            first_detected<=0; first_position<=32'hffffffff; first_candidate<=32'hffffffff;
            first_score<=0; first_energy<=0;
            for(t=0;t<4;t=t+1) begin target_position[t]<=32'hffffffff; target_score[t]<=0; target_energy[t]<=0; end
            length<=0; error_code<=0; core_cycles<=0; starts<=0; template_writes<=0;
            frame_count<=0; template_mask<=0; template_bits<=0;
            issued<=0; window_index<=0; read_valid<=0; product_valid<=0;
            read_index<=0; product_index<=0; term<=0; square<=0; score_sum<=0;
            initial_energy<=0; previous_energy<=0; first_square<=0; outgoing_square<=0;
        end else begin
            read_valid<=0;
            product_valid<=read_valid;
            product_index<=read_index;
            if (read_valid) begin
                term <= sign_read ? -{{16{sample_read[15]}},sample_read} :
                                    {{16{sample_read[15]}},sample_read};
                square <= sample_read * sample_read;
            end
            if (busy) begin
                core_cycles<=core_cycles+1'b1;
                if (reduce_state==0 && peak_done) begin
                    first_detected<={31'b0,peak_detected}; first_position<=peak_position;
                    first_candidate<=peak_candidate; first_score<=peak_score; first_energy<=peak_energy;
                    if(peak_detected) begin
                        target_count<=1; target_position[0]<=peak_position;
                        target_score[0]<=peak_score; target_energy[0]<=peak_energy;
                    end
                    if(multi_enable && peak_detected) begin reduce_state<=1; reduce_index<=0; end
                    else begin busy<=0; done<=1; end
                end
                if(reduce_state==1) reduce_state<=2;
                if(reduce_state==2) reduce_state<=3;
                if(reduce_state==3) reduce_state<=4;
                if(reduce_state==4 && peak_ready) begin
                    if(peak_done) begin
                        if(peak_detected) begin
                            target_position[target_count[1:0]]<=peak_position;
                            target_score[target_count[1:0]]<=peak_score;
                            target_energy[target_count[1:0]]<=peak_energy;
                            target_count<=target_count+1'b1;
                        end
                        if(!peak_detected || target_count==3) begin busy<=0; done<=1; end
                        else begin reduce_state<=1; reduce_index<=0; end
                    end else begin reduce_index<=reduce_index+1'b1; reduce_state<=2; end
                end
                if (reduce_state==0 && issued < 64) begin
                    issued<=issued+1'b1; read_index<=issued[5:0]; read_valid<=1;
                end
                if (reduce_state==0 && product_valid) begin
                    score_sum<=next_score;
                    if (window_index==0) initial_energy<=initial_energy+square;
                    if (product_index==0) first_square<=square;
                    if (product_index==63) begin
                        previous_energy<=next_energy; outgoing_square<=first_square;
                        if ({22'b0,window_index} != length-64) begin
                            window_index<=window_index+1'b1; issued<=0; score_sum<=0;
                        end
                    end
                end
            end
            if(accepted_clear || accepted_start) begin
                reduce_state<=0; reduce_index<=0; target_count<=0;
                first_detected<=0; first_position<=32'hffffffff; first_candidate<=32'hffffffff;
                first_score<=0; first_energy<=0;
                for(t=0;t<4;t=t+1) begin target_position[t]<=32'hffffffff; target_score[t]<=0; target_energy[t]<=0; end
            end
            if (write_access) begin
                if (busy) begin error<=1; error_code<=2; end
                else if (!format_ok) begin error<=1; error_code<=4; end
                else if (frame_select) begin
                    if (!sample_ok) begin error<=1; error_code<=6; end
                    else if (frame_count>=1024 || {1'b0,addr[11:2]}!=frame_count) begin error<=1; error_code<=5; end
                    else begin frame_count<=frame_count+1'b1; done<=0; result_valid<=0; end
                end else if (template_select) begin
                    if (wdata!=1 && wdata!=32'hffffffff) begin error<=1; error_code<=6; end
                    else begin
                        template_bits[addr[7:2]]<=wdata[31]; template_mask[addr[7:2]]<=1;
                        template_writes<=template_writes+1'b1; done<=0; result_valid<=0;
                    end
                end else case (addr)
                    14'h0000: begin
                        if (wdata==2) begin
                            done<=0; error<=0; error_code<=0; frame_count<=0; result_valid<=0;
                        end else if (wdata!=1) begin error<=1; error_code<=4; end
                        else if (length<64 || length>1024) begin error<=1; error_code<=1; end
                        else if (!(&template_mask) || frame_count!=length || error) begin error<=1; error_code<=5; end
                        else begin
                            busy<=1; done<=0; result_valid<=0; core_cycles<=0; starts<=starts+1'b1;
                            window_index<=0; issued<=0; read_valid<=0; product_valid<=0;
                            score_sum<=0; initial_energy<=0; previous_energy<=0; outgoing_square<=0;
                        end
                    end
                    14'h0008: begin length<=wdata; done<=0; result_valid<=0; end
                    14'h0050: if(wdata<=1) begin multi_enable<=wdata[0]; done<=0; result_valid<=0; end
                                  else begin error<=1; error_code<=6; end
                    14'h0020: if (select_result) result_valid<=1;
                                  else begin error<=1; error_code<=5; end
                    default: begin error<=1; error_code<=3; end
                endcase
            end
        end
    end
endmodule
