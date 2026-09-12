module Decoder
    import cpu_pkg::*;
#(
    parameter DATA_WIDTH = 8,
    parameter ADDR_WIDTH = 24
) (
    input  logic                decode_instr,
    input  logic [ADDR_WIDTH-1:0] fetched_addr,
    input  logic [31:0]         instr_data,

    output cond_t               condition      = COND_EQ,
    output instr_class_t        instr_class    = CLASS_DP,
    output logic                immediate      = 1'b0,
    output logic [3:0]          opcode         = '0,
    output logic                flag           = 1'b0,
    output logic [3:0]          rn             = '0,
    output logic [3:0]          rd             = '0,
    output logic [11:0]         second_operand = '0
);

    always_comb begin
        condition      = COND_EQ;
        instr_class    = CLASS_DP;
        immediate      = 1'b0;
        opcode         = '0;
        flag           = 1'b0;
        rn             = '0;
        rd             = '0;
        second_operand = '0;

        if (decode_instr) begin
            condition      = cond_t'(instr_data[31:28]);
            instr_class    = instr_class_t'(instr_data[27:26]);
            immediate      = instr_data[25];
            opcode         = instr_data[24:21];
            flag           = instr_data[20];
            rn             = instr_data[19:16];
            rd             = instr_data[15:12];
            second_operand = instr_data[11:0];
        end
    end

endmodule
