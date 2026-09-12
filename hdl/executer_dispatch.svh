            EX_IDLE: begin
                if (execute_instr && !halted) begin
                    if (condition == COND_EQ && instr_class == CLASS_DP &&
                        !immediate && opcode == 4'h0 && rn == 4'h0 &&
                        rd == 4'h0 && second_operand == 12'h0) begin
                        `SIMLOG(("Halt: Encountered null instruction (0x00000000), stopping execution"));
                        clear_forwarding();
                        halt_pending <= 1'b1;
                        if (queue_count_next == '0 && !fb_write_pending_next) begin
                            halted       <= 1'b1;
                            halt_pending <= 1'b0;
                            execute_done <= 1'b1;
                            `SIM_FINISH;
                        end else begin
                            execute_done <= 1'b0;
                            state        <= EX_HALT_DRAIN;
                        end
                    end

                    else if (!condition_met) begin
                        `SIMLOG(("Condition not met (cond=%h), skipping instruction", condition));
                        execute_done <= 1'b1;
                        clear_forwarding();
                    end

                    else if (instr_class == CLASS_BR) begin
                        case (br_op_t'(opcode))
                            BR_BL: begin
                                data_in_registers[REG_LR] <= data_out_pc;
                                set_forwarding(REG_LR, data_out_pc);
                                execute_done <= 1'b1;
                                `SIMLOG(("BL: Saving PC=%0d to R14 (LR)", data_out_pc));
                                `SIMLOG(("BRANCH: Jumping to address %0d", branch_target));
                            end
                            BR_ABS: begin
                                logic [ADDR_WIDTH-1:0] br_b, br_result;
                                br_b = operand_b;
                                if (br_b[ADDR_WIDTH-1])
                                    br_result = (~br_b) + ADDR_WIDTH'(1);
                                else
                                    br_result = br_b;
                                write_exec_result(br_result);
                                execute_done <= 1'b1;
                                `SIMLOG(("ABS: op2=%0d (0x%h) -> %0d (0x%h)",
                                         $signed(br_b), br_b, $signed(br_result), br_result));
                            end
                            BR_MAX: begin
                                logic [ADDR_WIDTH-1:0] br_a, br_b, br_result;
                                br_a = read_operand(rn);
                                br_b = operand_b;
                                br_result = ($signed(br_a) >= $signed(br_b)) ? br_a : br_b;
                                write_exec_result(br_result);
                                execute_done <= 1'b1;
                                `SIMLOG(("MAX: a=%0d (0x%h), b=%0d (0x%h) -> %0d (0x%h)",
                                         $signed(br_a), br_a, $signed(br_b), br_b,
                                         $signed(br_result), br_result));
                            end
                            BR_MIN: begin
                                logic [ADDR_WIDTH-1:0] br_a, br_b, br_result;
                                br_a = read_operand(rn);
                                br_b = operand_b;
                                br_result = ($signed(br_a) <= $signed(br_b)) ? br_a : br_b;
                                write_exec_result(br_result);
                                execute_done <= 1'b1;
                                `SIMLOG(("MIN: a=%0d (0x%h), b=%0d (0x%h) -> %0d (0x%h)",
                                         $signed(br_a), br_a, $signed(br_b), br_b,
                                         $signed(br_result), br_result));
                            end
                            BR_MADD: begin
                                logic [ADDR_WIDTH-1:0] br_acc, br_a, br_b, br_result;
                                logic [(ADDR_WIDTH*2)-1:0] br_mul_full;
                                br_acc = read_rd_operand();
                                br_a = read_operand(rn);
                                br_b = operand_b;
                                br_mul_full = br_a * br_b;
                                br_result = br_acc + br_mul_full[ADDR_WIDTH-1:0];
                                write_exec_result(br_result);
                                execute_done <= 1'b1;
                                `SIMLOG(("MADD: acc=%0d (0x%h), a=%0d (0x%h), b=%0d (0x%h) -> %0d (0x%h)",
                                         br_acc, br_acc, br_a, br_a, br_b, br_b, br_result, br_result));
                            end
                            BR_QADD: begin
                                logic [ADDR_WIDTH-1:0] q_a, q_b, q_res;
                                logic signed [SAT_W-1:0] q_wide;
                                q_a = read_operand(rn);
                                q_b = operand_b;
                                q_wide = $signed({q_a[ADDR_WIDTH-1], q_a})
                                       + $signed({q_b[ADDR_WIDTH-1], q_b});
                                q_res = saturate_wide(q_wide);
                                write_exec_result(q_res);
                                execute_done <= 1'b1;
                                `SIMLOG(("QADD: %0d + %0d -> %0d",
                                         $signed(q_a), $signed(q_b), $signed(q_res)));
                            end
                            BR_QSUB: begin
                                logic [ADDR_WIDTH-1:0] q_a, q_b, q_res;
                                logic signed [SAT_W-1:0] q_wide;
                                q_a = read_operand(rn);
                                q_b = operand_b;
                                q_wide = $signed({q_a[ADDR_WIDTH-1], q_a})
                                       - $signed({q_b[ADDR_WIDTH-1], q_b});
                                q_res = saturate_wide(q_wide);
                                write_exec_result(q_res);
                                execute_done <= 1'b1;
                                `SIMLOG(("QSUB: %0d - %0d -> %0d",
                                         $signed(q_a), $signed(q_b), $signed(q_res)));
                            end
                            BR_SSAT: begin
                                logic [ADDR_WIDTH-1:0] q_a, q_b, q_res;
                                q_a = read_operand(rn);
                                q_b = operand_b;
                                q_res = saturate_signed_bits(q_a, q_b[4:0]);
                                write_exec_result(q_res);
                                execute_done <= 1'b1;
                                `SIMLOG(("SSAT: %0d to %0d bits -> %0d",
                                         $signed(q_a), q_b[4:0], $signed(q_res)));
                            end
                            BR_USAT: begin
                                logic [ADDR_WIDTH-1:0] q_a, q_b, q_res;
                                q_a = read_operand(rn);
                                q_b = operand_b;
                                q_res = saturate_unsigned_bits(q_a, q_b[4:0]);
                                write_exec_result(q_res);
                                execute_done <= 1'b1;
                                `SIMLOG(("USAT: %0d to %0d bits -> %0d",
                                         $signed(q_a), q_b[4:0], q_res));
                            end
                            BR_QRDMULH: begin
                                logic [ADDR_WIDTH-1:0] q_a, q_b, q_res;
                                q_a = read_operand(rn);
                                q_b = operand_b;
                                q_res = qrdmulh(q_a, q_b);
                                write_exec_result(q_res);
                                execute_done <= 1'b1;
                                `SIMLOG(("QRDMULH: %0d x %0d -> %0d",
                                         $signed(q_a), $signed(q_b), $signed(q_res)));
                            end
                            BR_RSHR: begin
                                logic [ADDR_WIDTH-1:0] q_a, q_b, q_res;
                                q_a = read_operand(rn);
                                q_b = operand_b;
                                q_res = rounding_shift(q_a, q_b[4:0]);
                                write_exec_result(q_res);
                                execute_done <= 1'b1;
                                `SIMLOG(("RSHR: %0d >> %0d -> %0d",
                                         $signed(q_a), q_b[4:0], $signed(q_res)));
                            end
                            BR_RELU: begin
                                logic [ADDR_WIDTH-1:0] q_a, q_b, q_res;
                                q_a = read_operand(rn);
                                q_b = operand_b;
                                q_res = relu_clamp(q_a, q_b);
                                write_exec_result(q_res);
                                execute_done <= 1'b1;
                                `SIMLOG(("RELU: %0d ceiling %0d -> %0d",
                                         $signed(q_a), $signed(q_b), $signed(q_res)));
                            end
                            BR_SXTB: begin
                                logic [ADDR_WIDTH-1:0] q_b, q_res;
                                q_b = operand_b;
                                q_res = {{(ADDR_WIDTH-8){q_b[7]}}, q_b[7:0]};
                                write_exec_result(q_res);
                                execute_done <= 1'b1;
                                `SIMLOG(("SXTB: 0x%0h -> %0d", q_b[7:0], $signed(q_res)));
                            end
                            BR_PIXELNB: `PIXEL_ISSUE(1'b0)
                            BR_WAITKNB: begin
                                write_exec_result({{(ADDR_WIDTH-4){1'b0}}, waitk_hit_now});
                                execute_done <= 1'b1;
                                `SIMLOG(("WAITKNB: hit mask=0x%0h selected=0x%0h", waitk_hit_now, waitk_mask_now));
                            end
                            default: begin
                                clear_forwarding();
                                execute_done <= 1'b1;
                                `SIMLOG(("BRANCH: Jumping to address %0d", branch_target));
                            end
                        endcase
                    end

                    else if (instr_class == CLASS_EXT) begin
                        case (ext_op_t'(opcode))
                            EXT_MUL: begin
                                logic [ADDR_WIDTH-1:0] mul_a, mul_b, mul_result;
                                logic [(ADDR_WIDTH*2)-1:0] mul_full;
                                mul_a = read_operand(rn);
                                mul_b = operand_b;
                                mul_full = mul_a * mul_b;
                                mul_result = mul_full[ADDR_WIDTH-1:0];
                                `SIMLOG(("MUL: %0d * %0d = %0d", mul_a, mul_b, mul_result));
                                write_exec_result(mul_result);
                                execute_done <= 1'b1;
                            end
                            EXT_DIV: begin
                                div_a_r <= read_operand(rn);
                                div_b_r <= operand_b;
                                clear_forwarding();
                                execute_done <= 1'b0;
                                state        <= EX_DIV_START;
                            end
                            EXT_SETMA: begin
                                mar_a      <= imm_ext;
                                mat_rows_a <= rn;
                                mat_cols_a <= rd;
                                clear_forwarding();
                                execute_done <= 1'b1;
                                `SIMLOG(("SETMA: A addr=%0d rows=%0d cols=%0d", second_operand, rn, rd));
                            end
                            EXT_SETMB: begin
                                mar_b      <= imm_ext;
                                mat_cols_b <= rd;
                                clear_forwarding();
                                execute_done <= 1'b1;
                                `SIMLOG(("SETMB: B addr=%0d cols=%0d", second_operand, rd));
                            end
                            EXT_SETMR: begin
                                mar_r <= imm_ext;
                                clear_forwarding();
                                execute_done <= 1'b1;
                                `SIMLOG(("SETMR: result addr=%0d", second_operand));
                            end
                            EXT_PIXEL: `PIXEL_ISSUE(1'b1)
                            EXT_TEXT: begin
                                logic [ADDR_WIDTH-1:0] tx_x, tx_y, tx_ptr_start, tx_color_full;
                                tx_x = read_operand(rd);
                                tx_y = read_operand(rn);
                                tx_ptr_start = operand_b;
                                tx_color_full = read_operand(4'd12);

                                text_base_x <= tx_x;
                                text_base_y <= tx_y;
                                text_char_x_base <= tx_x;
                                text_ptr <= tx_ptr_start;
                                text_char_code <= '0;
                                text_color <= tx_color_full[7:0];
                                text_char_count <= '0;
                                text_row <= '0;
                                text_col <= '0;

                                ram_read_addr_r <= tx_ptr_start;
                                clear_forwarding();
                                execute_done <= 1'b0;
                                state        <= EX_TEXT_WAIT_CHAR;
                                `SIMLOG(("TEXT: x=%0d y=%0d ptr=%0d color=%0d",
                                         tx_x, tx_y, tx_ptr_start, tx_color_full[7:0]));
                            end
                            EXT_MMUL: begin
                                mat_i <= '0; mat_j <= '0; mat_k <= '0; mat_preload_k <= '0;
                                mat_accum  <= 32'd0;
                                a_row_base <= mar_a;
                                b_col_base <= mar_b;
                                r_row_base <= mar_r;
                                b_k_offset <= '0;
                                ram_read_addr_r <= mar_a;
                                clear_forwarding();
                                execute_done <= 1'b0;
                                state        <= EX_MAT_WAIT_A;
                                `SIMLOG(("MMUL: A(%0dx%0d)@%0d x B(%0dx%0d)@%0d -> R@%0d",
                                         mat_rows_a, mat_cols_a, mar_a,
                                         mat_cols_a, mat_cols_b, mar_b, mar_r));
                            end
                            EXT_FADD,
                            EXT_FSUB,
                            EXT_FMUL,
                            EXT_FDIV,
                            EXT_FCMP,
                            EXT_FMOV: begin
                                if (immediate && !fp_imm_cache_hit) begin
                                    fp_imm_addr   <= imm_ext;
                                    ram_read_addr_r <= imm_ext;
                                    clear_forwarding();
                                    execute_done  <= 1'b0;
                                    state         <= exec_state_t'(data_prefetch_valid ? EX_FP_IMM_LATCH_LO : EX_FP_IMM_WAIT_LO);
                                end else begin
                                    fp_a_r  <= fp_op_a_value;
                                    fp_b_r  <= fp_op_b_value;
                                    fp_op_r <= fp_unit_op;
                                    clear_forwarding();
                                    execute_done <= 1'b0;
                                    if (ext_op_t'(opcode) == EXT_FDIV) begin
                                        state <= EX_FP_START;
                                    end else begin
                                        fp_settle_count <= 3'(FP_SETTLE_CYCLES);
                                        state           <= EX_FP_SETTLE;
                                    end
                                end
                            end
                            EXT_WAITK: begin
                                if (waitk_hit_now != 4'b0000) begin
                                    write_exec_result({{(ADDR_WIDTH-4){1'b0}}, waitk_hit_now});
                                    execute_done <= 1'b1;
                                    `SIMLOG(("WAITK: immediate hit mask=0x%0h selected=0x%0h", waitk_hit_now, waitk_mask_now));
                                end else begin
                                    waitk_selected_mask <= waitk_mask_now;
                                    clear_forwarding();
                                    execute_done <= 1'b0;
                                    state        <= EX_WAIT_KEY;
                                    `SIMLOG(("WAITK: waiting for selected mask=0x%0h", waitk_mask_now));
                                end
                            end
                            default: begin
                                wait_cycles  <= (second_operand * CYCLES_PER_MS) > 0
                                                ? (second_operand * CYCLES_PER_MS) : 32'd1;
                                wait_counter <= '0;
                                clear_forwarding();
                                execute_done <= 1'b0;
                                state        <= EX_WAITING;
                                if (ext_op_t'(opcode) == EXT_WAIT)
                                    `SIMLOG(("WAIT: starting wait for %0d ms (%0d cycles)",
                                             second_operand, second_operand * CYCLES_PER_MS));
                                else
                                    `SIMLOG(("WAIT (fallback): starting wait for %0d ms (%0d cycles)",
                                             second_operand, second_operand * CYCLES_PER_MS));
                            end
                        endcase
                    end

                    else if (instr_class == CLASS_MEM) begin
                        case (mem_op_t'(opcode))
                            MEM_PUSH: begin
                                logic [ADDR_WIDTH-1:0] sp_value, sp_next, push_value;
                                sp_value   = get_reg_value(REG_SP);
                                sp_next    = sp_value - ADDR_WIDTH'(MEM_TRANSFER_BYTES);
                                push_value = read_rd_operand();
                                mem_multi_addr  <= sp_next;
                                mem_multi_value <= push_value;
                                mem_multi_index <= '0;
                                ram_write_addr_r  <= sp_next;
                                ram_write_data_r  <= extract_mem_chunk(push_value, 0);
                                ram_write_en_r    <= 1'b1;
                                invalidate_fp_literal_cache(sp_next);
                                data_in_registers[REG_SP] <= sp_next;
                                set_forwarding(REG_SP, sp_next);
                                stack_addr       <= sp_next;
                                stack_pop_active <= 1'b0;
                                execute_done     <= 1'b0;
                                state <= (MEM_TRANSFER_BYTES > 1) ? EX_MEM_STORE_MULTI
                                                                  : EX_MEM_STORE;
                                `SIMLOG(("STACK_PUSH: Stored value %0d (0x%h) from R%0d at address %0d (%0d byte(s), little-endian)",
                                         push_value, push_value, rd, sp_next, MEM_TRANSFER_BYTES));
                            end
                            MEM_POP: begin
                                logic [ADDR_WIDTH-1:0] sp_value;
                                sp_value = get_reg_value(REG_SP);
                                mem_multi_addr   <= sp_value;
                                mem_multi_value  <= '0;
                                mem_multi_index  <= '0;
                                ram_read_addr_r    <= sp_value;
                                stack_addr       <= sp_value;
                                stack_pop_active <= 1'b1;
                                mem_multi_pending <= (MEM_TRANSFER_BYTES > 1);
                                clear_forwarding();
                                execute_done <= 1'b0;
                                state        <= exec_state_t'(data_prefetch_valid
                                    ? ((MEM_TRANSFER_BYTES > 1) ? EX_MEM_LOAD_MULTI : EX_MEM_LOAD_SYNC)
                                    : EX_MEM_LOAD_WAIT);
                                `SIMLOG(("STACK_POP: Reading %0d byte(s) from address %0d into R%0d",
                                         MEM_TRANSFER_BYTES, sp_value, rd));
                            end
                            MEM_STORE_MULTI: begin
                                logic [ADDR_WIDTH-1:0] store_value, mem_addr;
                                store_value = read_rd_operand();
                                mem_addr    = resolved_mem_addr;
                                mem_multi_addr  <= mem_addr;
                                mem_multi_value <= store_value;
                                mem_multi_index <= '0;
                                ram_write_addr_r  <= mem_addr;
                                ram_write_data_r  <= extract_mem_chunk(store_value, 0);
                                ram_write_en_r    <= 1'b1;
                                invalidate_fp_literal_cache(mem_addr);
                                clear_forwarding();
                                stack_pop_active <= 1'b0;
                                execute_done <= 1'b0;
                                state <= (MEM_TRANSFER_BYTES > 1) ? EX_MEM_STORE_MULTI
                                                                  : EX_MEM_STORE;
                                `SIMLOG(("MEM_STORE_MULTI: Stored value %0d (0x%h) from R%0d at address %0d (%0d byte(s), little-endian)",
                                         store_value, store_value, rd, mem_addr, MEM_TRANSFER_BYTES));
                            end
                            MEM_LOAD_MULTI: begin
                                logic [ADDR_WIDTH-1:0] mem_addr;
                                mem_addr = resolved_mem_addr;
                                mem_multi_addr   <= mem_addr;
                                mem_multi_value  <= '0;
                                mem_multi_index  <= '0;
                                ram_read_addr_r    <= mem_addr;
                                stack_pop_active <= 1'b0;
                                mem_multi_pending <= 1'b1;
                                clear_forwarding();
                                execute_done     <= 1'b0;
                                state            <= exec_state_t'(data_prefetch_valid ? EX_MEM_LOAD_MULTI : EX_MEM_LOAD_WAIT);
                                `SIMLOG(("MEM_LOAD_MULTI: Reading %0d byte(s) from address %0d into R%0d (little-endian)",
                                         MEM_TRANSFER_BYTES, mem_addr, rd));
                            end
                            MEM_NPU: begin
                                stack_pop_active  <= 1'b0;
                                mem_multi_pending <= 1'b0;
                                case (npu_op_t'(npu_op))
                                    NPU_VLD: begin
                                        vec_addr   <= resolved_mem_addr;
                                        vec_target <= npu_vd;
                                        vec_index  <= '0;
                                        vec_value  <= '0;
                                        ram_read_addr_r <= resolved_mem_addr;
                                        clear_forwarding();
                                        execute_done <= 1'b0;
                                        state <= exec_state_t'(data_prefetch_valid
                                            ? EX_VEC_LOAD : EX_VEC_LOAD_WAIT);
                                        `SIMLOG(("VLD: V%0d from address %0d",
                                                 npu_vd, resolved_mem_addr));
                                    end
                                    NPU_VST: begin
                                        logic [NPU_VEC_WIDTH-1:0] v_out;
                                        v_out = vreg[npu_vd];
                                        vec_addr  <= resolved_mem_addr;
                                        vec_value <= {8'd0, v_out[NPU_VEC_WIDTH-1:8]};
                                        vec_index <= 1;
                                        ram_write_addr_r <= resolved_mem_addr;
                                        ram_write_data_r <= v_out[7:0];
                                        ram_write_en_r   <= 1'b1;
                                        invalidate_fp_literal_cache(resolved_mem_addr);
                                        clear_forwarding();
                                        execute_done <= 1'b0;
                                        state <= EX_VEC_STORE;
                                        `SIMLOG(("VST: V%0d to address %0d",
                                                 npu_vd, resolved_mem_addr));
                                    end
                                    NPU_VDOT: begin
                                        logic signed [31:0] dot_next;
                                        dot_next = acc_file[npu_ad]
                                                 + vector_dot(vreg[npu_sel_a], vreg[npu_sel_b]);
                                        acc_file[npu_ad] <= dot_next;
                                        clear_forwarding();
                                        execute_done <= 1'b1;
                                        `SIMLOG(("VDOT: A%0d = %0d", npu_ad, dot_next));
                                    end
                                    NPU_VSUM: begin
                                        logic signed [31:0] sum_next;
                                        sum_next = acc_file[npu_ad] + vector_sum(vreg[npu_sel_a]);
                                        acc_file[npu_ad] <= sum_next;
                                        clear_forwarding();
                                        execute_done <= 1'b1;
                                        `SIMLOG(("VSUM: A%0d = %0d", npu_ad, sum_next));
                                    end
                                    NPU_VMAXR: begin
                                        logic signed [7:0] lane_max;
                                        lane_max = vector_max(vreg[npu_sel_a]);
                                        write_exec_result({{(ADDR_WIDTH-8){lane_max[7]}}, lane_max});
                                        execute_done <= 1'b1;
                                        `SIMLOG(("VMAXR: V%0d -> %0d", npu_sel_a, lane_max));
                                    end
                                    NPU_VDUP: begin
                                        logic [ADDR_WIDTH-1:0] dup_src;
                                        dup_src = operand_b;
                                        vreg[npu_vd] <= {NPU_LANES{dup_src[7:0]}};
                                        clear_forwarding();
                                        execute_done <= 1'b1;
                                        `SIMLOG(("VDUP: V%0d = 0x%0h", npu_vd, dup_src[7:0]));
                                    end
                                    NPU_VEXT: begin
                                        logic [NPU_VEC_WIDTH-1:0] v_src;
                                        logic signed [7:0] lane_value;
                                        v_src = vreg[npu_sel_a];
                                        lane_value = v_src[{npu_lane, 3'b000} +: 8];
                                        write_exec_result({{(ADDR_WIDTH-8){lane_value[7]}}, lane_value});
                                        execute_done <= 1'b1;
                                        `SIMLOG(("VEXT: V%0d lane %0d -> %0d",
                                                 npu_sel_a, npu_lane, lane_value));
                                    end
                                    NPU_VINS: begin
                                        logic [NPU_VEC_WIDTH-1:0] v_dst;
                                        logic [ADDR_WIDTH-1:0] ins_src;
                                        v_dst   = vreg[npu_vd];
                                        ins_src = read_operand(npu_src);
                                        v_dst[{npu_lane, 3'b000} +: 8] = ins_src[7:0];
                                        vreg[npu_vd] <= v_dst;
                                        clear_forwarding();
                                        execute_done <= 1'b1;
                                        `SIMLOG(("VINS: V%0d lane %0d = 0x%0h",
                                                 npu_vd, npu_lane, ins_src[7:0]));
                                    end
                                    NPU_ACLR: begin
                                        acc_file[npu_ad] <= 32'sd0;
                                        clear_forwarding();
                                        execute_done <= 1'b1;
                                        `SIMLOG(("ACLR: A%0d = 0", npu_ad));
                                    end
                                    NPU_ASET: begin
                                        logic [ADDR_WIDTH-1:0] set_src;
                                        set_src = operand_b;
                                        acc_file[npu_ad] <=
                                            $signed({{(32-ADDR_WIDTH){set_src[ADDR_WIDTH-1]}}, set_src});
                                        clear_forwarding();
                                        execute_done <= 1'b1;
                                        `SIMLOG(("ASET: A%0d = %0d", npu_ad, $signed(set_src)));
                                    end
                                    NPU_AGET: begin
                                        logic signed [31:0] acc_value;
                                        acc_value = acc_file[npu_acc_a];
                                        write_exec_result(acc_value[ADDR_WIDTH-1:0]);
                                        execute_done <= 1'b1;
                                        `SIMLOG(("AGET: A%0d = %0d", npu_acc_a, acc_value));
                                    end
                                    NPU_AGETS: begin
                                        logic signed [31:0] acc_value;
                                        acc_value = acc_file[npu_acc_a];
                                        write_exec_result(saturate_acc(acc_value));
                                        execute_done <= 1'b1;
                                        `SIMLOG(("AGETS: A%0d = %0d saturated", npu_acc_a, acc_value));
                                    end
                                    NPU_AQMUL: begin
                                        logic [ADDR_WIDTH-1:0] mul_src;
                                        logic signed [31:0] scaled;
                                        mul_src = operand_b;
                                        scaled  = acc_qmul(acc_file[npu_ad], mul_src[15:0]);
                                        acc_file[npu_ad] <= scaled;
                                        clear_forwarding();
                                        execute_done <= 1'b1;
                                        `SIMLOG(("AQMUL: A%0d = %0d", npu_ad, scaled));
                                    end
                                    NPU_ARSHR: begin
                                        logic [ADDR_WIDTH-1:0] shift_src;
                                        logic signed [31:0] shifted;
                                        shift_src = operand_b;
                                        shifted   = acc_rounding_shift(acc_file[npu_ad], shift_src[4:0]);
                                        acc_file[npu_ad] <= shifted;
                                        clear_forwarding();
                                        execute_done <= 1'b1;
                                        `SIMLOG(("ARSHR: A%0d = %0d", npu_ad, shifted));
                                    end
                                    NPU_NPUCFG: begin
                                        npu_cfg_write <= 1'b1;
                                        npu_cfg_index <= npu_cfg_sel;
                                        npu_cfg_value <= operand_b;
                                        clear_forwarding();
                                        execute_done <= 1'b1;
                                        `SIMLOG(("NPUCFG: cfg[%0d] = %0d", npu_cfg_sel, operand_b));
                                    end
                                    default: begin
                                        npu_start <= 1'b1;
                                        clear_forwarding();
                                        execute_done <= 1'b0;
                                        state <= EX_NPU_RUN;
                                        `SIMLOG(("NPURUN: starting tensor engine"));
                                    end
                                endcase
                            end
                            MEM_STORE: begin
                                logic [ADDR_WIDTH-1:0] store_value, mem_addr;
                                store_value = read_rd_operand();
                                mem_addr    = resolved_mem_addr;
                                ram_write_addr_r <= mem_addr;
                                ram_write_data_r <= store_value[DATA_WIDTH-1:0];
                                ram_write_en_r   <= 1'b1;
                                invalidate_fp_literal_cache(mem_addr);
                                clear_forwarding();
                                stack_pop_active <= 1'b0;
                                execute_done     <= 1'b1;
                                `SIMLOG(("MEM_STORE: Stored value %0d (0x%h) from R%0d at address %0d",
                                         store_value[DATA_WIDTH-1:0], store_value[DATA_WIDTH-1:0], rd, mem_addr));
                            end
                            default: begin
                                logic [ADDR_WIDTH-1:0] mem_addr;
                                mem_addr = resolved_mem_addr;
                                ram_read_addr_r    <= mem_addr;
                                stack_pop_active <= 1'b0;
                                mem_multi_pending <= 1'b0;
                                execute_done     <= 1'b0;
                                state            <= exec_state_t'(data_prefetch_valid ? EX_MEM_LOAD_SYNC : EX_MEM_LOAD_WAIT);
                                `SIMLOG(("MEM_LOAD: Reading from address %0d into R%0d", mem_addr, rd));
                            end
                        endcase
                    end

                    else begin
                        case (alu_op_t'(opcode))
                            OP_TST,
                            OP_TEQ,
                            OP_CMP,
                            OP_CMN: begin
                                data_in_cpsr <= {
                                    dp_alu_negative,
                                    dp_alu_zero,
                                    dp_alu_carry,
                                    dp_alu_overflow,
                                    28'b0
                                };
                                clear_forwarding();
                                `SIMLOG(("Comparison: result=%h, N=%b Z=%b C=%b V=%b",
                                         dp_alu_result, dp_alu_negative, dp_alu_zero,
                                         dp_alu_carry, dp_alu_overflow));
                            end
                            default: begin
                                write_exec_result(dp_alu_result);
                            end
                        endcase

                        execute_done <= 1'b1;
                    end
                end
                else if (!execute_instr && !halted)
                    execute_done <= 1'b0;
                else if (halted)
                    execute_done <= 1'b1;
            end
