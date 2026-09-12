module vga_controller (
    input  logic       vga_clk,
    input  logic       reset_n,
    output logic [7:0] VGA_R,
    output logic [7:0] VGA_G,
    output logic [7:0] VGA_B,
    output logic       VGA_HS,
    output logic       VGA_VS,
    output logic       VGA_BLANK_N,
    output logic       VGA_SYNC_N,
    output logic       VGA_CLK,

    output logic [cpu_pkg::VGA_FB_ADDR_WIDTH-1:0] fb_addr,
    input  logic [7:0]  fb_data
);

    localparam H_VISIBLE    = 1024;
    localparam H_FRONT      = 24;
    localparam H_SYNC       = 136;
    localparam H_BACK       = 160;
    localparam H_TOTAL      = H_VISIBLE + H_FRONT + H_SYNC + H_BACK;

    localparam V_VISIBLE    = 768;
    localparam V_FRONT      = 3;
    localparam V_SYNC       = 6;
    localparam V_BACK       = 29;
    localparam V_TOTAL      = V_VISIBLE + V_FRONT + V_SYNC + V_BACK;

    logic [10:0] h_count;
    logic [9:0]  v_count;

    always_ff @(posedge vga_clk or negedge reset_n) begin
        if (!reset_n) begin
            h_count <= '0;
        end else if (h_count == H_TOTAL - 1) begin
            h_count <= '0;
        end else begin
            h_count <= h_count + 1'b1;
        end
    end

    always_ff @(posedge vga_clk or negedge reset_n) begin
        if (!reset_n) begin
            v_count <= '0;
        end else if (h_count == H_TOTAL - 1) begin
            if (v_count == V_TOTAL - 1)
                v_count <= '0;
            else
                v_count <= v_count + 1'b1;
        end
    end

    wire hs_n = ~(h_count >= H_VISIBLE + H_FRONT &&
                  h_count <  H_VISIBLE + H_FRONT + H_SYNC);

    wire vs_n = ~(v_count >= V_VISIBLE + V_FRONT &&
                  v_count <  V_VISIBLE + V_FRONT + V_SYNC);

    wire active = (h_count < H_VISIBLE) && (v_count < V_VISIBLE);

    always_ff @(posedge vga_clk or negedge reset_n) begin
        if (!reset_n) begin
            VGA_HS     <= 1'b1;
            VGA_VS     <= 1'b1;
            VGA_BLANK_N <= 1'b0;
        end else begin
            VGA_HS     <= hs_n;
            VGA_VS     <= vs_n;
            VGA_BLANK_N <= active;
        end
    end

    assign VGA_SYNC_N  = 1'b0;

    assign VGA_CLK     = ~vga_clk;

    wire [10:0] h_next = (h_count == H_TOTAL - 1) ? 11'd0 : h_count + 1'b1;
    wire [9:0]  v_next = (h_count == H_TOTAL - 1)
                         ? ((v_count == V_TOTAL - 1) ? 10'd0 : v_count + 1'b1)
                         : v_count;

    wire fb_region = active;
    wire fb_region_next = (h_next < H_VISIBLE) && (v_next < V_VISIBLE);

    localparam int FB_X_NUM = cpu_pkg::VGA_FB_WIDTH;
    localparam int FB_X_DEN = H_VISIBLE;
    localparam int FB_Y_NUM = cpu_pkg::VGA_FB_HEIGHT;
    localparam int FB_Y_DEN = V_VISIBLE;

    localparam int X_ACC_W   = $clog2(FB_X_DEN + FB_X_NUM + 1);
    localparam int Y_ACC_W   = $clog2(FB_Y_DEN + FB_Y_NUM + 1);
    localparam int FB_ADDR_W = cpu_pkg::VGA_FB_ADDR_WIDTH;

    logic [X_ACC_W-1:0]   x_acc;
    logic [Y_ACC_W-1:0]   y_acc;
    logic [FB_ADDR_W-1:0] fb_x;
    logic [FB_ADDR_W-1:0] fb_row_base;

    wire line_end  = (h_count == H_TOTAL - 1);
    wire frame_end = line_end && (v_count == V_TOTAL - 1);

    wire [X_ACC_W-1:0] x_acc_sum = x_acc + X_ACC_W'(FB_X_NUM);
    wire               x_carry   = (x_acc_sum >= X_ACC_W'(FB_X_DEN));
    wire [Y_ACC_W-1:0] y_acc_sum = y_acc + Y_ACC_W'(FB_Y_NUM);
    wire               y_carry   = (y_acc_sum >= Y_ACC_W'(FB_Y_DEN));

    wire [X_ACC_W-1:0] x_acc_next =
        line_end ? '0 : (x_carry ? (x_acc_sum - X_ACC_W'(FB_X_DEN)) : x_acc_sum);
    wire [FB_ADDR_W-1:0] fb_x_next =
        line_end ? '0 : (x_carry ? (fb_x + FB_ADDR_W'(1)) : fb_x);

    wire [Y_ACC_W-1:0] y_acc_next =
        frame_end ? '0
                  : (line_end ? (y_carry ? (y_acc_sum - Y_ACC_W'(FB_Y_DEN)) : y_acc_sum)
                              : y_acc);
    wire [FB_ADDR_W-1:0] fb_row_base_next =
        frame_end ? '0
                  : ((line_end && y_carry) ? (fb_row_base + FB_ADDR_W'(FB_X_NUM))
                                           : fb_row_base);

    always_ff @(posedge vga_clk or negedge reset_n) begin
        if (!reset_n) begin
            x_acc       <= '0;
            y_acc       <= '0;
            fb_x        <= '0;
            fb_row_base <= '0;
        end else begin
            x_acc       <= x_acc_next;
            y_acc       <= y_acc_next;
            fb_x        <= fb_x_next;
            fb_row_base <= fb_row_base_next;
        end
    end

    assign fb_addr = fb_region_next ? (fb_row_base_next + fb_x_next) : '0;

    logic fb_region_d;
    always_ff @(posedge vga_clk or negedge reset_n) begin
        if (!reset_n)
            fb_region_d <= 1'b0;
        else
            fb_region_d <= fb_region;
    end

    wire [2:0] r3 = fb_data[7:5];
    wire [2:0] g3 = fb_data[4:2];
    wire [1:0] b2 = fb_data[1:0];

    always_ff @(posedge vga_clk or negedge reset_n) begin
        if (!reset_n) begin
            VGA_R <= 8'h00;
            VGA_G <= 8'h00;
            VGA_B <= 8'h00;
        end else if (fb_region_d) begin
            VGA_R <= {r3, r3, r3[2:1]};
            VGA_G <= {g3, g3, g3[2:1]};
            VGA_B <= {b2, b2, b2, b2};
        end else begin
            VGA_R <= 8'h00;
            VGA_G <= 8'h00;
            VGA_B <= 8'h00;
        end
    end

endmodule
