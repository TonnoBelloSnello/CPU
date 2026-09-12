`include "executer_macros.svh"

module Executer
    import cpu_pkg::*;
#(
    parameter DATA_WIDTH = 32,
    parameter ADDR_WIDTH = 24,
    parameter CYCLES_PER_MS = 1
)(
    input  logic                clock,
    input  logic                reset,
    input  logic                execute_instr,

    input  cond_t               condition,
    input  instr_class_t        instr_class,
    input  logic                immediate,
    input  logic                flag,
    input  logic [3:0]          opcode,
    input  logic [3:0]          rn,
    input  logic [3:0]          rd,
    input  logic [11:0]         second_operand,
    input  logic [3:0]          key_n,
    input  logic [3:0]          key_jtag,

    input  logic                mmio_led_write,
    input  logic                mmio_hex_write,
    input  logic [DATA_WIDTH-1:0] mmio_display_byte,
    input  logic [1:0]          mmio_display_index,

    input  logic [ADDR_WIDTH-1:0] data_out_registers [REG_COUNT-1:0],
    input  logic [ADDR_WIDTH-1:0] data_out_pc,
    input  logic [31:0]           data_out_cpsr,
    output logic [ADDR_WIDTH-1:0] data_in_registers  [REG_COUNT-1:0],
    output logic [ADDR_WIDTH-1:0] data_in_pc   = '0,
    output logic [31:0]           data_in_cpsr = '0,
    output logic                  pc_write_en  = 1'b0,

    input  logic [ADDR_WIDTH-1:0] data_out_ledr,
    output logic [ADDR_WIDTH-1:0] data_in_ledr = '0,

    input  logic [ADDR_WIDTH-1:0] data_out_hex,
    output logic [ADDR_WIDTH-1:0] data_in_hex  = '0,

    output logic                  execute_done = 1'b0,
    output logic                  halted       = 1'b0,

    output logic [ADDR_WIDTH-1:0] ram_read_addr,
    output logic                  data_prefetch_valid,
    output logic [ADDR_WIDTH-1:0] data_prefetch_addr,
    input  logic [DATA_WIDTH-1:0] ram_data_out,
    output logic                  ram_write_en,
    output logic [ADDR_WIDTH-1:0] ram_write_addr,
    output logic [DATA_WIDTH-1:0] ram_write_data,

    output logic        vga_fb_write = 1'b0,
    output logic [VGA_FB_ADDR_WIDTH-1:0] vga_fb_addr  = '0,
    output logic [7:0]  vga_fb_data  = '0
);

    wire [ADDR_WIDTH-1:0] imm_ext      = {{(ADDR_WIDTH-12){1'b0}}, second_operand};
    wire [ADDR_WIDTH-1:0] ram_data_ext = {{(ADDR_WIDTH-DATA_WIDTH){1'b0}}, ram_data_out};
    wire [BR_TARGET_WIDTH-1:0] branch_target = {rn, rd, second_operand};
    wire [3:0]            op2_reg          = second_operand[3:0];
    wire                  op2_hex_source   = second_operand[4] && (second_operand[3:0] == REG_HEX);
    wire [1:0]            op2_shift_type   = second_operand[6:5];
    wire [4:0]            op2_shift_amount = second_operand[11:7];

    logic [ADDR_WIDTH-1:0] ram_read_addr_r  = '0;
    logic                  ram_write_en_r   = 1'b0;
    logic [ADDR_WIDTH-1:0] ram_write_addr_r = '0;
    logic [DATA_WIDTH-1:0] ram_write_data_r = '0;

    wire                   npu_busy;
    wire                   npu_done;
    wire [ADDR_WIDTH-1:0]  npu_result;
    wire [ADDR_WIDTH-1:0]  npu_mem_raddr;
    wire [ADDR_WIDTH-1:0]  npu_mem_waddr;
    wire                   npu_mem_write;
    wire [DATA_WIDTH-1:0]  npu_mem_wdata;

    assign ram_read_addr  = npu_busy ? npu_mem_raddr : ram_read_addr_r;
    assign ram_write_addr = npu_busy ? npu_mem_waddr : ram_write_addr_r;
    assign ram_write_data = npu_busy ? npu_mem_wdata : ram_write_data_r;
    assign ram_write_en   = npu_busy ? npu_mem_write : ram_write_en_r;

    logic                  npu_start     = 1'b0;
    logic                  npu_cfg_write = 1'b0;
    logic [4:0]            npu_cfg_index = '0;
    logic [ADDR_WIDTH-1:0] npu_cfg_value = '0;

    logic [31:0] wait_counter = '0;
    logic [31:0] wait_cycles  = '0;
    logic [3:0]  waitk_selected_mask = 4'hF;
    wire [3:0]   key_pressed_mask = ~key_n | key_jtag;
    wire [3:0]   waitk_hit_mask = key_pressed_mask & waitk_selected_mask;

    logic [3:0]            last_written_reg    = '0;
    logic [ADDR_WIDTH-1:0] last_written_value  = '0;
    logic                  last_write_valid    = 1'b0;
    logic [3:0]            last_written_reg2   = '0;
    logic [ADDR_WIDTH-1:0] last_written_value2 = '0;
    logic                  last_write2_valid   = 1'b0;
    logic                  stack_pop_active    = 1'b0;
    logic [ADDR_WIDTH-1:0] stack_addr          = '0;

    localparam int MEM_TRANSFER_BYTES = (ADDR_WIDTH + DATA_WIDTH - 1) / DATA_WIDTH;
    localparam int MEM_INDEX_WIDTH = (MEM_TRANSFER_BYTES <= 1) ? 1 : $clog2(MEM_TRANSFER_BYTES);
    function automatic [ADDR_WIDTH-1:0] merge_display_byte(
        input logic [ADDR_WIDTH-1:0] value,
        input logic [DATA_WIDTH-1:0] chunk,
        input logic [1:0]            index
    );
        merge_display_byte = value;
        for (int b = 0; b < MEM_TRANSFER_BYTES; b++)
            if (index == 2'(b))
                merge_display_byte[b*DATA_WIDTH +: DATA_WIDTH] = chunk;
    endfunction

    wire [ADDR_WIDTH-1:0] led_current = mmio_led_write
        ? merge_display_byte(data_in_ledr, mmio_display_byte, mmio_display_index)
        : data_out_ledr;
    wire [ADDR_WIDTH-1:0] hex_current = mmio_hex_write
        ? merge_display_byte(data_in_hex, mmio_display_byte, mmio_display_index)
        : data_out_hex;

    logic [ADDR_WIDTH-1:0] mem_multi_addr      = '0;
    logic [ADDR_WIDTH-1:0] mem_multi_value     = '0;
    logic [MEM_INDEX_WIDTH-1:0] mem_multi_index = '0;
    logic                  mem_multi_pending    = 1'b0;
    logic [ADDR_WIDTH-1:0] fp_imm_addr          = '0;
    logic [7:0]            fp_imm_lo            = '0;
    logic [15:0]           fp_imm_value         = '0;
    localparam int FP_CACHE_ENTRIES = 2;
    logic [FP_CACHE_ENTRIES-1:0] fp_cache_valid = '0;
    logic [ADDR_WIDTH-1:0] fp_cache_addr [0:FP_CACHE_ENTRIES-1];
    logic [15:0]           fp_cache_value [0:FP_CACHE_ENTRIES-1];
    logic                  fp_cache_replace = 1'b0;

    wire [31:0] effective_cpsr = data_in_cpsr;
    wire flag_n = effective_cpsr[31];
    wire flag_z = effective_cpsr[30];
    wire flag_c = effective_cpsr[29];
    wire flag_v = effective_cpsr[28];
    wire condition_met = check_condition(condition, flag_n, flag_z, flag_c, flag_v);

    function automatic [ADDR_WIDTH-1:0] get_reg_value(input logic [3:0] reg_num);
        if (reg_num >= REG_COUNT) return '0;
        if (last_write_valid  && reg_num == last_written_reg)  return last_written_value;
        if (last_write2_valid && reg_num == last_written_reg2) return last_written_value2;
        return data_out_registers[reg_num];
    endfunction

    localparam int REGISTER_WIDTH = 4;
    localparam logic [REGISTER_WIDTH-1:0] MAT_ONE = 1;
    logic [ADDR_WIDTH-1:0] mar_a      = '0;
    logic [ADDR_WIDTH-1:0] mar_b      = '0;
    logic [ADDR_WIDTH-1:0] mar_r      = '0;
    logic [3:0]            mat_rows_a = '0;
    logic [3:0]            mat_cols_a = '0;
    logic [3:0]            mat_cols_b = '0;
    logic [3:0]            mat_i      = '0;
    logic [3:0]            mat_j      = '0;
    logic [3:0]            mat_k      = '0;
    logic [3:0]            mat_preload_k = '0;
    localparam int MAT_CACHE_ENTRIES = 16;
    logic [DATA_WIDTH-1:0] mat_a_row_cache [0:MAT_CACHE_ENTRIES-1];
    logic [31:0]           mat_accum  = '0;
    logic [ADDR_WIDTH-1:0] a_row_base = '0;
    logic [ADDR_WIDTH-1:0] b_col_base = '0;
    logic [ADDR_WIDTH-1:0] b_k_offset = '0;
    logic [ADDR_WIDTH-1:0] r_row_base = '0;

    logic [NPU_VEC_WIDTH-1:0]        vreg     [0:NPU_VREGS-1];
    logic signed [NPU_ACC_WIDTH-1:0] acc_file [0:NPU_ACCS-1];

    logic [ADDR_WIDTH-1:0]         vec_addr   = '0;
    logic [NPU_LANE_SEL_WIDTH:0]   vec_index  = '0;
    logic [NPU_VREG_SEL_WIDTH-1:0] vec_target = '0;
    logic [NPU_VEC_WIDTH-1:0]      vec_value  = '0;

    wire [3:0] npu_op    = rn;
    wire [2:0] npu_sel_a = second_operand[2:0];
    wire [2:0] npu_sel_b = second_operand[5:3];
    wire [2:0] npu_lane  = second_operand[6:4];
    wire [3:0] npu_src   = second_operand[3:0];
    wire [1:0] npu_acc_a = second_operand[1:0];
    wire [NPU_VREG_SEL_WIDTH-1:0] npu_vd      = rd[NPU_VREG_SEL_WIDTH-1:0];
    wire [NPU_ACC_SEL_WIDTH-1:0]  npu_ad      = rd[NPU_ACC_SEL_WIDTH-1:0];
    wire [4:0]                    npu_cfg_sel = {flag, rd};

    localparam int SAT_W  = ADDR_WIDTH + 1;
    localparam int QMUL_W = (2 * ADDR_WIDTH) + 2;
    localparam logic signed [ADDR_WIDTH-1:0] SAT_MAX = {1'b0, {(ADDR_WIDTH-1){1'b1}}};
    localparam logic signed [ADDR_WIDTH-1:0] SAT_MIN = {1'b1, {(ADDR_WIDTH-1){1'b0}}};
    localparam logic signed [48:0] ACC_SAT_MAX =  49'sd2147483647;
    localparam logic signed [48:0] ACC_SAT_MIN = -49'sd2147483648;

    function automatic logic [ADDR_WIDTH-1:0] saturate_wide(
        input logic signed [SAT_W-1:0] value
    );
        logic signed [SAT_W-1:0] hi;
        logic signed [SAT_W-1:0] lo;
        begin
            hi = {1'b0, SAT_MAX};
            lo = {SAT_MIN[ADDR_WIDTH-1], SAT_MIN};
            if (value > hi)      saturate_wide = SAT_MAX;
            else if (value < lo) saturate_wide = SAT_MIN;
            else                 saturate_wide = value[ADDR_WIDTH-1:0];
        end
    endfunction

    function automatic logic [ADDR_WIDTH-1:0] saturate_acc(
        input logic signed [31:0] value
    );
        logic signed [31:0] hi;
        logic signed [31:0] lo;
        begin
            hi = {{(32-ADDR_WIDTH){1'b0}}, SAT_MAX};
            lo = {{(32-ADDR_WIDTH){1'b1}}, SAT_MIN};
            if (value > hi)      saturate_acc = SAT_MAX;
            else if (value < lo) saturate_acc = SAT_MIN;
            else                 saturate_acc = value[ADDR_WIDTH-1:0];
        end
    endfunction

    function automatic logic [ADDR_WIDTH-1:0] saturate_signed_bits(
        input logic signed [ADDR_WIDTH-1:0] value,
        input logic [4:0]                   bits
    );
        logic signed [SAT_W-1:0] hi;
        logic signed [SAT_W-1:0] lo;
        logic signed [SAT_W-1:0] wide;
        begin
            wide = {value[ADDR_WIDTH-1], value};
            if ((bits == 5'd0) || (bits >= 5'(ADDR_WIDTH))) begin
                saturate_signed_bits = value;
            end else begin
                hi = (SAT_W'(1) <<< (bits - 5'd1)) - SAT_W'(1);
                lo = -(SAT_W'(1) <<< (bits - 5'd1));
                if (wide > hi)      saturate_signed_bits = hi[ADDR_WIDTH-1:0];
                else if (wide < lo) saturate_signed_bits = lo[ADDR_WIDTH-1:0];
                else                saturate_signed_bits = value;
            end
        end
    endfunction

    function automatic logic [ADDR_WIDTH-1:0] saturate_unsigned_bits(
        input logic signed [ADDR_WIDTH-1:0] value,
        input logic [4:0]                   bits
    );
        logic signed [SAT_W-1:0] hi;
        logic signed [SAT_W-1:0] wide;
        begin
            wide = {value[ADDR_WIDTH-1], value};
            if (bits == 5'd0) begin
                saturate_unsigned_bits = '0;
            end else if (wide < 0) begin
                saturate_unsigned_bits = '0;
            end else if (bits >= 5'(ADDR_WIDTH)) begin
                saturate_unsigned_bits = value;
            end else begin
                hi = (SAT_W'(1) <<< bits) - SAT_W'(1);
                if (wide > hi) saturate_unsigned_bits = hi[ADDR_WIDTH-1:0];
                else           saturate_unsigned_bits = value;
            end
        end
    endfunction

    function automatic logic [ADDR_WIDTH-1:0] qrdmulh(
        input logic signed [ADDR_WIDTH-1:0] a,
        input logic signed [ADDR_WIDTH-1:0] b
    );
        logic signed [QMUL_W-1:0] wa;
        logic signed [QMUL_W-1:0] wb;
        logic signed [QMUL_W-1:0] rounded;
        logic signed [SAT_W-1:0]  narrowed;
        begin
            wa       = {{(QMUL_W-ADDR_WIDTH){a[ADDR_WIDTH-1]}}, a};
            wb       = {{(QMUL_W-ADDR_WIDTH){b[ADDR_WIDTH-1]}}, b};
            rounded  = ((wa * wb) <<< 1) + (QMUL_W'(1) <<< (ADDR_WIDTH - 1));
            narrowed = rounded >>> ADDR_WIDTH;
            qrdmulh  = saturate_wide(narrowed);
        end
    endfunction

    function automatic logic [ADDR_WIDTH-1:0] rounding_shift(
        input logic signed [ADDR_WIDTH-1:0] value,
        input logic [4:0]                   amount
    );
        logic signed [31:0] wide;
        logic signed [31:0] shifted;
        logic [31:0] mask;
        logic [31:0] remainder;
        logic [31:0] threshold;
        begin
            if (amount == 5'd0) begin
                rounding_shift = value;
            end else begin
                wide      = {{(32-ADDR_WIDTH){value[ADDR_WIDTH-1]}}, value};
                mask      = (32'd1 << amount) - 32'd1;
                remainder = wide & mask;
                threshold = (mask >> 1) + (wide[31] ? 32'd1 : 32'd0);
                shifted   = wide >>> amount;
                if (remainder > threshold) shifted = shifted + 32'sd1;
                rounding_shift = shifted[ADDR_WIDTH-1:0];
            end
        end
    endfunction

    function automatic logic [ADDR_WIDTH-1:0] relu_clamp(
        input logic signed [ADDR_WIDTH-1:0] value,
        input logic signed [ADDR_WIDTH-1:0] upper
    );
        logic signed [ADDR_WIDTH-1:0] floored;
        begin
            floored = (value < 0) ? '0 : value;
            if ((upper != 0) && (floored > upper)) relu_clamp = upper;
            else                                   relu_clamp = floored;
        end
    endfunction

    function automatic logic signed [31:0] vector_dot(
        input logic [NPU_VEC_WIDTH-1:0] va,
        input logic [NPU_VEC_WIDTH-1:0] vb
    );
        logic signed [7:0]  la;
        logic signed [7:0]  lb;
        logic signed [15:0] prod;
        logic signed [31:0] sum;
        begin
            sum = 32'sd0;
            for (int l = 0; l < NPU_LANES; l++) begin
                la   = va[l*8 +: 8];
                lb   = vb[l*8 +: 8];
                prod = la * lb;
                sum  = sum + {{16{prod[15]}}, prod};
            end
            vector_dot = sum;
        end
    endfunction

    function automatic logic signed [31:0] vector_sum(
        input logic [NPU_VEC_WIDTH-1:0] va
    );
        logic signed [7:0]  la;
        logic signed [31:0] sum;
        begin
            sum = 32'sd0;
            for (int l = 0; l < NPU_LANES; l++) begin
                la  = va[l*8 +: 8];
                sum = sum + {{24{la[7]}}, la};
            end
            vector_sum = sum;
        end
    endfunction

    function automatic logic signed [7:0] vector_max(
        input logic [NPU_VEC_WIDTH-1:0] va
    );
        logic signed [7:0] la;
        logic signed [7:0] best;
        begin
            best = va[7:0];
            for (int l = 1; l < NPU_LANES; l++) begin
                la = va[l*8 +: 8];
                if (la > best) best = la;
            end
            vector_max = best;
        end
    endfunction

    function automatic logic signed [31:0] acc_qmul(
        input logic signed [31:0] value,
        input logic signed [15:0] multiplier
    );
        logic signed [48:0] scaled;
        begin
            scaled = ({{17{value[31]}}, value} * {{33{multiplier[15]}}, multiplier})
                     + 49'sd16384;
            scaled = scaled >>> 15;
            if (scaled > ACC_SAT_MAX)      acc_qmul = 32'sh7FFFFFFF;
            else if (scaled < ACC_SAT_MIN) acc_qmul = 32'sh80000000;
            else                           acc_qmul = scaled[31:0];
        end
    endfunction

    function automatic logic signed [31:0] acc_rounding_shift(
        input logic signed [31:0] value,
        input logic [4:0]         amount
    );
        logic [31:0] mask;
        logic [31:0] remainder;
        logic [31:0] threshold;
        logic signed [31:0] shifted;
        begin
            if (amount == 5'd0) begin
                acc_rounding_shift = value;
            end else begin
                mask      = (32'd1 << amount) - 32'd1;
                remainder = value & mask;
                threshold = (mask >> 1) + (value[31] ? 32'd1 : 32'd0);
                shifted   = value >>> amount;
                acc_rounding_shift = (remainder > threshold) ? (shifted + 32'sd1)
                                                             : shifted;
            end
        end
    endfunction

    wire [DATA_WIDTH-1:0] mat_a_cached = mat_a_row_cache[mat_k];
    wire [31:0] mat_elem_product = {{(32-DATA_WIDTH){1'b0}}, mat_a_cached} *
                                   {{(32-DATA_WIDTH){1'b0}}, ram_data_out};
    wire [31:0] mat_accum_next   = mat_accum + mat_elem_product;
    localparam int TEXT_GLYPH_HEIGHT = 7;
    localparam int TEXT_GLYPH_WIDTH = 5;
    localparam int TEXT_GLYPH_ADVANCE = 6;
    localparam int TEXT_MAX_RENDER_CHARS = 16;

    logic [ADDR_WIDTH-1:0] text_base_x = '0;
    logic [ADDR_WIDTH-1:0] text_base_y = '0;
    logic [ADDR_WIDTH-1:0] text_char_x_base = '0;
    logic [ADDR_WIDTH-1:0] text_ptr = '0;
    logic [7:0]            text_char_code = '0;
    logic [7:0]            text_color = '0;
    logic [4:0]            text_char_count = '0;
    logic [2:0]            text_row = '0;
    logic [2:0]            text_col = '0;

    localparam int PIXEL_QUEUE_DEPTH = 16;
    localparam int PIXEL_QUEUE_INDEX_WIDTH = (PIXEL_QUEUE_DEPTH <= 1) ? 1 : $clog2(PIXEL_QUEUE_DEPTH);
    localparam int PIXEL_QUEUE_COUNT_WIDTH = PIXEL_QUEUE_INDEX_WIDTH + 1;
    logic [VGA_FB_ADDR_WIDTH-1:0] pixel_queue_addr [0:PIXEL_QUEUE_DEPTH-1];
    logic [7:0]                   pixel_queue_data [0:PIXEL_QUEUE_DEPTH-1];
    logic [PIXEL_QUEUE_INDEX_WIDTH-1:0] pixel_queue_head = '0;
    logic [PIXEL_QUEUE_INDEX_WIDTH-1:0] pixel_queue_tail = '0;
    logic [PIXEL_QUEUE_COUNT_WIDTH-1:0] pixel_queue_count = '0;
    logic [VGA_FB_ADDR_WIDTH-1:0] pending_fb_addr = '0;
    logic [7:0]                   pending_fb_data = '0;
    logic [ADDR_WIDTH-1:0]        pending_fb_x = '0;
    logic [ADDR_WIDTH-1:0]        pending_fb_y = '0;
    logic                         pixel_blocking = 1'b0;
    logic                         halt_pending = 1'b0;
    logic                         fb_write_pending = 1'b0;

    initial begin
        for (int j = 0; j < REG_COUNT; j++) data_in_registers[j] = '0;
        data_in_registers[REG_SP] = ADDR_WIDTH'(MMIO_BASE);
        for (int m = 0; m < MAT_CACHE_ENTRIES; m++) mat_a_row_cache[m] = '0;
        for (int c = 0; c < FP_CACHE_ENTRIES; c++) begin
            fp_cache_addr[c]  = '0;
            fp_cache_value[c] = '0;
        end
        for (int q = 0; q < PIXEL_QUEUE_DEPTH; q++) begin
            pixel_queue_addr[q] = '0;
            pixel_queue_data[q] = '0;
        end
        for (int v = 0; v < NPU_VREGS; v++) vreg[v] = '0;
        for (int a = 0; a < NPU_ACCS; a++)  acc_file[a] = '0;
    end

    exec_state_t state = EX_IDLE;


    function automatic [ADDR_WIDTH-1:0] read_operand(input logic [3:0] reg_num);
        return (reg_num == REG_LE) ? led_current : get_reg_value(reg_num);
    endfunction

    function automatic [ADDR_WIDTH-1:0] read_rd_operand();
        return (rd == REG_HEX && flag) ? hex_current : read_operand(rd);
    endfunction

    wire [TEXT_GLYPH_WIDTH-1:0] text_glyph_row_bits;

    text_glyph_rom text_font (
        .ascii_char(text_char_code),
        .row(text_row),
        .row_bits(text_glyph_row_bits)
    );

    wire [ADDR_WIDTH-1:0] op2_raw_value;
    wire [ADDR_WIDTH-1:0] op2_shifted_value;
    logic [ADDR_WIDTH-1:0] fp_op_a_full = '0;
    logic [15:0]          fp_op_a_value = '0;
    logic [15:0]          fp_op_b_value = '0;
    logic [1:0]           fp_unit_op = '0;
    wire [15:0]           fp_unit_result;
    wire                  fp_cmp_eq;
    wire                  fp_cmp_lt;
    wire                  fp_cmp_gt;
    wire                  fp_cmp_unordered;
    wire                  fp_imm_cache_hit = immediate &&
                                             ((fp_cache_valid[0] && (fp_cache_addr[0] == imm_ext)) ||
                                              (fp_cache_valid[1] && (fp_cache_addr[1] == imm_ext)));

    localparam int FP_SETTLE_CYCLES = 1;  // must match the CPUFrFr.sdc multicycle

    localparam int DIV_RADIX_BITS       = 2;
    localparam int DIV_SKIP_GRANULARITY = 4;
    localparam int FP_DIV_NUM_WIDTH     = 27;
    localparam int DIV_NUM_MIN   = (ADDR_WIDTH > FP_DIV_NUM_WIDTH) ? ADDR_WIDTH
                                                                   : FP_DIV_NUM_WIDTH;
    localparam int DIV_NUM_WIDTH = ((DIV_NUM_MIN + DIV_SKIP_GRANULARITY - 1)
                                    / DIV_SKIP_GRANULARITY) * DIV_SKIP_GRANULARITY;
    localparam int DIV_DEN_WIDTH = (ADDR_WIDTH > 16) ? ADDR_WIDTH : 16;

    logic [15:0]          fp_a_r = '0;
    logic [15:0]          fp_b_r = '0;
    logic [1:0]           fp_op_r = '0;
    logic [2:0]           fp_settle_count = '0;

    wire [FP_DIV_NUM_WIDTH-1:0] fp_div_num;
    wire [15:0]                 fp_div_den;

    logic                 div_start  = 1'b0;
    logic                 div_for_fp = 1'b0;
    logic [ADDR_WIDTH-1:0] div_a_r = '0;
    logic [ADDR_WIDTH-1:0] div_b_r = '0;
    wire [DIV_NUM_WIDTH-1:0] div_numerator   = div_for_fp ? DIV_NUM_WIDTH'(fp_div_num)
                                                          : DIV_NUM_WIDTH'(div_a_r);
    wire [DIV_DEN_WIDTH-1:0] div_denominator = div_for_fp ? DIV_DEN_WIDTH'(fp_div_den)
                                                          : DIV_DEN_WIDTH'(div_b_r);
    wire [DIV_NUM_WIDTH-1:0] div_quotient;
    wire                     div_rem_nonzero;
    wire                     div_busy;
    wire                     div_done;

    wire [ADDR_WIDTH-1:0] fp_unit_result_ext = {{(ADDR_WIDTH-16){1'b0}}, fp_unit_result};
    wire [ADDR_WIDTH-1:0] fp_mov_result_ext  = {{(ADDR_WIDTH-16){1'b0}}, fp_b_r};

    wire [ADDR_WIDTH-1:0] op2_forwarded_value =
        (op2_reg >= REG_COUNT)                                ? '0                   :
        (last_write_valid  && (op2_reg == last_written_reg))   ? last_written_value   :
        (last_write2_valid && (op2_reg == last_written_reg2))  ? last_written_value2  :
                                                                 data_out_registers[op2_reg];

    assign op2_raw_value = (op2_reg == REG_LE) ? led_current :
                           (op2_hex_source ? hex_current : op2_forwarded_value);

    always_comb begin
        fp_op_a_full = read_operand(rn);
        fp_op_a_value = fp_op_a_full[15:0];
        if (immediate) begin
            if (fp_imm_cache_hit && fp_cache_valid[0] && (fp_cache_addr[0] == imm_ext))
                fp_op_b_value = fp_cache_value[0];
            else if (fp_imm_cache_hit && fp_cache_valid[1] && (fp_cache_addr[1] == imm_ext))
                fp_op_b_value = fp_cache_value[1];
            else
                fp_op_b_value = fp_imm_value;
        end else begin
            fp_op_b_value = op2_raw_value[15:0];
        end
        fp_unit_op = (opcode == EXT_FSUB) ? 2'b01 :
                     (opcode == EXT_FMUL) ? 2'b10 :
                     (opcode == EXT_FDIV) ? 2'b11 :
                     2'b00;
    end

    BarrelShifter #(
        .DATA_WIDTH(ADDR_WIDTH)
    ) operand2_barrel_shifter (
        .value(op2_raw_value),
        .shift_type(op2_shift_type),
        .shift_amount(op2_shift_amount),
        .shifted(op2_shifted_value)
    );

    wire [15:0] fp_core_a;
    wire [15:0] fp_core_b;
    wire [1:0]  fp_core_op;
    wire [17:0] fp_core_div_q;
    wire        fp_core_div_rem_nonzero;

    `ifdef WEB_FAST_SIMULATION
        wire fp_core_active = (state == EX_FP_START) ||
                              (state == EX_FP_DIV_WAIT) ||
                              (state == EX_FP_SETTLE);
        assign fp_core_a = fp_core_active ? fp_a_r : 16'd0;
        assign fp_core_b = fp_core_active ? fp_b_r : 16'd0;
        assign fp_core_op = fp_core_active ? fp_op_r : 2'b00;
        assign fp_core_div_q = (state == EX_FP_SETTLE) ? div_quotient[17:0] : 18'd0;
        assign fp_core_div_rem_nonzero = (state == EX_FP_SETTLE) ? div_rem_nonzero : 1'b0;
    `else
        assign fp_core_a = fp_a_r;
        assign fp_core_b = fp_b_r;
        assign fp_core_op = fp_op_r;
        assign fp_core_div_q = div_quotient[17:0];
        assign fp_core_div_rem_nonzero = div_rem_nonzero;
    `endif

    fp16_unit fp16_core (
        .a(fp_core_a),
        .b(fp_core_b),
        .op(fp_core_op),
        .result(fp_unit_result),
        .cmp_eq(fp_cmp_eq),
        .cmp_lt(fp_cmp_lt),
        .cmp_gt(fp_cmp_gt),
        .cmp_unordered(fp_cmp_unordered),
        .div_num(fp_div_num),
        .div_den(fp_div_den),
        .div_q(fp_core_div_q),
        .div_rem_nonzero(fp_core_div_rem_nonzero)
    );

    divider_seq #(
        .NUM_WIDTH(DIV_NUM_WIDTH),
        .DEN_WIDTH(DIV_DEN_WIDTH),
        .RADIX_BITS(DIV_RADIX_BITS),
        .SKIP_GRANULARITY(DIV_SKIP_GRANULARITY)
    ) divider (
        .clock(clock),
        .reset(reset),
        .start(div_start),
        .numerator(div_numerator),
        .denominator(div_denominator),
        .quotient(div_quotient),
        .rem_nonzero(div_rem_nonzero),
        .busy(div_busy),
        .done(div_done)
    );

    NPU #(
        .DATA_WIDTH(DATA_WIDTH),
        .ADDR_WIDTH(ADDR_WIDTH)
    ) tensor_engine (
        .clock(clock),
        .reset(reset),
        .cfg_write(npu_cfg_write),
        .cfg_index(npu_cfg_index),
        .cfg_value(npu_cfg_value),
        .start(npu_start),
        .busy(npu_busy),
        .done(npu_done),
        .result(npu_result),
        .mem_raddr(npu_mem_raddr),
        .mem_waddr(npu_mem_waddr),
        .mem_write(npu_mem_write),
        .mem_wdata(npu_mem_wdata),
        .mem_rdata(ram_data_out)
    );

    wire [ADDR_WIDTH-1:0] operand_b = immediate ? imm_ext : op2_shifted_value;

    wire [3:0] waitk_mask_now = (operand_b[3:0] != 4'b0000) ? operand_b[3:0] : 4'hF;
    wire [3:0] waitk_hit_now  = key_pressed_mask & waitk_mask_now;

    logic [ADDR_WIDTH-1:0] dp_alu_a;
    wire [ADDR_WIDTH-1:0] dp_alu_result;
    wire                  dp_alu_zero;
    wire                  dp_alu_negative;
    wire                  dp_alu_carry;
    wire                  dp_alu_overflow;

    always_comb dp_alu_a = read_operand(rn);

    ALU #(
        .DATA_WIDTH(ADDR_WIDTH)
    ) data_processing_alu (
        .a(dp_alu_a),
        .b(operand_b),
        .opcode(alu_op_t'(opcode)),
        .carry_in(flag_c),
        .result(dp_alu_result),
        .zero(dp_alu_zero),
        .negative(dp_alu_negative),
        .carry(dp_alu_carry),
        .overflow(dp_alu_overflow)
    );

    wire [ADDR_WIDTH-1:0] resolved_mem_addr = immediate ? imm_ext : op2_raw_value;

    always_comb begin
        data_prefetch_valid = 1'b0;
        data_prefetch_addr  = ram_read_addr_r;

        if (state == EX_IDLE && execute_instr && !halted && condition_met && !ram_write_en_r) begin
            if (instr_class == CLASS_MEM) begin
                case (mem_op_t'(opcode))
                    MEM_POP: begin
                        data_prefetch_valid = 1'b1;
                        data_prefetch_addr  = get_reg_value(REG_SP);
                    end

                    MEM_LOAD,
                    MEM_LOAD_MULTI: begin
                        data_prefetch_valid = 1'b1;
                        data_prefetch_addr  = resolved_mem_addr;
                    end

                    MEM_NPU: begin
                        data_prefetch_valid = (npu_op_t'(rn) == NPU_VLD);
                        data_prefetch_addr  = resolved_mem_addr;
                    end

                    default: begin
                        data_prefetch_valid = 1'b0;
                    end
                endcase
            end else if (instr_class == CLASS_EXT && immediate && !fp_imm_cache_hit) begin
                case (ext_op_t'(opcode))
                    EXT_FADD,
                    EXT_FSUB,
                    EXT_FMUL,
                    EXT_FDIV,
                    EXT_FCMP,
                    EXT_FMOV: begin
                        data_prefetch_valid = 1'b1;
                        data_prefetch_addr  = imm_ext;
                    end

                    default: begin
                        data_prefetch_valid = 1'b0;
                    end
                endcase
            end
        end else if (state == EX_FP_IMM_LATCH_LO && !ram_write_en_r) begin
            data_prefetch_valid = 1'b1;
            data_prefetch_addr  = fp_imm_addr + ADDR_WIDTH'(1);
        end else if (state == EX_MEM_LOAD_MULTI && !ram_write_en_r) begin
            if ((mem_multi_index + 1'b1) < MEM_TRANSFER_BYTES) begin
                data_prefetch_valid = 1'b1;
                data_prefetch_addr  = mem_multi_addr + ADDR_WIDTH'(mem_multi_index) + ADDR_WIDTH'(1);
            end
        end else if (state == EX_VEC_LOAD && !ram_write_en_r) begin
            if ((vec_index + 1'b1) < NPU_LANES) begin
                data_prefetch_valid = 1'b1;
                data_prefetch_addr  = vec_addr + ADDR_WIDTH'(vec_index) + ADDR_WIDTH'(1);
            end
        end else if (state == EX_MAT_WAIT_A2 && !ram_write_en_r) begin
            if (mat_preload_k + MAT_ONE < mat_cols_a) begin
                data_prefetch_valid = 1'b1;
                data_prefetch_addr  = a_row_base + ADDR_WIDTH'(mat_preload_k) + ADDR_WIDTH'(1);
            end
        end else if (state == EX_MAT_WAIT_B2 && !ram_write_en_r) begin
            if (mat_k + MAT_ONE < mat_cols_a) begin
                data_prefetch_valid = 1'b1;
                data_prefetch_addr  = b_col_base + b_k_offset + ADDR_WIDTH'(mat_cols_b);
            end
        end
    end

    function automatic [VGA_FB_ADDR_WIDTH-1:0] vga_addr_from_xy(
        input logic [ADDR_WIDTH-1:0] x,
        input logic [ADDR_WIDTH-1:0] y
    );
        logic [VGA_FB_ADDR_WIDTH-1:0] x_ext;
        logic [VGA_FB_ADDR_WIDTH-1:0] y_ext;
        begin
            x_ext = VGA_FB_ADDR_WIDTH'(x);
            y_ext = VGA_FB_ADDR_WIDTH'(y);
            vga_addr_from_xy = (y_ext * VGA_FB_WIDTH) + x_ext;
        end
    endfunction

    function automatic [DATA_WIDTH-1:0] extract_mem_chunk(
        input logic [ADDR_WIDTH-1:0] value,
        input int unsigned chunk_index
    );
        extract_mem_chunk = value >> (chunk_index * DATA_WIDTH);
    endfunction

    function automatic [ADDR_WIDTH-1:0] insert_mem_chunk(
        input logic [ADDR_WIDTH-1:0] acc,
        input logic [DATA_WIDTH-1:0] chunk,
        input int unsigned chunk_index
    );
        logic [ADDR_WIDTH-1:0] shifted;
        shifted = {{(ADDR_WIDTH-DATA_WIDTH){1'b0}}, chunk} << (chunk_index * DATA_WIDTH);
        insert_mem_chunk = acc | shifted;
    endfunction

    task automatic clear_forwarding();
        last_write_valid  <= 1'b0;
        last_write2_valid <= 1'b0;
    endtask

    task automatic set_forwarding(input logic [3:0] reg_id, input logic [ADDR_WIDTH-1:0] value);
        last_written_reg2   <= last_written_reg;
        last_written_value2 <= last_written_value;
        last_write2_valid   <= last_write_valid;
        last_written_reg  <= reg_id;
        last_written_value <= value;
        last_write_valid  <= 1'b1;
    endtask

`ifdef SIMULATION
    function automatic string dest_name();
        if (rd == REG_HEX && flag) dest_name = "HEX display register";
        else if (rd != REG_LE)     dest_name = $sformatf("R%0d", rd);
        else if (flag)             dest_name = "LE (LEDR)";
        else                       dest_name = "PC";
    endfunction
`endif

    task automatic write_exec_result(input logic [ADDR_WIDTH-1:0] value);
        if (rd == REG_HEX && flag) begin
            data_in_hex <= value;
            clear_forwarding();
        end else if (rd != REG_LE) begin
            data_in_registers[rd] <= value;
            set_forwarding(rd, value);
        end else if (flag) begin
            data_in_ledr <= value;
            clear_forwarding();
        end else begin
            data_in_pc  <= value;
            pc_write_en <= 1'b1;
            clear_forwarding();
        end
        `SIMLOG(("Storing result %d (0x%h) in %s", value, value, dest_name()));
    endtask

    task automatic write_load_destination(input logic [ADDR_WIDTH-1:0] value);
        if (rd == REG_HEX && flag) begin
            data_in_hex      <= value;
            last_write_valid <= 1'b0;
        end else if (rd != REG_LE) begin
            data_in_registers[rd] <= value;
            last_written_reg      <= rd;
            last_written_value    <= value;
            last_write_valid      <= 1'b1;
        end else if (flag) begin
            data_in_ledr     <= value;
            last_write_valid <= 1'b0;
        end else begin
            data_in_pc       <= value;
            pc_write_en      <= 1'b1;
            last_write_valid <= 1'b0;
        end
    endtask

    task automatic finish_stack_pop();
        logic [ADDR_WIDTH-1:0] sp_next;
        sp_next = stack_addr + ADDR_WIDTH'(MEM_TRANSFER_BYTES);
        data_in_registers[REG_SP] <= sp_next;
        if (rd < REG_COUNT && rd != REG_SP && !(rd == REG_HEX && flag)) begin
            last_written_reg2   <= REG_SP;
            last_written_value2 <= sp_next;
            last_write2_valid   <= 1'b1;
        end else begin
            last_written_reg   <= REG_SP;
            last_written_value <= sp_next;
            last_write_valid   <= 1'b1;
            last_write2_valid  <= 1'b0;
        end
        stack_pop_active <= 1'b0;
    endtask

    task automatic write_fp_compare_flags();
        logic n, z, c, v;
        if (fp_cmp_unordered) begin
            n = 1'b0;
            z = 1'b0;
            c = 1'b0;
            v = 1'b1;
        end else begin
            n = fp_cmp_lt;
            z = fp_cmp_eq;
            c = fp_cmp_gt || fp_cmp_eq;
            v = 1'b0;
        end
        data_in_cpsr <= {n, z, c, v, 28'b0};
        clear_forwarding();
        `SIMLOG(("FP Compare: N=%b Z=%b C=%b V=%b", n, z, c, v));
    endtask

    task automatic finish_fp_operation();
        if (opcode == EXT_FCMP) begin
            write_fp_compare_flags();
        end else if (opcode == EXT_FMOV) begin
            write_exec_result(fp_mov_result_ext);
            if (immediate) `SIMLOG(("FMOV (imm): 0x%h", fp_b_r));
            else           `SIMLOG(("FMOV: 0x%h -> 0x%h", fp_b_r, fp_mov_result_ext));
        end else begin
            write_exec_result(fp_unit_result_ext);
            if (immediate) `SIMLOG(("FP ALU (imm) opcode=%0h: A=0x%h B=0x%h -> 0x%h",
                                    opcode, fp_a_r, fp_b_r, fp_unit_result));
            else           `SIMLOG(("FP ALU opcode=%0h: A=0x%h B=0x%h -> 0x%h",
                                    opcode, fp_a_r, fp_b_r, fp_unit_result));
        end
    endtask

    task automatic invalidate_fp_literal_cache(input logic [ADDR_WIDTH-1:0] write_addr);
        if (fp_cache_valid[0] &&
            (write_addr == fp_cache_addr[0] ||
             write_addr == (fp_cache_addr[0] + ADDR_WIDTH'(1))))
            fp_cache_valid[0] <= 1'b0;

        if (fp_cache_valid[1] &&
            (write_addr == fp_cache_addr[1] ||
             write_addr == (fp_cache_addr[1] + ADDR_WIDTH'(1))))
            fp_cache_valid[1] <= 1'b0;
    endtask

    integer i;

    always @(posedge clock) begin
        logic queue_enqueue_req;
        logic [VGA_FB_ADDR_WIDTH-1:0] queue_enqueue_addr;
        logic [7:0] queue_enqueue_data;
        logic [ADDR_WIDTH-1:0] queue_enqueue_x;
        logic [ADDR_WIDTH-1:0] queue_enqueue_y;
        logic [PIXEL_QUEUE_INDEX_WIDTH-1:0] queue_head_next;
        logic [PIXEL_QUEUE_INDEX_WIDTH-1:0] queue_tail_next;
        logic [PIXEL_QUEUE_COUNT_WIDTH-1:0] queue_count_next;
        logic fb_write_pending_next;
        logic queue_has_space;
        logic [ADDR_WIDTH-1:0] px_x, px_y, px_color;
        logic [VGA_FB_ADDR_WIDTH-1:0] px_addr;

        pc_write_en  <= 1'b0;
        ram_write_en_r <= 1'b0;
        vga_fb_write <= 1'b0;
        div_start    <= 1'b0;
        npu_start     <= 1'b0;
        npu_cfg_write <= 1'b0;

        data_in_pc   <= data_out_pc;
        data_in_cpsr <= data_in_cpsr;
        data_in_ledr <= data_in_ledr;
        data_in_hex  <= data_in_hex;
        for (i = 0; i < REG_COUNT; i++)
            data_in_registers[i] <= data_in_registers[i];

        queue_enqueue_req  = 1'b0;
        queue_enqueue_addr = '0;
        queue_enqueue_data = '0;
        queue_enqueue_x    = '0;
        queue_enqueue_y    = '0;
        queue_head_next    = pixel_queue_head;
        queue_tail_next    = pixel_queue_tail;
        queue_count_next   = pixel_queue_count;
        fb_write_pending_next = fb_write_pending;
        if (fb_write_pending_next)
            fb_write_pending_next = 1'b0;

        if (pixel_queue_count != '0) begin
            vga_fb_addr  <= pixel_queue_addr[pixel_queue_head];
            vga_fb_data  <= pixel_queue_data[pixel_queue_head];
            vga_fb_write <= 1'b1;
            queue_head_next = pixel_queue_head + PIXEL_QUEUE_INDEX_WIDTH'(1);
            queue_count_next = pixel_queue_count - PIXEL_QUEUE_COUNT_WIDTH'(1);
            fb_write_pending_next = 1'b1;
        end
        queue_has_space = (queue_count_next < PIXEL_QUEUE_DEPTH);

        case (state)
`include "executer_dispatch.svh"
`include "executer_states.svh"
        endcase

        if (queue_enqueue_req) begin
            pixel_queue_addr[queue_tail_next] <= queue_enqueue_addr;
            pixel_queue_data[queue_tail_next] <= queue_enqueue_data;
            queue_tail_next = queue_tail_next + PIXEL_QUEUE_INDEX_WIDTH'(1);
            queue_count_next = queue_count_next + PIXEL_QUEUE_COUNT_WIDTH'(1);
            `SIMPIXELLOG(("PIXEL: x=%0d y=%0d color=%0d addr=%0d",
                          queue_enqueue_x, queue_enqueue_y, queue_enqueue_data, queue_enqueue_addr));
        end

        pixel_queue_head  <= queue_head_next;
        pixel_queue_tail  <= queue_tail_next;
        pixel_queue_count <= queue_count_next;
        fb_write_pending  <= fb_write_pending_next;

        if (mmio_led_write)
            data_in_ledr <= merge_display_byte(data_in_ledr, mmio_display_byte,
                                               mmio_display_index);
        if (mmio_hex_write)
            data_in_hex  <= merge_display_byte(data_in_hex, mmio_display_byte,
                                               mmio_display_index);

        if (reset) begin
            state        <= EX_IDLE;
            execute_done <= 1'b0;
            halted       <= 1'b0;
            halt_pending <= 1'b0;
            pc_write_en  <= 1'b0;
            ram_write_en_r <= 1'b0;
            vga_fb_write <= 1'b0;

            data_in_pc     <= '0;
            data_in_cpsr   <= '0;
            data_in_ledr   <= '0;
            data_in_hex    <= '0;
            ram_read_addr_r  <= '0;
            ram_write_addr_r <= '0;
            ram_write_data_r <= '0;
            vga_fb_addr    <= '0;
            vga_fb_data    <= '0;

            for (i = 0; i < REG_COUNT; i++)
                data_in_registers[i] <= '0;
            data_in_registers[REG_SP] <= ADDR_WIDTH'(MMIO_BASE);

            last_write_valid  <= 1'b0;
            last_write2_valid <= 1'b0;
            stack_pop_active  <= 1'b0;
            mem_multi_pending <= 1'b0;

            pixel_queue_head  <= '0;
            pixel_queue_tail  <= '0;
            pixel_queue_count <= '0;
            fb_write_pending  <= 1'b0;
            pixel_blocking    <= 1'b0;

            wait_counter    <= '0;
            wait_cycles     <= '0;
            fp_cache_valid  <= '0;
            fp_settle_count <= '0;
            div_start       <= 1'b0;
            div_for_fp      <= 1'b0;
            npu_start       <= 1'b0;
            npu_cfg_write   <= 1'b0;
            vec_index       <= '0;
            for (i = 0; i < NPU_VREGS; i++) vreg[i] <= '0;
            for (i = 0; i < NPU_ACCS; i++)  acc_file[i] <= '0;
        end
    end
endmodule
