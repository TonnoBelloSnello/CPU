module NPU
    import cpu_pkg::*;
#(
    parameter DATA_WIDTH = 8,
    parameter ADDR_WIDTH = 16
)(
    input  logic                  clock,
    input  logic                  reset,

    input  logic                  cfg_write,
    input  logic [4:0]            cfg_index,
    input  logic [ADDR_WIDTH-1:0] cfg_value,

    input  logic                  start,
    output logic                  busy   = 1'b0,
    output logic                  done   = 1'b0,
    output logic [ADDR_WIDTH-1:0] result = '0,

    output logic [ADDR_WIDTH-1:0] mem_raddr = '0,
    output logic [ADDR_WIDTH-1:0] mem_waddr = '0,
    output logic                  mem_write = 1'b0,
    output logic [DATA_WIDTH-1:0] mem_wdata = '0,
    input  logic [DATA_WIDTH-1:0] mem_rdata
);

    typedef enum logic [4:0] {
        N_IDLE,
        N_START,
        N_PATCH_ISSUE,
        N_PATCH_WAIT,
        N_PATCH_DATA,
        N_POOL,
        N_SEED_ISSUE,
        N_SEED_WAIT,
        N_SEED_DATA,
        N_MAC_PRIME,
        N_MAC_PRIME2,
        N_MAC_RUN,
        N_OUT_MUL,
        N_OUT_PREP,
        N_OUT_WRITE,
        N_NEXT,
        N_LUT_WAIT,
        N_LUT_INDEX,
        N_LUT_TABLE_WAIT,
        N_LUT_STORE,
        N_ARG_WAIT,
        N_ARG_DATA,
        N_FINISH
    } npu_state_t;

    npu_state_t state = N_IDLE;

    logic [ADDR_WIDTH-1:0] cfg [0:NPU_CFG_COUNT-1];

    (* ramstyle = "MLAB" *) logic signed [8:0] patch [0:NPU_PATCH_DEPTH-1];

    wire [3:0]  mode  = cfg[NPUC_MODE][3:0];
    wire [15:0] flags = cfg[NPUC_FLAGS][15:0];

    wire [ADDR_WIDTH-1:0] cfg_in_base  = cfg[NPUC_IN_BASE];
    wire [ADDR_WIDTH-1:0] cfg_w_base   = cfg[NPUC_W_BASE];
    wire [ADDR_WIDTH-1:0] cfg_b_base   = cfg[NPUC_B_BASE];
    wire [ADDR_WIDTH-1:0] cfg_out_base = cfg[NPUC_OUT_BASE];
    wire [ADDR_WIDTH-1:0] cfg_acc_base = cfg[NPUC_ACC_BASE];
    wire [ADDR_WIDTH-1:0] cfg_lut_base = cfg[NPUC_LUT_BASE];

    wire [15:0] in_w  = cfg[NPUC_IN_W][15:0];
    wire [15:0] in_h  = cfg[NPUC_IN_H][15:0];
    wire [15:0] in_c  = cfg[NPUC_IN_C][15:0];
    wire [15:0] out_w = cfg[NPUC_OUT_W][15:0];
    wire [15:0] out_h = cfg[NPUC_OUT_H][15:0];
    wire [15:0] out_c = cfg[NPUC_OUT_C][15:0];
    wire [15:0] k_w   = cfg[NPUC_K_W][15:0];
    wire [15:0] k_h   = cfg[NPUC_K_H][15:0];

    wire [7:0] stride_x = cfg[NPUC_STRIDE][7:0];
    wire [7:0] stride_y = cfg[NPUC_STRIDE][15:8];
    wire [7:0] pad_x    = cfg[NPUC_PAD][7:0];
    wire [7:0] pad_y    = cfg[NPUC_PAD][15:8];

    wire signed [7:0]  in_zp   = cfg[NPUC_IN_ZP][7:0];
    wire signed [15:0] out_zp  = cfg[NPUC_OUT_ZP][15:0];
    wire        [15:0] mult    = cfg[NPUC_MULT][15:0];
    wire        [4:0]  shift   = cfg[NPUC_SHIFT][4:0];
    wire signed [7:0]  act_min = cfg[NPUC_ACT_MIN][7:0];
    wire signed [7:0]  act_max = cfg[NPUC_ACT_MAX][7:0];

    wire flag_acc_in  = flags[NPU_FLAG_ACC_IN];
    wire flag_acc_out = flags[NPU_FLAG_ACC_OUT];
    wire flag_no_bias = flags[NPU_FLAG_NO_BIAS];

    wire mode_is_conv       = (mode == NPU_MODE_CONV);
    wire mode_is_pool       = (mode == NPU_MODE_MAXPOOL) || (mode == NPU_MODE_AVGPOOL);
    wire mode_has_weights   = (mode == NPU_MODE_CONV) || (mode == NPU_MODE_DEPTHWISE);
    wire patch_per_channel  = !mode_is_conv;

    logic [15:0] oy = '0, ox = '0, oc = '0;
    logic [15:0] ky = '0, kx = '0, ic = '0;

    logic [NPU_PATCH_ADDR_WIDTH:0] patch_len   = '0;
    logic [NPU_PATCH_ADDR_WIDTH:0] patch_w     = '0;
    logic [NPU_PATCH_ADDR_WIDTH:0] patch_count = '0;
    logic [NPU_PATCH_ADDR_WIDTH:0] pool_idx    = '0;
    logic [NPU_PATCH_ADDR_WIDTH:0] mac_issue   = '0;
    logic [NPU_PATCH_ADDR_WIDTH:0] mac_data    = '0;

    logic signed [31:0] acc        = '0;
    logic        [31:0] seed_value = '0;
    logic signed [48:0] acc_scaled = '0;
    logic [1:0]  byte_idx = '0;
    logic [ADDR_WIDTH-1:0] seed_base  = '0;
    logic [ADDR_WIDTH-1:0] w_ptr      = '0;
    logic [ADDR_WIDTH-1:0] w_stride   = '0;
    logic [ADDR_WIDTH-1:0] out_index  = '0;
    logic [ADDR_WIDTH-1:0] elem_count = '0;
    logic [ADDR_WIDTH-1:0] elem_index = '0;
    logic signed [15:0]    best_val   = '0;
    logic [ADDR_WIDTH-1:0] best_index = '0;

    wire signed [8:0]  patch_q     = patch[mac_data[NPU_PATCH_ADDR_WIDTH-1:0]];
    wire signed [8:0]  pool_q      = patch[pool_idx[NPU_PATCH_ADDR_WIDTH-1:0]];
    wire signed [31:0] pool_q_ext  = {{23{pool_q[8]}}, pool_q};
    wire signed [7:0]  weight_q    = $signed(mem_rdata);
    wire signed [16:0] mac_product = patch_q * weight_q;
    wire signed [31:0] mac_next    = acc + {{15{mac_product[16]}}, mac_product};

    wire signed [48:0] acc_ext  = {{17{acc[31]}}, acc};
    wire signed [48:0] mult_ext = {33'd0, mult};

    function automatic logic signed [31:0] rounding_shift_right(
        input logic signed [31:0] value,
        input logic [4:0]         amount
    );
        logic [31:0] mask;
        logic [31:0] remainder;
        logic [31:0] threshold;
        logic signed [31:0] shifted;
        begin
            if (amount == 5'd0) begin
                rounding_shift_right = value;
            end else begin
                mask      = (32'd1 << amount) - 32'd1;
                remainder = value & mask;
                threshold = (mask >> 1) + (value[31] ? 32'd1 : 32'd0);
                shifted   = value >>> amount;
                rounding_shift_right = (remainder > threshold) ? (shifted + 32'sd1)
                                                               : shifted;
            end
        end
    endfunction

    function automatic logic signed [31:0] clamp_activation(
        input logic signed [31:0] value,
        input logic signed [7:0]  lo,
        input logic signed [7:0]  hi
    );
        logic signed [31:0] lo_ext;
        logic signed [31:0] hi_ext;
        begin
            if (lo == hi) begin
                lo_ext = -32'sd128;
                hi_ext =  32'sd127;
            end else begin
                lo_ext = {{24{lo[7]}}, lo};
                hi_ext = {{24{hi[7]}}, hi};
            end
            if (value < lo_ext)      clamp_activation = lo_ext;
            else if (value > hi_ext) clamp_activation = hi_ext;
            else                     clamp_activation = value;
        end
    endfunction

    logic signed [31:0] src_y;
    logic signed [31:0] src_x;
    logic               src_in_bounds;
    logic [15:0]        src_channel;
    logic signed [31:0] src_offset;

    always_comb begin
        src_y = ($signed({16'd0, oy}) * $signed({24'd0, stride_y}))
              + $signed({16'd0, ky}) - $signed({24'd0, pad_y});
        src_x = ($signed({16'd0, ox}) * $signed({24'd0, stride_x}))
              + $signed({16'd0, kx}) - $signed({24'd0, pad_x});
        src_in_bounds = (src_y >= 0) && (src_y < $signed({16'd0, in_h}))
                     && (src_x >= 0) && (src_x < $signed({16'd0, in_w}));
        src_channel = mode_is_conv ? ic : oc;
        src_offset  = (((src_y * $signed({16'd0, in_w})) + src_x)
                       * $signed({16'd0, in_c})) + $signed({16'd0, src_channel});
    end

    task automatic advance_patch(output logic finished);
        begin
            finished = 1'b0;
            if (mode_is_conv && ((ic + 16'd1) < in_c)) begin
                ic <= ic + 16'd1;
            end else begin
                ic <= 16'd0;
                if ((kx + 16'd1) < k_w) begin
                    kx <= kx + 16'd1;
                end else begin
                    kx <= 16'd0;
                    if ((ky + 16'd1) < k_h) ky <= ky + 16'd1;
                    else                    finished = 1'b1;
                end
            end
        end
    endtask

    task automatic begin_patch();
        begin
            ky          <= 16'd0;
            kx          <= 16'd0;
            ic          <= 16'd0;
            patch_w     <= '0;
            patch_count <= '0;
            state       <= N_PATCH_ISSUE;
        end
    endtask

    task automatic begin_reduction();
        begin
            if (mode_is_pool) begin
                pool_idx <= '0;
                acc      <= 32'sd0;
                state    <= N_POOL;
            end else begin
                state <= N_SEED_ISSUE;
            end
        end
    endtask

    integer init_i;
    initial begin
        for (init_i = 0; init_i < NPU_CFG_COUNT; init_i++) cfg[init_i] = '0;
        for (init_i = 0; init_i < NPU_PATCH_DEPTH; init_i++) patch[init_i] = '0;
    end

    always_ff @(posedge clock) begin
        logic patch_finished;
        logic signed [31:0] requantized;

        done      <= 1'b0;
        mem_write <= 1'b0;

        if (cfg_write && (state == N_IDLE))
            cfg[cfg_index] <= cfg_value;

        case (state)
            N_IDLE: begin
                if (start) begin
                    busy  <= 1'b1;
                    state <= N_START;
                end
            end

            N_START: begin
                logic [31:0] window;
                window = mode_is_conv
                    ? ({16'd0, k_h} * {16'd0, k_w} * {16'd0, in_c})
                    : ({16'd0, k_h} * {16'd0, k_w});

                oy         <= 16'd0;
                ox         <= 16'd0;
                oc         <= 16'd0;
                out_index  <= '0;
                elem_index <= '0;
                best_index <= '0;
                best_val   <= 16'sh8000;

                if ((out_w == 16'd0) || (out_h == 16'd0) || (out_c == 16'd0)) begin
                    result <= ADDR_WIDTH'(NPU_ERR_SHAPE);
                    state  <= N_FINISH;
                end else if ((mode == NPU_MODE_LUT) || (mode == NPU_MODE_ARGMAX)) begin
                    elem_count <= ADDR_WIDTH'({16'd0, out_w} * {16'd0, out_h}
                                              * {16'd0, out_c});
                    result     <= (mode == NPU_MODE_LUT) ? cfg_out_base : '0;
                    mem_raddr  <= cfg_in_base;
                    state      <= (mode == NPU_MODE_LUT) ? N_LUT_WAIT : N_ARG_WAIT;
                end else if ((k_w == 16'd0) || (k_h == 16'd0)
                             || (mode_is_conv && (in_c == 16'd0))) begin
                    result <= ADDR_WIDTH'(NPU_ERR_SHAPE);
                    state  <= N_FINISH;
                end else if (window > NPU_PATCH_DEPTH) begin
                    result <= ADDR_WIDTH'(NPU_ERR_PATCH);
                    state  <= N_FINISH;
                end else begin
                    patch_len <= window[NPU_PATCH_ADDR_WIDTH:0];
                    w_stride  <= mode_is_conv ? ADDR_WIDTH'(1) : ADDR_WIDTH'(in_c);
                    result    <= cfg_out_base;
                    begin_patch();
                end
            end

            N_PATCH_ISSUE: begin
                if (src_in_bounds) begin
                    mem_raddr <= cfg_in_base + ADDR_WIDTH'(src_offset);
                    state     <= N_PATCH_WAIT;
                end else begin
                    if (!mode_is_pool) begin
                        patch[patch_w[NPU_PATCH_ADDR_WIDTH-1:0]] <= 9'sd0;
                        patch_w <= patch_w + 1'b1;
                    end
                    advance_patch(patch_finished);
                    if (patch_finished) begin_reduction();
                end
            end

            N_PATCH_WAIT: state <= N_PATCH_DATA;

            N_PATCH_DATA: begin
                patch[patch_w[NPU_PATCH_ADDR_WIDTH-1:0]] <=
                    mode_is_pool
                        ? $signed({mem_rdata[DATA_WIDTH-1], mem_rdata})
                        : ($signed({mem_rdata[DATA_WIDTH-1], mem_rdata})
                           - $signed({in_zp[7], in_zp}));
                patch_w     <= patch_w + 1'b1;
                patch_count <= patch_count + 1'b1;
                advance_patch(patch_finished);
                if (patch_finished) begin_reduction();
                else                state <= N_PATCH_ISSUE;
            end

            N_POOL: begin
                if (patch_count == '0) begin
                    acc   <= 32'sd0;
                    state <= N_OUT_MUL;
                end else if (pool_idx < patch_count) begin
                    if (mode == NPU_MODE_MAXPOOL)
                        acc <= ((pool_idx == '0) || (pool_q_ext > acc)) ? pool_q_ext : acc;
                    else
                        acc <= acc + pool_q_ext;
                    pool_idx <= pool_idx + 1'b1;
                end else begin
                    state <= N_OUT_MUL;
                end
            end

            N_SEED_ISSUE: begin
                logic [ADDR_WIDTH-1:0] base;
                base = flag_acc_in
                    ? (cfg_acc_base + ADDR_WIDTH'({14'd0, out_index} << 2))
                    : (cfg_b_base   + ADDR_WIDTH'({14'd0, oc} << 2));
                seed_base  <= base;
                seed_value <= 32'd0;
                byte_idx   <= 2'd0;
                if (flag_no_bias && !flag_acc_in) begin
                    acc   <= 32'sd0;
                    state <= N_MAC_PRIME;
                end else begin
                    mem_raddr <= base;
                    state     <= N_SEED_WAIT;
                end
            end

            N_SEED_WAIT: state <= N_SEED_DATA;

            N_SEED_DATA: begin
                seed_value <= {mem_rdata, seed_value[31:8]};
                if (byte_idx == 2'd3) begin
                    acc   <= $signed({mem_rdata, seed_value[31:8]});
                    state <= N_MAC_PRIME;
                end else begin
                    byte_idx  <= byte_idx + 2'd1;
                    mem_raddr <= seed_base + ADDR_WIDTH'({14'd0, byte_idx}) + ADDR_WIDTH'(1);
                    state     <= N_SEED_WAIT;
                end
            end

            N_MAC_PRIME: begin
                logic [ADDR_WIDTH-1:0] row;
                row = mode_is_conv
                    ? (cfg_w_base + ADDR_WIDTH'({16'd0, oc} * {23'd0, patch_len}))
                    : (cfg_w_base + ADDR_WIDTH'(oc));
                mac_data <= '0;
                if (!mode_has_weights || (patch_len == '0)) begin
                    mac_issue <= '0;
                    state     <= N_OUT_MUL;
                end else begin
                    w_ptr     <= row + w_stride;
                    mem_raddr <= row;
                    mac_issue <= 1;
                    state     <= N_MAC_PRIME2;
                end
            end

            N_MAC_PRIME2: begin
                if (mac_issue < patch_len) begin
                    mem_raddr <= w_ptr;
                    w_ptr     <= w_ptr + w_stride;
                    mac_issue <= mac_issue + 1'b1;
                end
                state <= N_MAC_RUN;
            end

            N_MAC_RUN: begin
                acc <= mac_next;
                if (mac_issue < patch_len) begin
                    mem_raddr <= w_ptr;
                    w_ptr     <= w_ptr + w_stride;
                    mac_issue <= mac_issue + 1'b1;
                end
                if ((mac_data + 1'b1) == patch_len) state    <= N_OUT_MUL;
                else                                mac_data <= mac_data + 1'b1;
            end

            N_OUT_MUL: begin
                acc_scaled <= (acc_ext * mult_ext) + 49'sd16384;
                state      <= N_OUT_PREP;
            end

            N_OUT_PREP: begin
                if (flag_acc_out) begin
                    byte_idx  <= 2'd0;
                    mem_waddr <= cfg_acc_base + ADDR_WIDTH'({14'd0, out_index} << 2);
                    mem_wdata <= acc[7:0];
                    mem_write <= 1'b1;
                    state     <= N_OUT_WRITE;
                end else begin
                    requantized = (mult == 16'd0) ? acc : acc_scaled[46:15];
                    requantized = rounding_shift_right(requantized, shift);
                    requantized = requantized + {{16{out_zp[15]}}, out_zp};
                    requantized = clamp_activation(requantized, act_min, act_max);
                    mem_waddr   <= cfg_out_base + out_index;
                    mem_wdata   <= requantized[DATA_WIDTH-1:0];
                    mem_write   <= 1'b1;
                    state       <= N_NEXT;
                end
            end

            N_OUT_WRITE: begin
                if (byte_idx == 2'd3) begin
                    state <= N_NEXT;
                end else begin
                    mem_waddr <= cfg_acc_base + ADDR_WIDTH'({14'd0, out_index} << 2)
                                 + ADDR_WIDTH'({14'd0, byte_idx}) + ADDR_WIDTH'(1);
                    mem_wdata <= acc[{byte_idx + 2'd1, 3'b000} +: 8];
                    mem_write <= 1'b1;
                    byte_idx  <= byte_idx + 2'd1;
                end
            end

            N_NEXT: begin
                out_index <= out_index + ADDR_WIDTH'(1);
                if ((oc + 16'd1) < out_c) begin
                    oc <= oc + 16'd1;
                    if (patch_per_channel) begin_patch();
                    else                   begin_reduction();
                end else begin
                    oc <= 16'd0;
                    if ((ox + 16'd1) < out_w) begin
                        ox <= ox + 16'd1;
                        begin_patch();
                    end else begin
                        ox <= 16'd0;
                        if ((oy + 16'd1) < out_h) begin
                            oy <= oy + 16'd1;
                            begin_patch();
                        end else begin
                            state <= N_FINISH;
                        end
                    end
                end
            end

            N_LUT_WAIT: state <= N_LUT_INDEX;

            N_LUT_INDEX: begin
                mem_raddr <= cfg_lut_base + ADDR_WIDTH'(mem_rdata);
                state     <= N_LUT_TABLE_WAIT;
            end

            N_LUT_TABLE_WAIT: state <= N_LUT_STORE;

            N_LUT_STORE: begin
                mem_waddr <= cfg_out_base + elem_index;
                mem_wdata <= mem_rdata;
                mem_write <= 1'b1;
                if ((elem_index + ADDR_WIDTH'(1)) == elem_count) begin
                    state <= N_FINISH;
                end else begin
                    elem_index <= elem_index + ADDR_WIDTH'(1);
                    mem_raddr  <= cfg_in_base + elem_index + ADDR_WIDTH'(1);
                    state      <= N_LUT_WAIT;
                end
            end

            N_ARG_WAIT: state <= N_ARG_DATA;

            N_ARG_DATA: begin
                logic signed [15:0] sample;
                logic               takes_lead;
                sample     = $signed({mem_rdata[DATA_WIDTH-1], mem_rdata});
                takes_lead = (elem_index == '0) || (sample > best_val);
                if (takes_lead) begin
                    best_val   <= sample;
                    best_index <= elem_index;
                end
                if ((elem_index + ADDR_WIDTH'(1)) == elem_count) begin
                    result <= takes_lead ? elem_index : best_index;
                    state  <= N_FINISH;
                end else begin
                    elem_index <= elem_index + ADDR_WIDTH'(1);
                    mem_raddr  <= cfg_in_base + elem_index + ADDR_WIDTH'(1);
                    state      <= N_ARG_WAIT;
                end
            end

            N_FINISH: begin
                busy  <= 1'b0;
                done  <= 1'b1;
                state <= N_IDLE;
            end

            default: state <= N_IDLE;
        endcase

        if (reset) begin
            state     <= N_IDLE;
            busy      <= 1'b0;
            done      <= 1'b0;
            mem_write <= 1'b0;
            mem_raddr <= '0;
            mem_waddr <= '0;
            mem_wdata <= '0;
            result    <= '0;
            for (init_i = 0; init_i < NPU_CFG_COUNT; init_i++) cfg[init_i] <= '0;
        end
    end

endmodule
