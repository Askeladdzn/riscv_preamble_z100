`timescale 1ns/1ps
module tb_window_accel;
    reg clk=0,rst=1,access=0;
    reg [13:0] addr=0;
    reg [31:0] wdata=0;
    reg [3:0] wstrb=0;
    wire [31:0] rdata;
    always #10 clk=~clk;
    window_accel dut(.*);
    integer vectors,rc,n,frames,expected_frames,windows=0,checks=0;
    integer samples[0:1023],expected_s[0:1023],expected_e[0:1023],template_values[0:63];
    reg [31:0] observed;
    task wr(input [13:0] a,input [31:0] d,input [3:0] st=4'hf);
        @(negedge clk);access=1;addr=a;wdata=d;wstrb=st;
        @(negedge clk);access=0;wstrb=0;
    endtask
    task rd(input [13:0] a,output [31:0] d);
        @(negedge clk);access=1;addr=a;wstrb=0;
        @(negedge clk);d=rdata;access=0;
    endtask
    task reset_dut;
        @(negedge clk);rst=1;repeat(3) @(negedge clk);rst=0;
        rd(4,observed);if(observed!=0) $fatal(1,"FAIL: reset status");
        rd('h14,observed);if(observed!=0) $fatal(1,"FAIL: template valid after reset");
    endtask
    task load_template;
        for(integer i=0;i<64;i++) wr('h2000+4*i,template_values[i]);
    endtask
    task load_frame(input integer len);
        wr(0,2);wr(8,len);
        for(integer i=0;i<len;i++) wr('h1000+4*i,samples[i]);
    endtask
    task check_error(input integer code);
        rd(4,observed);if(!(observed&4)) $fatal(1,"FAIL: error status missing %0d",code);
        rd(12,observed);if(observed!=code) $fatal(1,"FAIL: error code got %0d expected %0d",observed,code);
        checks++;
    endtask
    initial begin
        vectors=$fopen("unit_vectors.txt","r");
        if(!vectors) $fatal(1,"FAIL: no unit vectors");
        rc=$fscanf(vectors,"%d\n",expected_frames);
        for(integer i=0;i<64;i++) rc=$fscanf(vectors,"%d\n",template_values[i]);
        reset_dut();
        wr(0,1);check_error(1);wr(0,2);wr(8,1025);wr(0,1);check_error(1);
        wr(0,2);wr(8,64);wr(0,1);check_error(5);
        wr(0,2);wr('h1004,0);check_error(5);
        wr(0,2);wr('h1000,2048);check_error(6);
        wr(0,2);wr('h1000,32'hfffff7ff);check_error(6);
        wr(0,2);wr('h2000,0);check_error(6);
        wr(0,2);wr('h2001,1);check_error(4);
        wr(0,2);wr(8,64,4'h3);check_error(4);
        wr(0,2);wr('h0038,0);check_error(3);
        wr(0,2);wr('h0020,0);check_error(5);
        wr(0,2);load_template();
        for(integer i=0;i<1024;i++) samples[i]=i-512;
        load_frame(1024);wr(0,1);
        wr(0,1);check_error(2);wr(8,64);check_error(2);
        wr('h1000,0);check_error(2);wr('h2000,1);check_error(2);wr(0,2);check_error(2);
        wait(!dut.busy);rd(8,observed);if(observed!=1024) $fatal(1,"FAIL: busy changed length");
        rd('h2c,observed);if(observed!=1024) $fatal(1,"FAIL: busy changed frame count");
        load_frame(1024);wr(0,1);repeat(80) @(negedge clk);reset_dut();
        repeat(100) @(negedge clk);rd(4,observed);if(observed!=0) $fatal(1,"FAIL: stray commit after reset");
        load_template();
        for(frames=0;frames<expected_frames;frames++) begin
            rc=$fscanf(vectors,"%d\n",n);if(rc!=1) $fatal(1,"FAIL: frame length input");
            for(integer i=0;i<n;i++) begin
                rc=$fscanf(vectors,"%d\n",samples[i]);if(rc!=1) $fatal(1,"FAIL: sample input");
            end
            for(integer k=0;k<n-63;k++) begin
                rc=$fscanf(vectors,"%d %d\n",expected_s[k],expected_e[k]);
                if(rc!=2) $fatal(1,"FAIL: oracle input");
            end
            load_frame(n);wr(0,1);wait(!dut.busy);
            rd(4,observed);if(observed!=2) $fatal(1,"FAIL: completed status frame %0d",frames);
            rd('h18,observed);if(observed!=(n-63)*66) $fatal(1,"FAIL: core count %0d",observed);
            for(integer k=0;k<n-63;k++) begin
                wr('h20,k);rd('h24,observed);
                if($signed(observed)!=expected_s[k]) $fatal(1,"FAIL: score frame=%0d k=%0d got=%0d expected=%0d",frames,k,$signed(observed),expected_s[k]);
                rd('h28,observed);
                if(observed!=expected_e[k]) $fatal(1,"FAIL: energy frame=%0d k=%0d got=%0d expected=%0d",frames,k,observed,expected_e[k]);
                windows++;
            end
            if(frames%200==0) $display("UNIT %0d/%0d frames",frames,expected_frames);
        end
        wr('h20,n-63);check_error(5);
        $fclose(vectors);
        $display("PASS: window scanner %0d frames %0d windows %0d error checks; busy protection and reset recovery",frames,windows,checks);
        $finish;
    end
    initial begin #(64'd10000000000); $fatal(1,"FAIL: unit timeout"); end
endmodule
