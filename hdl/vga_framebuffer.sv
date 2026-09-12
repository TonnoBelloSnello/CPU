module vga_framebuffer
    import cpu_pkg::*;
(
    input  logic        wr_clk,
    input  logic        wr_en,
    input  logic [VGA_FB_ADDR_WIDTH-1:0] wr_addr,
    input  logic [7:0]  wr_data,

    input  logic        rd_clk,
    input  logic [VGA_FB_ADDR_WIDTH-1:0] rd_addr,
    output logic [7:0]  rd_data
);

    (* ramstyle = "M10K" *)
    logic [7:0] fb_mem [0:VGA_FB_SIZE-1];

    initial begin
        for (int y = 0; y < VGA_FB_HEIGHT; y++) begin
            for (int x = 0; x < VGA_FB_WIDTH; x++) begin
                fb_mem[(y * VGA_FB_WIDTH) + x] = 8'h00;
            end
        end
    end

    always_ff @(posedge wr_clk) begin
        if (wr_en)
            fb_mem[wr_addr] <= wr_data;
    end

    always_ff @(posedge rd_clk) begin
        rd_data <= fb_mem[rd_addr];
    end

endmodule
