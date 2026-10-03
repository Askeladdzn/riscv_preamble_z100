`timescale 1ns/1ps
module tb_detection_a5_system;
    localparam integer BIT_NS=4000; // 250 kbaud in simulation; same production ELF.
    reg clk=0, rst=1, rx=1;
    wire tx;
    wire [1:0] led;
    always #10 clk=~clk;
    assign led[0]=0;
    // The unchanged MMCM/reset wrapper is covered by V1 and the actual A2 board.
    // Drive the production 50 MHz SoC directly to avoid redundant clock-model cost.
    riscv_soc #(.BAUD(250000)) dut (
        .clk(clk), .rst(rst), .uart_rxd(rx), .uart_txd(tx), .fault(led[1])
    );
    byte observed [0:65535];
    reg [7:0] sample;
    integer received=0, consumed=0, starts=0, buffer_writes=0;
    integer stimulus, results, rc, tx_count, rx_count, reset_before, value, transactions=0;
    integer dot_responses=0, boots=1, sum_n=0, expected_starts, expected_writes;
    integer scans=0, frame_writes=0, template_writes=0;
    integer expected_scans=0, expected_frames=0, expected_templates=0;
    integer legacy_windows=0;
    initial forever begin
        @(negedge tx);
        #(BIT_NS/2);
        if (tx !== 0) $fatal(1,"FAIL: false TX start");
        for (integer i=0;i<8;i=i+1) begin #BIT_NS; sample[i]=tx; end
        #BIT_NS;
        if (tx !== 1) $fatal(1,"FAIL: incorrect TX stop");
        if (received>=65536) $fatal(1,"FAIL: unexpected TX overflow");
        observed[received]=sample;
        received=received+1;
    end
    always @(posedge clk) begin
        if (!dut.rst) begin
            if (dut.u_window.access && |dut.wstrb) begin
                if (dut.addr==32'h20004000 && dut.wdata==1) scans++;
                if (dut.addr[13:12]==1) frame_writes++;
                if (dut.addr[13:12]==2) template_writes++;
            end
            if (led[1]) $fatal(1,"FAIL: CPU trap, MMIO fault or UART error");
            if (dut.u_accel.access && |dut.wstrb) begin
                if (dut.addr==32'h20000000 && dut.wdata==1) starts=starts+1;
                if (dut.addr[13:12]==1 || dut.addr[13:12]==2) buffer_writes=buffer_writes+1;
            end
        end
    end
    task send_byte(input reg [7:0] data);
        rx=0; #BIT_NS;
        for (integer i=0;i<8;i=i+1) begin rx=data[i]; #BIT_NS; end
        rx=1; #BIT_NS;
    endtask
    task reset_system;
        @(negedge clk); rst=1;
        repeat(10) @(negedge clk);
        rst=0;
        // Allow the unchanged boot RAM/math/CRC/MMIO self-test.
        #5_000_000;
    endtask
    initial begin
        stimulus=$fopen("stimulus.txt","r");
        results=$fopen("responses.jsonl","w");
        if (!stimulus || !results) $fatal(1,"FAIL: cannot open simulation data");
        reset_system();
        while (!$feof(stimulus)) begin
            rc=$fscanf(stimulus,"%d %d %d\n",tx_count,rx_count,reset_before);
            if (rc==3) begin
                if (reset_before) begin reset_system(); boots=boots+1; end
                for (integer i=0;i<tx_count;i=i+1) begin
                    rc=$fscanf(stimulus,"%h\n",value);
                    if (rc!=1) $fatal(1,"FAIL: malformed stimulus");
                    send_byte(value[7:0]);
                end
                wait (received>=consumed+rx_count);
                $fwrite(results,"{\"rx_hex\":\"");
                for (integer i=0;i<rx_count;i=i+1) $fwrite(results,"%02x",observed[consumed+i]);
                $fwrite(results,"\"}\n");
                if (observed[consumed+5]==8'h82) begin
                    dot_responses=dot_responses+1;
                    sum_n=sum_n+{observed[consumed+13],observed[consumed+12]};
                end
                if (observed[consumed+5]==8'h83 || observed[consumed+5]==8'h86 || observed[consumed+5]==8'h87 || observed[consumed+5]==8'h88 || observed[consumed+5]==8'h89) begin
                    expected_scans++;
                    expected_frames=expected_frames+{observed[consumed+13],observed[consumed+12]};
                    expected_templates=expected_templates+64*observed[consumed+24];
                end
                if (observed[consumed+5]==8'h85)
                    legacy_windows=legacy_windows+{observed[consumed+17],observed[consumed+16]};
                consumed=consumed+rx_count;
                transactions=transactions+1;
                #(BIT_NS*2);
                if (received!=consumed) $fatal(1,"FAIL: extra TX response");
                $display("SIM transaction %0d received",transactions);
            end else if (!$feof(stimulus)) $fatal(1,"FAIL: invalid stimulus header");
        end
        expected_starts=boots+dot_responses+legacy_windows;
        expected_writes=boots*6+sum_n*2+128*legacy_windows;
        if (starts!=expected_starts || buffer_writes!=expected_writes)
            $fatal(1,"FAIL: duplicated/missing MMIO writes: starts=%0d/%0d buffers=%0d/%0d",starts,expected_starts,buffer_writes,expected_writes);
        if (scans!=expected_scans || frame_writes!=expected_frames || template_writes!=expected_templates)
            $fatal(1,"FAIL: scanner MMIO count scans=%0d/%0d frames=%0d/%0d template=%0d/%0d",scans,expected_scans,frame_writes,expected_frames,template_writes,expected_templates);
        $display("PASS: scanner MMIO %0d STARTs %0d frame writes %0d template writes",scans,frame_writes,template_writes);
        $fclose(stimulus); $fclose(results);
        $display("PASS: integrated UART/CPU/MMIO simulation, %0d transactions, %0d STARTs, %0d buffer writes, %0d boots; Python checks follow",transactions,starts,buffer_writes,boots);
        $finish;
    end
    initial begin #(64'd6000000000); $fatal(1,"FAIL: integrated simulation timeout"); end
endmodule
