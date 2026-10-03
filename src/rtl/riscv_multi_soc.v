`timescale 1ns/1ps
module riscv_soc #(
    parameter integer CLK_HZ = 50_000_000,
    parameter integer BAUD = 115200,
    parameter MEM_FILE = "firmware.hex"
) (
    input wire clk,
    input wire rst,
    input wire uart_rxd,
    output wire uart_txd,
    output wire fault
);
    wire valid, instr;
    wire [31:0] addr, wdata;
    wire [3:0] wstrb;
    reg ready;
    reg [31:0] io_rdata;
    wire trap;
    reg bus_fault;
    wire ram_selected = (addr < 32'h00010000);
    wire request = valid && !ready;
    wire accel_selected = addr[31:14] == 18'h08000;
    wire [31:0] accel_rdata;
    dot_accel u_accel (
        .clk(clk), .rst(rst), .access(!rst && request && accel_selected),
        .addr(addr[13:0]), .wdata(wdata), .wstrb(wstrb), .rdata(accel_rdata)
    );
    wire window_selected = addr[31:14] == 18'h08001;
    wire [31:0] window_rdata;
    window_multi_accel u_window (
        .clk(clk), .rst(rst), .access(!rst && request && window_selected),
        .addr(addr[13:0]), .wdata(wdata), .wstrb(wstrb), .rdata(window_rdata)
    );
    (* ram_style = "block" *) reg [31:0] ram [0:16383];
    reg [31:0] ram_rdata;
    initial $readmemh(MEM_FILE, ram);
    always @(posedge clk) begin
        if (!rst && request && ram_selected) begin
            if (wstrb[0]) ram[addr[15:2]][7:0]   <= wdata[7:0];
            if (wstrb[1]) ram[addr[15:2]][15:8]  <= wdata[15:8];
            if (wstrb[2]) ram[addr[15:2]][23:16] <= wdata[23:16];
            if (wstrb[3]) ram[addr[15:2]][31:24] <= wdata[31:24];
            ram_rdata <= ram[addr[15:2]];
        end
    end
    picorv32 #(
        .ENABLE_COUNTERS(1), .ENABLE_COUNTERS64(1),
        .ENABLE_MUL(1), .ENABLE_DIV(1), .ENABLE_FAST_MUL(0),
        .BARREL_SHIFTER(1), .COMPRESSED_ISA(0), .ENABLE_IRQ(0),
        .CATCH_MISALIGN(1), .CATCH_ILLINSN(1),
        .PROGADDR_RESET(32'h0), .STACKADDR(32'h10000)
    ) u_cpu (
        .clk(clk), .resetn(!rst), .trap(trap),
        .mem_valid(valid), .mem_instr(instr), .mem_ready(ready),
        .mem_addr(addr), .mem_wdata(wdata), .mem_wstrb(wstrb),
        .mem_rdata(ram_selected ? ram_rdata : io_rdata),
        .pcpi_wr(1'b0), .pcpi_rd(32'b0), .pcpi_wait(1'b0),
        .pcpi_ready(1'b0), .irq(32'b0),
        .mem_la_read(), .mem_la_write(), .mem_la_addr(), .mem_la_wdata(), .mem_la_wstrb(),
        .pcpi_valid(), .pcpi_insn(), .pcpi_rs1(), .pcpi_rs2(), .eoi(), .trace_valid(), .trace_data()
    );

    wire [7:0] rx_data;
    wire rx_valid, rx_frame_error, tx_ready;
    reg tx_valid;
    reg [7:0] tx_data;
    uart_rx #(.CLK_HZ(CLK_HZ), .BAUD(BAUD)) u_rx (
        .clk(clk), .rst(rst), .rx(uart_rxd), .data(rx_data),
        .valid(rx_valid), .frame_error(rx_frame_error)
    );
    uart_tx #(.CLK_HZ(CLK_HZ), .BAUD(BAUD)) u_tx (
        .clk(clk), .rst(rst), .data(tx_data), .valid(tx_valid),
        .ready(tx_ready), .tx(uart_txd)
    );
    reg [7:0] rx_fifo [0:31];
    reg [4:0] rx_wr_ptr, rx_rd_ptr;
    reg [5:0] rx_count;
    reg rx_overrun, rx_bad_frame;
    wire rx_pop = request && addr == 32'h10000004 && wstrb == 0 && rx_count != 0;
    wire rx_push = rx_valid && (rx_count < 32 || rx_pop);
    wire clear_errors = request && addr == 32'h1000000c && wstrb[0] && wdata[0];
    always @(posedge clk) begin
        if (rst) begin
            rx_wr_ptr <= 0;
            rx_rd_ptr <= 0;
            rx_count <= 0;
            rx_overrun <= 0;
            rx_bad_frame <= 0;
        end else begin
            if (rx_push) begin
                rx_fifo[rx_wr_ptr] <= rx_data;
                rx_wr_ptr <= rx_wr_ptr + 1'b1;
            end
            if (rx_pop) rx_rd_ptr <= rx_rd_ptr + 1'b1;
            case ({rx_push, rx_pop})
                2'b10: rx_count <= rx_count + 1'b1;
                2'b01: rx_count <= rx_count - 1'b1;
                default: ;
            endcase
            if (clear_errors) begin
                rx_overrun <= 0;
                rx_bad_frame <= 0;
            end
            if (rx_valid && !rx_push) rx_overrun <= 1;
            if (rx_frame_error) rx_bad_frame <= 1;
        end
    end
    reg [63:0] cycles;
    always @(posedge clk) begin
        if (rst) begin
            ready <= 0;
            io_rdata <= 0;
            bus_fault <= 0;
            tx_valid <= 0;
            tx_data <= 0;
            cycles <= 0;
        end else begin
            cycles <= cycles + 1'b1;
            ready <= 0;
            tx_valid <= 0;
            if (request) begin
                if (ram_selected) ready <= 1;
                else if (accel_selected) begin
                    ready <= 1;
                    io_rdata <= accel_rdata;
                    if (instr) bus_fault <= 1;
                end else if (window_selected) begin
                    ready <= 1;
                    io_rdata <= window_rdata;
                    if (instr) bus_fault <= 1;
                end else begin
                    ready <= 1;
                    io_rdata <= 0;
                    case (addr)
                        32'h10000000: io_rdata <= {28'b0, rx_bad_frame, rx_overrun, tx_ready, (rx_count != 0)};
                        32'h10000004: io_rdata <= rx_count != 0 ? {24'b0, rx_fifo[rx_rd_ptr]} : 32'hffffffff;
                        32'h10000008: if (wstrb[0]) begin
                            if (tx_ready && !tx_valid) begin
                                tx_data <= wdata[7:0];
                                tx_valid <= 1;
                            end else ready <= 0;
                        end
                        32'h1000000c: ;
                        32'h10000010: io_rdata <= cycles[31:0];
                        32'h10000014: io_rdata <= cycles[63:32];
                        32'h10000018: io_rdata <= CLK_HZ;
                        32'h1000001c: io_rdata <= 32'h52563031;
                        default: bus_fault <= 1;
                    endcase
                    if (instr) bus_fault <= 1;
                end
            end
        end
    end
    assign fault = trap || bus_fault || rx_overrun || rx_bad_frame;
endmodule
