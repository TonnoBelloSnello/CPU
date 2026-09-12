module fp16_unit (
    input  logic [15:0] a,
    input  logic [15:0] b,
    input  logic [1:0]  op,  // 00=add, 01=sub, 10=mul, 11=div
    output logic [15:0] result,
    output logic        cmp_eq,
    output logic        cmp_lt,
    output logic        cmp_gt,
    output logic        cmp_unordered,

    output logic [26:0] div_num,
    output logic [15:0] div_den,
    input  logic [17:0] div_q,
    input  logic        div_rem_nonzero
);

    localparam logic [15:0] FP16_POS_INF = 16'h7C00;
    localparam logic [15:0] FP16_QUIET_NAN = 16'h7E00;

    typedef struct packed {
        logic       sign;
        logic [4:0] exp;
        logic [9:0] frac;
        logic       is_nan;
        logic       is_inf;
        logic       is_zero;
    } fp16_parts_t;

    function automatic fp16_parts_t unpack_fp16(input logic [15:0] value);
        logic [4:0] exp;
        logic [9:0] frac;
        exp  = value[14:10];
        frac = value[9:0];
        unpack_fp16.sign    = value[15];
        unpack_fp16.exp     = exp;
        unpack_fp16.frac    = (exp == 5'd0) ? 10'd0 : frac;
        unpack_fp16.is_nan  = (exp == 5'h1F) && (frac != 10'd0);
        unpack_fp16.is_inf  = (exp == 5'h1F) && (frac == 10'd0);
        unpack_fp16.is_zero = (exp == 5'd0);
    endfunction

    function automatic logic [15:0] pack_fp16(
        input logic sign,
        input logic [4:0] exp,
        input logic [9:0] frac
    );
        pack_fp16 = {sign, exp, frac};
    endfunction

    function automatic logic [13:0] shift_right_sticky_14(
        input logic [13:0] value,
        input int unsigned shift_amount
    );
        logic [13:0] shifted;
        logic [13:0] dropped_mask;
        begin
            if (shift_amount == 0) begin
                shift_right_sticky_14 = value;
            end else if (shift_amount >= 14) begin
                shift_right_sticky_14 = {13'b0, |value};
            end else begin
                shifted = value >> shift_amount;
                dropped_mask = ~(14'h3FFF << shift_amount);
                shifted[0] = shifted[0] | (|(value & dropped_mask));
                shift_right_sticky_14 = shifted;
            end
        end
    endfunction

    function automatic logic [3:0] norm_shift_14(
        input logic [13:0] value,
        input int          exp_in
    );
        logic [3:0] lead;
        logic [3:0] room;
        int p;
        begin
            lead = 4'd11;
            for (p = 10; p >= 0; p = p - 1)
                if (value[13 - p]) lead = 4'(p);

            room = (exp_in > 11) ? 4'd11 : ((exp_in > 1) ? 4'(exp_in - 1) : 4'd0);
            norm_shift_14 = (lead < room) ? lead : room;
        end
    endfunction

    function automatic logic [1:0] norm_shift_18(
        input logic [17:0] value,
        input int          exp_in
    );
        logic [1:0] lead;
        logic [1:0] room;
        int p;
        begin
            lead = 2'd3;
            for (p = 2; p >= 0; p = p - 1)
                if (value[16 - p]) lead = 2'(p);

            room = (exp_in > 3) ? 2'd3 : ((exp_in > 1) ? 2'(exp_in - 1) : 2'd0);
            norm_shift_18 = (lead < room) ? lead : room;
        end
    endfunction

    function automatic logic [15:0] round_pack_normal(
        input logic sign,
        input int   exp_int,
        input logic [13:0] sig_grs
    );
        logic [10:0] mant;
        logic guard_bit, round_bit, sticky_bit;
        logic [11:0] mant_ext;
        int exp_work;
        begin
            if (sig_grs == 14'd0) begin
                round_pack_normal = pack_fp16(sign, 5'd0, 10'd0);
            end else begin
                exp_work = exp_int;
                if (exp_work <= 0) begin
                    round_pack_normal = pack_fp16(sign, 5'd0, 10'd0);
                end else begin
                    mant = sig_grs[13:3];
                    guard_bit = sig_grs[2];
                    round_bit = sig_grs[1];
                    sticky_bit = sig_grs[0];

                    mant_ext = {1'b0, mant};
                    if (guard_bit && (round_bit || sticky_bit || mant[0]))
                        mant_ext = mant_ext + 12'd1;

                    if (mant_ext[11]) begin
                        mant_ext = {1'b0, mant_ext[11:1]};
                        exp_work = exp_work + 1;
                    end

                    if (exp_work >= 31) begin
                        round_pack_normal = pack_fp16(sign, 5'h1F, 10'd0);
                    end else if (exp_work <= 0) begin
                        round_pack_normal = pack_fp16(sign, 5'd0, 10'd0);
                    end else begin
                        round_pack_normal = pack_fp16(sign, exp_work[4:0], mant_ext[9:0]);
                    end
                end
            end
        end
    endfunction

    function automatic logic [15:0] fp16_addsub(
        input fp16_parts_t pa,
        input fp16_parts_t pb,
        input logic        subtract
    );
        logic sign_b_eff;
        logic [10:0] mant_a, mant_b;
        logic [13:0] ext_a, ext_b, ext_large, ext_small;
        logic sign_large, sign_small, sign_res;
        int exp_large, exp_small, exp_res;
        int exp_diff;

        logic [14:0] ext_sum;
        logic [13:0] sig_norm;
        logic [13:0] ext_diff;
        logic [3:0]  norm_shift;

        begin
            sign_b_eff = pb.sign ^ subtract;

            if (pa.is_nan || pb.is_nan) begin
                fp16_addsub = FP16_QUIET_NAN;
            end else if (pa.is_inf || pb.is_inf) begin
                if (pa.is_inf && pb.is_inf && (pa.sign != sign_b_eff))
                    fp16_addsub = FP16_QUIET_NAN;
                else if (pa.is_inf)
                    fp16_addsub = pack_fp16(pa.sign, 5'h1F, 10'd0);
                else
                    fp16_addsub = pack_fp16(sign_b_eff, 5'h1F, 10'd0);
            end else if (pa.is_zero && pb.is_zero) begin
                fp16_addsub = pack_fp16(pa.sign & sign_b_eff, 5'd0, 10'd0);
            end else if (pa.is_zero) begin
                fp16_addsub = pack_fp16(sign_b_eff, pb.exp, pb.frac);
            end else if (pb.is_zero) begin
                fp16_addsub = pack_fp16(pa.sign, pa.exp, pa.frac);
            end else begin
                mant_a = {1'b1, pa.frac};
                mant_b = {1'b1, pb.frac};
                ext_a = {mant_a, 3'b000};
                ext_b = {mant_b, 3'b000};

                if ((pa.exp > pb.exp) || ((pa.exp == pb.exp) && (mant_a >= mant_b))) begin
                    exp_large = pa.exp;
                    exp_small = pb.exp;
                    sign_large = pa.sign;
                    sign_small = sign_b_eff;
                    ext_large = ext_a;
                    ext_small = ext_b;
                end else begin
                    exp_large = pb.exp;
                    exp_small = pa.exp;
                    sign_large = sign_b_eff;
                    sign_small = pa.sign;
                    ext_large = ext_b;
                    ext_small = ext_a;
                end

                exp_diff = exp_large - exp_small;
                ext_small = shift_right_sticky_14(ext_small, exp_diff);
                exp_res = exp_large;

                if (sign_large == sign_small) begin
                    ext_sum = {1'b0, ext_large} + {1'b0, ext_small};
                    sign_res = sign_large;
                    if (ext_sum[14]) begin
                        sig_norm = ext_sum[14:1];
                        sig_norm[0] = sig_norm[0] | ext_sum[0];
                        exp_res = exp_res + 1;
                    end else begin
                        sig_norm = ext_sum[13:0];
                    end
                    fp16_addsub = round_pack_normal(sign_res, exp_res, sig_norm);
                end else begin
                    if (ext_large == ext_small) begin
                        fp16_addsub = pack_fp16(1'b0, 5'd0, 10'd0);
                    end else begin
                        ext_diff = ext_large - ext_small;
                        sign_res = sign_large;
                        norm_shift = norm_shift_14(ext_diff, exp_res);
                        sig_norm = ext_diff << norm_shift;
                        exp_res  = exp_res - int'(norm_shift);
                        if (sig_norm[13] == 1'b0)
                            fp16_addsub = pack_fp16(sign_res, 5'd0, 10'd0);
                        else
                            fp16_addsub = round_pack_normal(sign_res, exp_res, sig_norm);
                    end
                end
            end
        end
    endfunction

    function automatic logic [15:0] fp16_mul(
        input fp16_parts_t pa,
        input fp16_parts_t pb
    );
        logic sign_res;
        logic [10:0] mant_a, mant_b;
        logic [21:0] product;
        logic [13:0] sig_norm;
        int exp_res;
        begin
            sign_res = pa.sign ^ pb.sign;

            if (pa.is_nan || pb.is_nan) begin
                fp16_mul = FP16_QUIET_NAN;
            end else if ((pa.is_inf && pb.is_zero) || (pb.is_inf && pa.is_zero)) begin
                fp16_mul = FP16_QUIET_NAN;
            end else if (pa.is_inf || pb.is_inf) begin
                fp16_mul = pack_fp16(sign_res, 5'h1F, 10'd0);
            end else if (pa.is_zero || pb.is_zero) begin
                fp16_mul = pack_fp16(sign_res, 5'd0, 10'd0);
            end else begin
                mant_a = {1'b1, pa.frac};
                mant_b = {1'b1, pb.frac};
                product = mant_a * mant_b;
                exp_res = pa.exp + pb.exp - 15;

                if (product[21]) begin
                    exp_res = exp_res + 1;
                    sig_norm = {product[21:11], product[10], product[9], |product[8:0]};
                end else begin
                    sig_norm = {product[20:10], product[9], product[8], |product[7:0]};
                end

                fp16_mul = round_pack_normal(sign_res, exp_res, sig_norm);
            end
        end
    endfunction

    function automatic logic [15:0] fp16_div(
        input fp16_parts_t pa,
        input fp16_parts_t pb,
        input logic [17:0] quot,
        input logic        quot_rem_nonzero
    );
        logic sign_res;
        logic [10:0] mant_a, mant_b;
        logic [17:0] q_raw;
        logic [17:0] q_norm;
        logic [10:0] mant_norm;
        logic guard_bit, round_bit, sticky_bit;
        logic rem_nonzero;
        logic [13:0] sig_norm;
        logic [1:0]  norm_shift;
        int exp_res;
        begin
            sign_res = pa.sign ^ pb.sign;

            if (pa.is_nan || pb.is_nan) begin
                fp16_div = FP16_QUIET_NAN;
            end else if ((pa.is_zero && pb.is_zero) || (pa.is_inf && pb.is_inf)) begin
                fp16_div = FP16_QUIET_NAN;
            end else if (pa.is_inf) begin
                fp16_div = pack_fp16(sign_res, 5'h1F, 10'd0);
            end else if (pb.is_inf) begin
                fp16_div = pack_fp16(sign_res, 5'd0, 10'd0);
            end else if (pb.is_zero) begin
                fp16_div = pack_fp16(sign_res, 5'h1F, 10'd0);
            end else if (pa.is_zero) begin
                fp16_div = pack_fp16(sign_res, 5'd0, 10'd0);
            end else begin
                mant_a = {1'b1, pa.frac};
                mant_b = {1'b1, pb.frac};
                exp_res = pa.exp - pb.exp + 15;

                q_raw = quot;
                rem_nonzero = quot_rem_nonzero;

                norm_shift = norm_shift_18(q_raw, exp_res);
                q_norm  = q_raw << norm_shift;
                exp_res = exp_res - int'(norm_shift);

                mant_norm = q_norm[16:6];
                guard_bit = q_norm[5];
                round_bit = q_norm[4];
                sticky_bit = (|q_norm[3:0]) | rem_nonzero;

                sig_norm = {mant_norm, guard_bit, round_bit, sticky_bit};
                fp16_div = round_pack_normal(sign_res, exp_res, sig_norm);
            end
        end
    endfunction

    fp16_parts_t pa, pb;
    assign pa = unpack_fp16(a);
    assign pb = unpack_fp16(b);

    logic [14:0] mag_a, mag_b;

    assign div_num = {1'b1, pa.frac, 16'd0};
    assign div_den = {5'd0, 1'b1, pb.frac};

    always_comb begin
        case (op)
            2'b00: result = fp16_addsub(pa, pb, 1'b0);
            2'b01: result = fp16_addsub(pa, pb, 1'b1);
            2'b10: result = fp16_mul(pa, pb);
            default: result = fp16_div(pa, pb, div_q, div_rem_nonzero);
        endcase

        mag_a = {pa.exp, pa.frac};
        mag_b = {pb.exp, pb.frac};

        cmp_eq = 1'b0;
        cmp_lt = 1'b0;
        cmp_gt = 1'b0;
        cmp_unordered = 1'b0;

        if (pa.is_nan || pb.is_nan) begin
            cmp_unordered = 1'b1;
        end else if (pa.is_zero && pb.is_zero) begin
            cmp_eq = 1'b1;
        end else if (pa.sign != pb.sign) begin
            cmp_lt = pa.sign;
            cmp_gt = ~pa.sign;
        end else if (mag_a == mag_b) begin
            cmp_eq = 1'b1;
        end else if (!pa.sign) begin
            cmp_lt = (mag_a < mag_b);
            cmp_gt = (mag_a > mag_b);
        end else begin
            cmp_lt = (mag_a > mag_b);
            cmp_gt = (mag_a < mag_b);
        end
    end

endmodule
