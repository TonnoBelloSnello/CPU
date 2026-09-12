module ProcessController
    import cpu_pkg::*;
(
    input  logic       clock,
    input  logic       reset,
    input  logic       loader_done,
    input  logic       halted,
    input  logic       exec_done,
    input  logic       exec_pc_write_en,
    input  logic [31:0] cpsr,

    input  cond_t        condition,
    input  instr_class_t instr_class,
    input  logic         immediate,
    input  logic [3:0]   opcode,
    input  logic         flag,
    input  logic [3:0]   rn,
    input  logic [3:0]   rd,
    input  logic [11:0]  second_operand,

    output logic         fetch_instr = 1'b0,
    output logic         decode_instr = 1'b0,
    output logic         exec_instr = 1'b0,
    output logic         branch_redirect_en = 1'b0,
    output logic [BR_TARGET_WIDTH-1:0] branch_redirect_operand = '0,

    output cond_t        ex_condition = COND_EQ,
    output instr_class_t ex_instr_class = CLASS_DP,
    output logic         ex_immediate = 1'b0,
    output logic         ex_flag = 1'b0,
    output logic [3:0]   ex_opcode = '0,
    output logic [3:0]   ex_rn = '0,
    output logic [3:0]   ex_rd = '0,
    output logic [11:0]  ex_second_operand = '0
);

    fd_state_t fd_state = FD_IDLE;

    logic ex_active = 1'b0;

    cond_t        ex_condition_r = COND_EQ;
    instr_class_t ex_instr_class_r = CLASS_DP;
    logic         ex_immediate_r = 1'b0;
    logic         ex_flag_r = 1'b0;
    logic [3:0]   ex_opcode_r = '0;
    logic [3:0]   ex_rn_r = '0;
    logic [3:0]   ex_rd_r = '0;
    logic [11:0]  ex_second_operand_r = '0;

    logic exec_slot_free;
    logic issue_from_decode;
    logic fetch_from_idle;
    logic fetch_from_decode;
    logic flush_pipeline;
    logic decode_branch_taken;

    function automatic logic is_control_flow_branch(input logic [3:0] op);
        case (br_op_t'(op))
            BR_ABS,
            BR_MAX,
            BR_MIN,
            BR_MADD,
            BR_PIXELNB,
            BR_WAITKNB,
            BR_QADD,
            BR_QSUB,
            BR_SSAT,
            BR_USAT,
            BR_QRDMULH,
            BR_RSHR,
            BR_RELU,
            BR_SXTB: return 1'b0;
            default: return 1'b1;
        endcase
    endfunction


    function automatic logic is_multi_cycle(
        input cond_t cond_in,
        input instr_class_t cls,
        input logic [3:0] rn_in,
        input logic [3:0] rd_in,
        input logic [3:0] op,
        input logic imm_in,
        input logic [11:0] sop_in
    );
        if (cond_in == COND_EQ
            && cls == CLASS_DP
            && !imm_in
            && op == 4'h0
            && rn_in == 4'h0
            && rd_in == 4'h0
            && sop_in == 12'h0)
            return 1'b1;

        if (cls == CLASS_MEM) begin
            case (mem_op_t'(op))
                MEM_STORE: return 1'b0;
                default:   return 1'b1;
            endcase
        end

        if (cls == CLASS_EXT) begin
            case (ext_op_t'(op))
                EXT_MUL,
                EXT_SETMA,
                EXT_SETMB,
                EXT_SETMR: return 1'b0;
                default:   return 1'b1;
            endcase
        end

        if (cls == CLASS_BR && br_op_t'(op) == BR_PIXELNB)
            return 1'b1;

        return 1'b0;
    endfunction

    always_comb begin
        exec_slot_free = !ex_active || exec_done;
        flush_pipeline = exec_pc_write_en;

        issue_from_decode = !flush_pipeline
            && !halted
            && (fd_state == FD_DECODE_DISPATCH)
            && exec_slot_free;

        decode_branch_taken = issue_from_decode
            && (instr_class == CLASS_BR)
            && is_control_flow_branch(opcode)
            && check_condition(condition, cpsr[31], cpsr[30], cpsr[29], cpsr[28]);
        branch_redirect_en = decode_branch_taken;
        branch_redirect_operand = decode_branch_taken ? {rn, rd, second_operand}
                                                      : BR_TARGET_WIDTH'(0);

        fetch_from_idle = !flush_pipeline
            && !halted
            && loader_done
            && (fd_state == FD_IDLE);

        fetch_from_decode = !flush_pipeline
            && !halted
            && loader_done
            && (fd_state == FD_DECODE_DISPATCH)
            && issue_from_decode;

        fetch_instr  = fetch_from_idle || fetch_from_decode;
        decode_instr = (fd_state == FD_DECODE_DISPATCH);
        exec_instr   = issue_from_decode;


        if (issue_from_decode) begin
            ex_condition      = condition;
            ex_instr_class    = instr_class;
            ex_immediate      = immediate;
            ex_flag           = flag;
            ex_opcode         = opcode;
            ex_rn             = rn;
            ex_rd             = rd;
            ex_second_operand = second_operand;
        end else begin
            ex_condition      = ex_condition_r;
            ex_instr_class    = ex_instr_class_r;
            ex_immediate      = ex_immediate_r;
            ex_flag           = ex_flag_r;
            ex_opcode         = ex_opcode_r;
            ex_rn             = ex_rn_r;
            ex_rd             = ex_rd_r;
            ex_second_operand = ex_second_operand_r;
        end
    end

    always_ff @(posedge clock) begin
        if (reset || halted || flush_pipeline) begin
            fd_state  <= FD_IDLE;
            ex_active <= 1'b0;
        end else begin
            if (issue_from_decode) begin
                ex_active           <= is_multi_cycle(condition, instr_class, rn, rd,
                                                      opcode, immediate, second_operand);
                ex_condition_r      <= condition;
                ex_instr_class_r    <= instr_class;
                ex_immediate_r      <= immediate;
                ex_flag_r           <= flag;
                ex_opcode_r         <= opcode;
                ex_rn_r             <= rn;
                ex_rd_r             <= rd;
                ex_second_operand_r <= second_operand;
            end else if (ex_active && exec_done) begin
                ex_active <= 1'b0;
            end

            case (fd_state)
                FD_IDLE: if (fetch_from_idle) fd_state <= FD_DECODE_DISPATCH;
                FD_DECODE_DISPATCH: ;
                default: fd_state <= FD_IDLE;
            endcase
        end
    end
endmodule
