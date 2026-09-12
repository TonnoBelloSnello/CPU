module Fetcher #(
    parameter DATA_WIDTH = 8, 
    parameter ADDR_WIDTH = 24
) (
    input wire clock,
    input wire fetch_instr,
    input wire redirect_en,
    input wire [ADDR_WIDTH-1:0] redirect_addr,
    
    input wire [ADDR_WIDTH-1:0] data_out_pc,
    output logic [ADDR_WIDTH-1:0] data_in_pc = '0,
    output logic [ADDR_WIDTH-1:0] fetched_addr = '0
);

    logic [ADDR_WIDTH-1:0] fetched_addr_r = '0;
    logic [ADDR_WIDTH-1:0] fetch_addr_next = '0;

    always_comb begin
        fetch_addr_next = redirect_en ? redirect_addr : data_out_pc;
        data_in_pc = fetch_addr_next + ADDR_WIDTH'(4);
        fetched_addr = fetch_instr ? fetch_addr_next : fetched_addr_r;
    end

    always_ff @(posedge clock) begin
        if (fetch_instr)
            fetched_addr_r <= fetch_addr_next;
    end
endmodule
