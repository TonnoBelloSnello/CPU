module ALU
    import cpu_pkg::*;
#(
    parameter DATA_WIDTH = 32
)(
    input  logic [DATA_WIDTH-1:0] a,
    input  logic [DATA_WIDTH-1:0] b,
    input  alu_op_t               opcode,
    input  logic                  carry_in,  // CPSR C flag, for ADC/SBC/RSC
    output logic [DATA_WIDTH-1:0] result,
    output logic                  zero,
    output logic                  negative,
    output logic                  carry,
    output logic                  overflow
);

    logic [DATA_WIDTH:0] temp;
    always @(*) begin
        carry    = 1'b0;
        overflow = 1'b0;
        temp     = '0;

        case (opcode)
            OP_AND, OP_TST: result = a & b;
            OP_EOR, OP_TEQ: result = a ^ b;
            OP_ORR:         result = a | b;
            OP_MOV:         result = b;
            OP_BIC:         result = a & ~b;
            OP_MVN:         result = ~b;
            OP_SUB, OP_CMP: begin
                temp     = {1'b0, a} - {1'b0, b};
                result   = temp[DATA_WIDTH-1:0];
                carry    = ~temp[DATA_WIDTH];
                overflow = (a[DATA_WIDTH-1] != b[DATA_WIDTH-1]) &&
                           (a[DATA_WIDTH-1] != result[DATA_WIDTH-1]);
            end
            OP_RSB: begin
                temp     = {1'b0, b} - {1'b0, a};
                result   = temp[DATA_WIDTH-1:0];
                carry    = ~temp[DATA_WIDTH];
                overflow = (b[DATA_WIDTH-1] != a[DATA_WIDTH-1]) &&
                           (b[DATA_WIDTH-1] != result[DATA_WIDTH-1]);
            end
            OP_ADD, OP_CMN: begin
                temp     = {1'b0, a} + {1'b0, b};
                result   = temp[DATA_WIDTH-1:0];
                carry    = temp[DATA_WIDTH];
                overflow = (a[DATA_WIDTH-1] == b[DATA_WIDTH-1]) &&
                           (a[DATA_WIDTH-1] != result[DATA_WIDTH-1]);
            end
            OP_ADC: begin
                temp     = {1'b0, a} + {1'b0, b} + {{DATA_WIDTH{1'b0}}, carry_in};
                result   = temp[DATA_WIDTH-1:0];
                carry    = temp[DATA_WIDTH];
                overflow = (a[DATA_WIDTH-1] == b[DATA_WIDTH-1]) &&
                           (a[DATA_WIDTH-1] != result[DATA_WIDTH-1]);
            end
            OP_SBC: begin
                temp     = {1'b0, a} - {1'b0, b} - {{DATA_WIDTH{1'b0}}, ~carry_in};
                result   = temp[DATA_WIDTH-1:0];
                carry    = ~temp[DATA_WIDTH];
                overflow = (a[DATA_WIDTH-1] != b[DATA_WIDTH-1]) &&
                           (a[DATA_WIDTH-1] != result[DATA_WIDTH-1]);
            end
            OP_RSC: begin
                temp     = {1'b0, b} - {1'b0, a} - {{DATA_WIDTH{1'b0}}, ~carry_in};
                result   = temp[DATA_WIDTH-1:0];
                carry    = ~temp[DATA_WIDTH];
                overflow = (b[DATA_WIDTH-1] != a[DATA_WIDTH-1]) &&
                           (b[DATA_WIDTH-1] != result[DATA_WIDTH-1]);
            end
            default: result = '0;
        endcase

        zero     = (result == '0);
        negative = result[DATA_WIDTH-1];
    end
endmodule
