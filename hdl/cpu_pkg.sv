package cpu_pkg;

    typedef enum logic [1:0] {
        CLASS_DP  = 2'b00,
        CLASS_EXT = 2'b01,
        CLASS_MEM = 2'b10,
        CLASS_BR  = 2'b11
    } instr_class_t;

    typedef enum logic [3:0] {
        OP_AND = 4'h0,
        OP_EOR = 4'h1,
        OP_SUB = 4'h2,
        OP_RSB = 4'h3,
        OP_ADD = 4'h4,
        OP_ADC = 4'h5,
        OP_SBC = 4'h6,
        OP_RSC = 4'h7,
        OP_TST = 4'h8,
        OP_TEQ = 4'h9,
        OP_CMP = 4'hA,
        OP_CMN = 4'hB,
        OP_ORR = 4'hC,
        OP_MOV = 4'hD,
        OP_BIC = 4'hE,
        OP_MVN = 4'hF
    } alu_op_t;

    typedef enum logic [3:0] {
        EXT_WAIT  = 4'h0,
        EXT_MUL   = 4'h1,
        EXT_SETMA = 4'h2,
        EXT_SETMB = 4'h3,
        EXT_SETMR = 4'h4,
        EXT_MMUL  = 4'h5,
        EXT_PIXEL = 4'h6,
        EXT_FADD  = 4'h7,
        EXT_FSUB  = 4'h8,
        EXT_FMUL  = 4'h9,
        EXT_FDIV  = 4'hA,
        EXT_FCMP  = 4'hB,
        EXT_FMOV  = 4'hC,
        EXT_WAITK = 4'hD,
        EXT_TEXT  = 4'hE,
        EXT_DIV   = 4'hF
    } ext_op_t;

    localparam int VGA_FB_WIDTH  = 160;
    localparam int VGA_FB_HEIGHT = 120;
    localparam int VGA_FB_SIZE   = VGA_FB_WIDTH * VGA_FB_HEIGHT;
    localparam int VGA_FB_ADDR_WIDTH = (VGA_FB_SIZE <= 1) ? 1 : $clog2(VGA_FB_SIZE);

    typedef enum logic [3:0] {
        MEM_NPU   = 4'h0,
        MEM_STORE_MULTI = 4'hA,
        MEM_LOAD_MULTI  = 4'hB,
        MEM_STORE = 4'hC,
        MEM_LOAD  = 4'hD,
        MEM_PUSH  = 4'hE,
        MEM_POP   = 4'hF
    } mem_op_t;

    typedef enum logic [3:0] {
        NPU_VLD    = 4'h0,
        NPU_VST    = 4'h1,
        NPU_VDOT   = 4'h2,
        NPU_VSUM   = 4'h3,
        NPU_VMAXR  = 4'h4,
        NPU_VDUP   = 4'h5,
        NPU_VEXT   = 4'h6,
        NPU_VINS   = 4'h7,
        NPU_ACLR   = 4'h8,
        NPU_ASET   = 4'h9,
        NPU_AGET   = 4'hA,
        NPU_AGETS  = 4'hB,
        NPU_AQMUL  = 4'hC,
        NPU_ARSHR  = 4'hD,
        NPU_NPUCFG = 4'hE,
        NPU_NPURUN = 4'hF
    } npu_op_t;

    localparam int NPU_LANES     = 8;
    localparam int NPU_VREGS     = 8;
    localparam int NPU_ACCS      = 4;
    localparam int NPU_VEC_WIDTH = NPU_LANES * 8;
    localparam int NPU_ACC_WIDTH = 32;
    localparam int NPU_LANE_SEL_WIDTH = $clog2(NPU_LANES);
    localparam int NPU_VREG_SEL_WIDTH = $clog2(NPU_VREGS);
    localparam int NPU_ACC_SEL_WIDTH  = $clog2(NPU_ACCS);

    localparam int NPU_PATCH_DEPTH = 512;
    localparam int NPU_PATCH_ADDR_WIDTH = $clog2(NPU_PATCH_DEPTH);

    typedef enum logic [4:0] {
        NPUC_MODE     = 5'd0,
        NPUC_FLAGS    = 5'd1,
        NPUC_IN_BASE  = 5'd2,
        NPUC_IN_W     = 5'd3,
        NPUC_IN_H     = 5'd4,
        NPUC_IN_C     = 5'd5,
        NPUC_W_BASE   = 5'd6,
        NPUC_B_BASE   = 5'd7,
        NPUC_OUT_BASE = 5'd8,
        NPUC_OUT_W    = 5'd9,
        NPUC_OUT_H    = 5'd10,
        NPUC_OUT_C    = 5'd11,
        NPUC_K_W      = 5'd12,
        NPUC_K_H      = 5'd13,
        NPUC_STRIDE   = 5'd14,
        NPUC_PAD      = 5'd15,
        NPUC_IN_ZP    = 5'd16,
        NPUC_OUT_ZP   = 5'd17,
        NPUC_MULT     = 5'd18,
        NPUC_SHIFT    = 5'd19,
        NPUC_ACT_MIN  = 5'd20,
        NPUC_ACT_MAX  = 5'd21,
        NPUC_ACC_BASE = 5'd22,
        NPUC_LUT_BASE = 5'd23
    } npu_cfg_t;

    localparam int NPU_CFG_COUNT = 24;

    localparam logic [3:0] NPU_MODE_CONV      = 4'd0;
    localparam logic [3:0] NPU_MODE_DEPTHWISE = 4'd1;
    localparam logic [3:0] NPU_MODE_MAXPOOL   = 4'd2;
    localparam logic [3:0] NPU_MODE_AVGPOOL   = 4'd3;
    localparam logic [3:0] NPU_MODE_LUT       = 4'd4;
    localparam logic [3:0] NPU_MODE_ARGMAX    = 4'd5;

    localparam int NPU_FLAG_ACC_IN  = 0;  // seed from the int32 buffer
    localparam int NPU_FLAG_ACC_OUT = 1;  // emit raw int32, skip requantization
    localparam int NPU_FLAG_NO_BIAS = 2;  // start from zero, ignore B_BASE

    localparam int NPU_ERR_OK    = 0;
    localparam int NPU_ERR_SHAPE = 1;  // a dimension is zero
    localparam int NPU_ERR_PATCH = 2;  // window exceeds the patch cache

    typedef enum logic [3:0] {
        BR_B    = 4'h0,
        BR_BL   = 4'h1,
        BR_ABS  = 4'h2,
        BR_MAX  = 4'h3,
        BR_MIN  = 4'h4,
        BR_MADD = 4'h5,
        BR_PIXELNB = 4'h6,
        BR_WAITKNB = 4'h7,
        BR_QADD    = 4'h8,
        BR_QSUB    = 4'h9,
        BR_SSAT    = 4'hA,
        BR_USAT    = 4'hB,
        BR_QRDMULH = 4'hC,
        BR_RSHR    = 4'hD,
        BR_RELU    = 4'hE,
        BR_SXTB    = 4'hF
    } br_op_t;

    localparam int BR_TARGET_WIDTH = 20;

    typedef enum logic [3:0] {
        COND_EQ = 4'h0,
        COND_NE = 4'h1,
        COND_CS = 4'h2,
        COND_CC = 4'h3,
        COND_MI = 4'h4,
        COND_PL = 4'h5,
        COND_VS = 4'h6,
        COND_VC = 4'h7,
        COND_HI = 4'h8,
        COND_LS = 4'h9,
        COND_GE = 4'hA,
        COND_LT = 4'hB,
        COND_GT = 4'hC,
        COND_LE = 4'hD,
        COND_AL = 4'hE,
        COND_NV = 4'hF
    } cond_t;

    function automatic bit check_condition(
        input cond_t cond,
        input bit n, z, c, v
    );
        case (cond)
            COND_EQ: return  z;
            COND_NE: return !z;
            COND_CS: return  c;
            COND_CC: return !c;
            COND_MI: return  n;
            COND_PL: return !n;
            COND_VS: return  v;
            COND_VC: return !v;
            COND_HI: return  c && !z;
            COND_LS: return !c ||  z;
            COND_GE: return (n == v);
            COND_LT: return (n != v);
            COND_GT: return !z && (n == v);
            COND_LE: return  z || (n != v);
            COND_AL: return 1;
            COND_NV: return 0;
            default: return 0;
        endcase
    endfunction

    localparam logic [3:0] REG_SP = 4'd13;
    localparam logic [3:0] REG_LR = 4'd14;
    localparam logic [3:0] REG_PC = 4'd15;
    localparam logic [3:0] REG_LE = 4'd15;  // aliases PC; write flag disambiguates
    localparam logic [3:0] REG_HEX = 4'd14;  // aliases LR; write flag disambiguates

    localparam int REG_COUNT = 15;

    localparam int RAM_ADDR_WIDTH = 16;  // RAM is 2^this bytes deep

    localparam int MMIO_WINDOW_BYTES = 256;
    localparam int MMIO_ADDR_BITS    = $clog2(MMIO_WINDOW_BYTES);
    localparam int MMIO_BASE         = (2**RAM_ADDR_WIDTH) - MMIO_WINDOW_BYTES;

    localparam int MMIO_OFF_LED       = 'h00;
    localparam int MMIO_OFF_HEX       = 'h04;
    localparam int MMIO_OFF_KEYS      = 'h08;  // pressed keys, active high
    localparam int MMIO_OFF_CYCLES_LO = 'h0C;
    localparam int MMIO_OFF_CYCLES_HI = 'h10;

    localparam int CLOCK_FREQ_HZ = 50_000_000;
    localparam int USE_SLOW_CLOCK = 0;
    localparam int SLOW_CLOCK_DIVISOR = 21;

    localparam int USE_INIT_FILE = 1;

    localparam int LOADER_MAX_PROGRAM_SIZE = 65280;

    typedef enum logic [4:0] {
        EX_IDLE,
        EX_WAITING,
        EX_WAIT_KEY,
        EX_HALT_DRAIN,
        EX_MEM_STORE,
        EX_MEM_LOAD_WAIT,       
        EX_MEM_STORE_MULTI,
        EX_MEM_LOAD_MULTI,
        EX_PIXEL_ENQUEUE_WAIT,
        EX_PIXEL_COMMIT_WAIT,
        EX_MAT_WAIT_A,          
        EX_MAT_WAIT_B,          
        EX_MEM_LOAD_SYNC,      
        EX_MEM_LOAD_MULTI_WAIT,
        EX_MAT_WAIT_A2,         
        EX_MAT_WAIT_B2,
        EX_FP_IMM_WAIT_LO,
        EX_FP_IMM_LATCH_LO,
        EX_FP_IMM_WAIT_HI,
        EX_FP_IMM_LATCH_HI,
        EX_TEXT_WAIT_CHAR,
        EX_TEXT_LATCH_CHAR,
        EX_TEXT_DRAW,
        EX_FP_START,
        EX_FP_DIV_WAIT,
        EX_FP_SETTLE,
        EX_DIV_START,
        EX_DIV_WAIT,
        EX_VEC_LOAD,
        EX_VEC_LOAD_WAIT,
        EX_VEC_STORE,
        EX_NPU_RUN
    } exec_state_t;

    typedef enum logic [1:0] {
        FD_IDLE,
        FD_DECODE_DISPATCH
    } fd_state_t;

endpackage
