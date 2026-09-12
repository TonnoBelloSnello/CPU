            EX_WAITING: begin
                if (wait_counter < wait_cycles) begin
                    wait_counter <= wait_counter + 1'b1;
                    execute_done <= 1'b0;
                end else begin
                    execute_done <= 1'b1;
                    state        <= EX_IDLE;
                end
            end

            EX_WAIT_KEY: begin
                if (waitk_hit_mask != 4'b0000) begin
                    write_exec_result({{(ADDR_WIDTH-4){1'b0}}, waitk_hit_mask});
                    execute_done <= 1'b1;
                    state        <= EX_IDLE;
                    `SIMLOG(("WAITK: hit mask=0x%0h selected=0x%0h", waitk_hit_mask, waitk_selected_mask));
                end else begin
                    execute_done <= 1'b0;
                end
            end

            EX_HALT_DRAIN: begin
                if (queue_count_next == '0 && !fb_write_pending_next) begin
                    halted       <= 1'b1;
                    halt_pending <= 1'b0;
                    execute_done <= 1'b1;
                    state        <= EX_IDLE;
                    `SIM_FINISH;
                end else begin
                    execute_done <= 1'b0;
                end
            end

            EX_PIXEL_ENQUEUE_WAIT: begin
                execute_done <= 1'b0;
                if (queue_has_space) begin
                    `ENQUEUE_PIXEL(pending_fb_addr, pending_fb_data, pending_fb_x, pending_fb_y);
                    state <= exec_state_t'(pixel_blocking ? EX_PIXEL_COMMIT_WAIT : EX_IDLE);
                    if (!pixel_blocking) execute_done <= 1'b1;
                end
            end

            EX_PIXEL_COMMIT_WAIT: begin
                execute_done <= (queue_count_next == '0 && !fb_write_pending_next);
                if (queue_count_next == '0 && !fb_write_pending_next)
                    state <= EX_IDLE;
            end

            EX_MEM_STORE: begin
                execute_done <= 1'b1;
                state        <= EX_IDLE;
            end
            
            EX_MEM_LOAD_WAIT: begin
                if (mem_multi_pending)
                    state <= EX_MEM_LOAD_MULTI;
                else
                    state <= EX_MEM_LOAD_SYNC;
            end

            EX_MEM_LOAD_SYNC: begin
                write_load_destination(ram_data_ext);

                if (stack_pop_active) begin
                    finish_stack_pop();
                    `SIMLOG(("STACK_POP: Loaded value %0d (0x%h) from address %0d into %s",
                             ram_data_out, ram_data_out, stack_addr, dest_name()));
                end else begin
                    last_write2_valid <= 1'b0;
                    `SIMLOG(("MEM_LOAD: Loaded value %0d (0x%h) from address %0d into %s",
                             ram_data_out, ram_data_out, ram_read_addr_r, dest_name()));
                end
                
                execute_done <= 1'b1;
                state        <= EX_IDLE;
            end

            EX_MEM_STORE_MULTI: begin
                logic [ADDR_WIDTH-1:0] write_addr_next;
                int unsigned next_index;
                if ((mem_multi_index + 1'b1) < MEM_TRANSFER_BYTES) begin
                    next_index = mem_multi_index + 1;
                    write_addr_next = mem_multi_addr + ADDR_WIDTH'(next_index);
                    mem_multi_index <= MEM_INDEX_WIDTH'(next_index);
                    ram_write_addr_r  <= write_addr_next;
                    ram_write_data_r  <= extract_mem_chunk(mem_multi_value, next_index);
                    ram_write_en_r    <= 1'b1;
                    invalidate_fp_literal_cache(write_addr_next);
                    execute_done    <= 1'b0;
                end else begin
                    execute_done <= 1'b1;
                    state        <= EX_IDLE;
                end
            end

            EX_MEM_LOAD_MULTI: begin
                logic [ADDR_WIDTH-1:0] next_value;
                int unsigned next_index;
                next_value = insert_mem_chunk(mem_multi_value, ram_data_out, mem_multi_index);

                if ((mem_multi_index + 1'b1) < MEM_TRANSFER_BYTES) begin
                    next_index = mem_multi_index + 1;
                    mem_multi_value <= next_value;
                    mem_multi_index <= MEM_INDEX_WIDTH'(next_index);
                    ram_read_addr_r   <= mem_multi_addr + ADDR_WIDTH'(next_index);
                    execute_done    <= 1'b0;
                    state           <= exec_state_t'(data_prefetch_valid ? EX_MEM_LOAD_MULTI : EX_MEM_LOAD_MULTI_WAIT);
                end else begin
                    write_load_destination(next_value);
                    if (stack_pop_active) begin
                        finish_stack_pop();
                        `SIMLOG(("STACK_POP: Loaded value %0d (0x%h) from address %0d into %s",
                                 next_value, next_value, stack_addr, dest_name()));
                    end else begin
                        last_write2_valid <= 1'b0;
                        `SIMLOG(("MEM_LOAD_MULTI: Loaded value %0d (0x%h) from address %0d into %s",
                                 next_value, next_value, mem_multi_addr, dest_name()));
                    end
                    execute_done <= 1'b1;
                    state        <= EX_IDLE;
                end
            end

            EX_MEM_LOAD_MULTI_WAIT: begin
                state <= EX_MEM_LOAD_MULTI;
            end

            EX_MAT_WAIT_A: begin
                state <= EX_MAT_WAIT_A2;
            end

            EX_MAT_WAIT_A2: begin
                mat_a_row_cache[mat_preload_k] <= ram_data_out;
                if (mat_preload_k + MAT_ONE < mat_cols_a) begin
                    mat_preload_k <= mat_preload_k + MAT_ONE;
                    ram_read_addr_r <= a_row_base + ADDR_WIDTH'(mat_preload_k) + 1'b1;
                    state         <= exec_state_t'(data_prefetch_valid ? EX_MAT_WAIT_A2 : EX_MAT_WAIT_A);
                end else begin
                    mat_j      <= '0;
                    b_col_base <= mar_b;
                    mat_k      <= '0;
                    b_k_offset <= '0;
                    mat_accum  <= 32'd0;
                    ram_read_addr_r <= mar_b;
                    state      <= EX_MAT_WAIT_B;
                end
            end

            EX_MAT_WAIT_B: begin
                state <= EX_MAT_WAIT_B2;
            end

            EX_MAT_WAIT_B2: begin
                if (mat_k + MAT_ONE < mat_cols_a) begin
                    mat_accum  <= mat_accum_next;
                    mat_k      <= mat_k + MAT_ONE;
                    b_k_offset <= b_k_offset + ADDR_WIDTH'(mat_cols_b);
                    ram_read_addr_r <= b_col_base + b_k_offset + ADDR_WIDTH'(mat_cols_b);
                    state <= exec_state_t'(data_prefetch_valid ? EX_MAT_WAIT_B2 : EX_MAT_WAIT_B);
                end else begin
                    logic [ADDR_WIDTH-1:0] mat_write_addr;
                    mat_write_addr = r_row_base + ADDR_WIDTH'(mat_j);
                    ram_write_addr_r <= mat_write_addr;
                    ram_write_data_r <= mat_accum_next[DATA_WIDTH-1:0];
                    ram_write_en_r   <= 1'b1;
                    invalidate_fp_literal_cache(mat_write_addr);
                    `SIMLOG(("MMUL: R[%0d][%0d] = %0d",
                             mat_i, mat_j, mat_accum_next[DATA_WIDTH-1:0]));
                    if (mat_j + MAT_ONE < mat_cols_b) begin
                        mat_j      <= mat_j + MAT_ONE;
                        b_col_base <= b_col_base + 1'b1;
                        mat_k      <= '0;
                        b_k_offset <= '0;
                        mat_accum  <= 32'd0;
                        ram_read_addr_r <= b_col_base + 1'b1;
                        state <= EX_MAT_WAIT_B;
                    end else if (mat_i + MAT_ONE < mat_rows_a) begin
                        logic [ADDR_WIDTH-1:0] next_a_row_base;
                        next_a_row_base = a_row_base + ADDR_WIDTH'(mat_cols_a);
                        mat_i      <= mat_i + MAT_ONE;
                        a_row_base <= next_a_row_base;
                        r_row_base <= r_row_base + ADDR_WIDTH'(mat_cols_b);
                        mat_j      <= '0;
                        b_col_base <= mar_b;
                        mat_preload_k <= '0;
                        mat_k      <= '0;
                        b_k_offset <= '0;
                        mat_accum  <= 32'd0;
                        ram_read_addr_r <= next_a_row_base;
                        state <= EX_MAT_WAIT_A;
                    end else begin
                        write_exec_result(mar_r);
                        execute_done <= 1'b1;
                        state        <= EX_IDLE;
                    end
                end
            end

            EX_TEXT_WAIT_CHAR: begin
                execute_done <= 1'b0;
                state        <= EX_TEXT_LATCH_CHAR;
            end

            EX_TEXT_LATCH_CHAR: begin
                if (text_char_count >= TEXT_MAX_RENDER_CHARS || ram_data_out == 8'h00) begin
                    execute_done <= 1'b1;
                    state        <= EX_IDLE;
                end else begin
                    text_char_code <= ram_data_out;
                    text_row <= '0;
                    text_col <= '0;
                    execute_done <= 1'b0;
                    state <= EX_TEXT_DRAW;
                end
            end

            EX_TEXT_DRAW: begin
                logic [ADDR_WIDTH-1:0] tx_draw_x, tx_draw_y, next_text_ptr;
                logic [VGA_FB_ADDR_WIDTH-1:0] tx_addr;
                logic [4:0] tx_row_bits;
                logic tx_pixel_on;
                logic [4:0] next_char_count;
                logic text_stall;

                tx_draw_x = text_char_x_base + {{(ADDR_WIDTH-3){1'b0}}, text_col};
                tx_draw_y = text_base_y + {{(ADDR_WIDTH-3){1'b0}}, text_row};
                tx_row_bits = text_glyph_row_bits;
                tx_pixel_on = (text_col < TEXT_GLYPH_WIDTH)
                    ? tx_row_bits[TEXT_GLYPH_WIDTH - 1 - text_col]
                    : 1'b0;
                tx_addr = vga_addr_from_xy(tx_draw_x, tx_draw_y);
                text_stall = 1'b0;

                if (tx_pixel_on && tx_draw_x < VGA_FB_WIDTH && tx_draw_y < VGA_FB_HEIGHT) begin
                    if (queue_has_space) begin
                        `ENQUEUE_PIXEL(tx_addr, text_color, tx_draw_x, tx_draw_y);
                    end else begin
                        text_stall = 1'b1;
                    end
                end

                execute_done <= 1'b0;
                if (!text_stall) begin
                    if (text_col + 1 < TEXT_GLYPH_ADVANCE) begin
                        text_col <= text_col + 1'b1;
                    end else begin
                        text_col <= '0;
                        if (text_row + 1 < TEXT_GLYPH_HEIGHT) begin
                            text_row <= text_row + 1'b1;
                        end else begin
                            next_char_count = text_char_count + 1'b1;
                            if (next_char_count >= TEXT_MAX_RENDER_CHARS) begin
                                execute_done <= 1'b1;
                                state        <= EX_IDLE;
                            end else begin
                                text_char_count <= next_char_count;
                                text_char_x_base <= text_char_x_base + ADDR_WIDTH'(TEXT_GLYPH_ADVANCE);
                                next_text_ptr = text_ptr + ADDR_WIDTH'(1);
                                text_ptr <= next_text_ptr;
                                ram_read_addr_r <= next_text_ptr;
                                state <= EX_TEXT_WAIT_CHAR;
                            end
                        end
                    end
                end
            end

            EX_FP_IMM_WAIT_LO: begin
                execute_done <= 1'b0;
                state        <= EX_FP_IMM_LATCH_LO;
            end

            EX_FP_IMM_LATCH_LO: begin
                fp_imm_lo    <= ram_data_out;
                ram_read_addr_r <= fp_imm_addr + 1'b1;
                execute_done <= 1'b0;
                state        <= exec_state_t'(data_prefetch_valid ? EX_FP_IMM_LATCH_HI : EX_FP_IMM_WAIT_HI);
            end

            EX_FP_IMM_WAIT_HI: begin
                execute_done <= 1'b0;
                state        <= EX_FP_IMM_LATCH_HI;
            end

            EX_FP_IMM_LATCH_HI: begin
                logic [15:0] fetched_fp_imm;
                fetched_fp_imm = {ram_data_out, fp_imm_lo};
                fp_imm_value <= fetched_fp_imm;
                if (!fp_cache_replace) begin
                    fp_cache_addr[0]  <= fp_imm_addr;
                    fp_cache_value[0] <= fetched_fp_imm;
                    fp_cache_valid[0] <= 1'b1;
                end else begin
                    fp_cache_addr[1]  <= fp_imm_addr;
                    fp_cache_value[1] <= fetched_fp_imm;
                    fp_cache_valid[1] <= 1'b1;
                end
                fp_cache_replace <= ~fp_cache_replace;
                fp_a_r       <= fp_op_a_value;
                fp_b_r       <= fetched_fp_imm;
                fp_op_r      <= fp_unit_op;
                execute_done <= 1'b0;
                if (ext_op_t'(opcode) == EXT_FDIV) begin
                    state <= EX_FP_START;
                end else begin
                    fp_settle_count <= 3'(FP_SETTLE_CYCLES);
                    state           <= EX_FP_SETTLE;
                end
            end

            EX_FP_START: begin
                execute_done <= 1'b0;
                div_start  <= 1'b1;
                div_for_fp <= 1'b1;
                state      <= EX_FP_DIV_WAIT;
            end

            EX_FP_DIV_WAIT: begin
                execute_done <= 1'b0;
                if (div_done) begin
                    fp_settle_count <= 3'(FP_SETTLE_CYCLES);
                    state           <= EX_FP_SETTLE;
                end
            end

            EX_FP_SETTLE: begin
                if (fp_settle_count == '0) begin
                    finish_fp_operation();
                    execute_done <= 1'b1;
                    state        <= EX_IDLE;
                end else begin
                    execute_done    <= 1'b0;
                    fp_settle_count <= fp_settle_count - 3'd1;
                end
            end

            EX_DIV_START: begin
                execute_done <= 1'b0;
                if (div_b_r == '0) begin
                    write_exec_result('0);
                    execute_done <= 1'b1;
                    state        <= EX_IDLE;
                    `SIMLOG(("DIV: %0d / %0d = %0d (divide-by-zero)", div_a_r, div_b_r, 0));
                end else begin
                    div_start  <= 1'b1;
                    div_for_fp <= 1'b0;
                    state      <= EX_DIV_WAIT;
                end
            end

            EX_DIV_WAIT: begin
                execute_done <= 1'b0;
                if (div_done) begin
                    write_exec_result(div_quotient[ADDR_WIDTH-1:0]);
                    execute_done <= 1'b1;
                    state        <= EX_IDLE;
                    `SIMLOG(("DIV: %0d / %0d = %0d",
                             div_a_r, div_b_r, div_quotient[ADDR_WIDTH-1:0]));
                end
            end

            EX_VEC_LOAD_WAIT: begin
                execute_done <= 1'b0;
                state        <= EX_VEC_LOAD;
            end

            EX_VEC_LOAD: begin
                logic [NPU_VEC_WIDTH-1:0] next_vec;
                next_vec = {ram_data_out, vec_value[NPU_VEC_WIDTH-1:8]};
                if ((vec_index + 1'b1) < NPU_LANES) begin
                    vec_value <= next_vec;
                    vec_index <= vec_index + 1'b1;
                    ram_read_addr_r <= vec_addr + ADDR_WIDTH'(vec_index) + ADDR_WIDTH'(1);
                    execute_done <= 1'b0;
                    state <= exec_state_t'(data_prefetch_valid ? EX_VEC_LOAD
                                                               : EX_VEC_LOAD_WAIT);
                end else begin
                    vreg[vec_target] <= next_vec;
                    execute_done <= 1'b1;
                    state        <= EX_IDLE;
                    `SIMLOG(("VLD: V%0d = 0x%0h", vec_target, next_vec));
                end
            end

            EX_VEC_STORE: begin
                if (vec_index < NPU_LANES) begin
                    logic [ADDR_WIDTH-1:0] vec_write_addr;
                    vec_write_addr = vec_addr + ADDR_WIDTH'(vec_index);
                    ram_write_addr_r <= vec_write_addr;
                    ram_write_data_r <= vec_value[7:0];
                    ram_write_en_r   <= 1'b1;
                    invalidate_fp_literal_cache(vec_write_addr);
                    vec_value    <= {8'd0, vec_value[NPU_VEC_WIDTH-1:8]};
                    vec_index    <= vec_index + 1'b1;
                    execute_done <= 1'b0;
                end else begin
                    execute_done <= 1'b1;
                    state        <= EX_IDLE;
                end
            end

            EX_NPU_RUN: begin
                if (npu_done) begin
                    write_exec_result(npu_result);
                    fp_cache_valid <= '0;
                    execute_done   <= 1'b1;
                    state          <= EX_IDLE;
                    `SIMLOG(("NPURUN: engine finished, result %0d", npu_result));
                end else begin
                    execute_done <= 1'b0;
                end
            end

            default: begin
                execute_done <= 1'b1;
                state        <= EX_IDLE;
            end
