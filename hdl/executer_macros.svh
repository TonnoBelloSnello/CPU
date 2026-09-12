`ifndef SIMLOG
    `ifdef SIMULATION
        `ifdef WEB_FAST_SIMULATION
            `define SIMLOG(args)
        `else
            `define SIMLOG(args) $display args
        `endif
        `ifdef SNAPSHOT_MODE
            `define SIM_FINISH
        `else
            `define SIM_FINISH $finish
        `endif
    `else
        `define SIMLOG(args)
        `define SIM_FINISH
    `endif
`endif

`ifndef SIMPIXELLOG
    `ifdef SIMULATION
        `define SIMPIXELLOG(args) $display args
    `else
        `define SIMPIXELLOG(args)
    `endif
`endif

`ifndef ENQUEUE_PIXEL
    `define ENQUEUE_PIXEL(a, d, px, py) \
        queue_enqueue_req  = 1'b1;      \
        queue_enqueue_addr = a;         \
        queue_enqueue_data = d;         \
        queue_enqueue_x    = px;        \
        queue_enqueue_y    = py
`endif

`ifndef PIXEL_ISSUE
    `define PIXEL_ISSUE(blocking) begin                          \
        px_x     = read_operand(rd);                             \
        px_y     = read_operand(rn);                             \
        px_color = operand_b;                                    \
        px_addr  = vga_addr_from_xy(px_x, px_y);                 \
        clear_forwarding();                                      \
        pixel_blocking <= (blocking);                            \
        if (px_x >= VGA_FB_WIDTH || px_y >= VGA_FB_HEIGHT) begin \
            execute_done <= 1'b1;                                \
        end else if (queue_has_space) begin                      \
            `ENQUEUE_PIXEL(px_addr, px_color[7:0], px_x, px_y);  \
            execute_done <= !(blocking);                         \
            if (blocking) state <= EX_PIXEL_COMMIT_WAIT;         \
        end else begin                                           \
            pending_fb_addr <= px_addr;                          \
            pending_fb_data <= px_color[7:0];                    \
            pending_fb_x    <= px_x;                             \
            pending_fb_y    <= px_y;                             \
            execute_done    <= 1'b0;                             \
            state           <= EX_PIXEL_ENQUEUE_WAIT;            \
        end                                                      \
    end
`endif
