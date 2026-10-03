`timescale 1ns/1ps
module tb_peak_selector;
    reg clk=0,rst=1,clear=0,valid=0,last=0;
    reg [9:0] index=0;
    reg signed [31:0] score=0;
    reg [31:0] energy=0;
    wire ready,done,detected;
    wire [31:0] position,candidate,best_score,best_energy;
    always #10 clk=~clk;
    peak_selector dut(.*);
    integer f,rc,cases,n,checked=0,total=0;
    reg [31:0] expected[0:4];
    task reset_dut;
        @(negedge clk);rst=1;valid=0;
        repeat(3) @(negedge clk);rst=0;
        if(done || detected || candidate!=32'hffffffff) $fatal(1,"FAIL: selector reset");
    endtask
    initial begin
        reset_dut();
        // Reset in each occupied pipeline stage must cancel pending results.
        for(integer stage=1;stage<=3;stage++) begin
            @(negedge clk);valid=1;last=1;score=-131072;energy=268435456;
            @(negedge clk);valid=0;
            repeat(stage-1) @(negedge clk);
            reset_dut();repeat(6) @(negedge clk);
            if(done) $fatal(1,"FAIL: stale completion after reset");
        end
        f=$fopen("selector_vectors.txt","r");if(!f) $fatal(1,"FAIL: no selector vectors");
        rc=$fscanf(f,"%d\n",cases);
        for(integer c=0;c<cases;c++) begin
            @(negedge clk);clear=1;
            @(negedge clk);clear=0;
            if(done || candidate!=32'hffffffff) $fatal(1,"FAIL: selector clear");
            rc=$fscanf(f,"%d\n",n);if(rc!=1) $fatal(1,"FAIL: vector length");
            for(integer k=0;k<n;k++) begin
                @(negedge clk);
                if(!ready) $fatal(1,"FAIL: no ready");
                rc=$fscanf(f,"%d %d\n",score,energy);if(rc!=2) $fatal(1,"FAIL: vector statistics");
                index=k;last=k==n-1;valid=1;
                @(negedge clk);valid=0;
                repeat(3) @(negedge clk);
                total++;
            end
            for(integer i=0;i<5;i++) rc=$fscanf(f,"%h\n",expected[i]);
            if(!done || detected!==expected[0][0] || position!==expected[1] || candidate!==expected[2] ||
               best_score!==expected[3] || best_energy!==expected[4])
                $fatal(1,"FAIL: selector case %0d got %0d/%h/%h/%h/%h",c,detected,position,candidate,best_score,best_energy);
            repeat(2) @(negedge clk);
            if(!done || position!==expected[1]) $fatal(1,"FAIL: result not held");
            checked++;
        end
        $fclose(f);
        $display("PASS: exact peak selector %0d cases %0d statistics; thresholds, ties, full-width products, clear and pipeline reset",checked,total);
        $finish;
    end
    initial begin #100000000; $fatal(1,"FAIL: selector timeout"); end
endmodule
