`timescale 1ns/1ps

module CPU 
    import cpu_pkg::*;
#(
    parameter DATA_WIDTH = 8,
    parameter ADDR_WIDTH = cpu_pkg::RAM_ADDR_WIDTH,
    parameter USE_SLOW_CLOCK = cpu_pkg::USE_SLOW_CLOCK,
    parameter CLOCK_FREQ_HZ = cpu_pkg::CLOCK_FREQ_HZ,
    parameter SLOW_CLOCK_DIVISOR = cpu_pkg::SLOW_CLOCK_DIVISOR
)(
    input                     clock,
    input [3:0]               KEY,
    output [9:0]              LEDR,
    output [6:0]              HEX0,
    output [6:0]              HEX1,
    output [6:0]              HEX2,
    output [6:0]              HEX3,
    output [6:0]              HEX4,
    output [6:0]              HEX5,
    output [7:0]              VGA_R,
    output [7:0]              VGA_G,
    output [7:0]              VGA_B,
    output                    VGA_HS,
    output                    VGA_VS,
    output                    VGA_BLANK_N,
    output                    VGA_SYNC_N,
    output                    VGA_CLK
);
    

    logic [SLOW_CLOCK_DIVISOR-1:0] clock_counter = '0;
    logic slow_clock = 1'b0;
    wire cpu_clock;
    wire core_reset;

    localparam int CPU_CYCLES_PER_SEC = USE_SLOW_CLOCK
        ? (CLOCK_FREQ_HZ >> (SLOW_CLOCK_DIVISOR + 1))
        : CLOCK_FREQ_HZ;

    localparam int CPU_CYCLES_PER_MS = (CPU_CYCLES_PER_SEC >= 1000)
        ? (CPU_CYCLES_PER_SEC / 1000)
        : 1;

    generate
        if (USE_SLOW_CLOCK) begin : gen_slow_clock
            always_ff @(posedge clock) begin
                clock_counter <= clock_counter + 1'b1;
                if (clock_counter == '0) begin
                    slow_clock <= ~slow_clock;
                end
            end
            assign cpu_clock = slow_clock;
        end else begin : gen_fast_clock
            assign cpu_clock = clock;
        end
    endgenerate

    logic [3:0] key_meta = 4'hF;
    logic [3:0] key_sync = 4'hF;
    always_ff @(posedge cpu_clock) begin
        key_meta <= KEY;
        key_sync <= key_meta;
    end

`ifdef SIMULATION
    logic [3:0] jtag_key_raw = 4'h0;
`else
    wire [3:0] jtag_key_raw;
    altsource_probe #(
        .sld_auto_instance_index ("NO"),
        .sld_instance_index      (0),
        .instance_id             ("KEYS"),
        .source_width            (4),
        .probe_width             (0),
        .source_initial_value    ("0")
    ) u_jtag_keys (
        .source (jtag_key_raw)
    );
`endif

    logic [3:0] jtag_key_meta = 4'h0;
    logic [3:0] jtag_key_sync = 4'h0;
    always_ff @(posedge cpu_clock) begin
        jtag_key_meta <= jtag_key_raw;
        jtag_key_sync <= jtag_key_meta;
    end

    wire [DATA_WIDTH-1:0] data_in_ram;
    wire [ADDR_WIDTH-1:0] read_addr_ram;
    wire [ADDR_WIDTH-1:0] write_addr_ram;
    wire write_ram;
    wire [DATA_WIDTH-1:0] data_out_ram_raw;
    wire                  mmio_write_hit;
    wire                  mmio_read_sel;
    wire [DATA_WIDTH-1:0] mmio_read_data;
    wire                  mmio_led_write;
    wire                  mmio_hex_write;
    wire [DATA_WIDTH-1:0] mmio_display_byte;
    wire [1:0]            mmio_display_index;
    wire [DATA_WIDTH-1:0] data_out_ram = mmio_read_sel ? mmio_read_data : data_out_ram_raw;
    wire [DATA_WIDTH-1:0] data_in_ram_loader;
    wire [DATA_WIDTH-1:0] data_in_ram_exec;
    wire [ADDR_WIDTH-1:0] write_addr_ram_loader;
    wire [ADDR_WIDTH-1:0] write_addr_ram_exec;
    wire write_ram_loader;
    wire write_ram_exec;
    wire [ADDR_WIDTH-1:0] fetched_addr;
    wire [31:0] instr_data;

    wire [ADDR_WIDTH-1:0] data_in_registers_exec [REG_COUNT-1:0];
    wire [ADDR_WIDTH-1:0] data_out_registers [REG_COUNT-1:0];

    wire [ADDR_WIDTH-1:0] fetcher_pc;
    wire [ADDR_WIDTH-1:0] executer_pc;
    wire [ADDR_WIDTH-1:0] data_in_pc;
    wire [ADDR_WIDTH-1:0] data_out_pc;

    wire [31:0] data_in_cpsr;  // N, Z, C, V in [31:28]
    wire [31:0] data_out_cpsr;

    genvar i;
    generate
        for (i = 0; i < REG_COUNT; i = i + 1) begin : register_gen
            Register #(
                .size(ADDR_WIDTH)
            ) reg_inst (
                .clock(cpu_clock),
                .data_in(data_in_registers_exec[i]),
                .data_out(data_out_registers[i]),
                .reset(core_reset)
            );
        end
    endgenerate

    Register #(
        .size(ADDR_WIDTH)
    ) PC (
        .clock(cpu_clock),
        .data_in(data_in_pc),
        .data_out(data_out_pc),
        .reset(core_reset)
    );
    
    Register #(
        .size(32)
    ) CPSR (
        .clock(cpu_clock),
        .data_in(data_in_cpsr),
        .data_out(data_out_cpsr),
        .reset(core_reset)
    );

    RAM #(
		.DATA_WIDTH(DATA_WIDTH),
		.ADDR_WIDTH(ADDR_WIDTH)
	) storage (
		.data            (data_in_ram),
		.read_addr       (read_addr_ram),
		.write_addr      (write_addr_ram),
		.write           (write_ram),
		.clock           (cpu_clock),
		.q               (data_out_ram_raw),
		.instr_read_addr (fetched_addr),
		.instr_load_write(write_ram_loader),
		.instr_load_addr (write_addr_ram_loader),
		.instr_load_data (data_in_ram_loader),
		.instr_q         (instr_data)
	);

    wire loader_done;
    
    Loader #(
        .DATA_WIDTH(DATA_WIDTH),
        .ADDR_WIDTH(ADDR_WIDTH)
    ) loader (
        .clock(cpu_clock),
        .reset(core_reset),
        .write_ram(write_ram_loader),
        .data_in_ram(data_in_ram_loader),
        .write_addr_ram(write_addr_ram_loader),
        .loader_done(loader_done)
    );
	 
    assign write_ram = loader_done ? (write_ram_exec && !mmio_write_hit)
                                   : write_ram_loader;
    assign data_in_ram = loader_done ? data_in_ram_exec : data_in_ram_loader;
    assign write_addr_ram = loader_done ? write_addr_ram_exec : write_addr_ram_loader;

    wire fetch_instr;
    wire decode_instr;
    wire exec_instr;

    wire exec_done;
    wire halted; 
    wire exec_pc_write_en;

    cond_t        ex_condition;
    instr_class_t ex_instr_class;
    wire ex_immediate;
    wire ex_flag;
    wire [3:0] ex_opcode;
    wire [3:0] ex_rn;
    wire [3:0] ex_rd;
    wire [11:0] ex_second_operand;
    wire branch_redirect_en;
    wire [cpu_pkg::BR_TARGET_WIDTH-1:0] branch_redirect_operand;
    localparam int BR_EXT_WIDTH = (ADDR_WIDTH > cpu_pkg::BR_TARGET_WIDTH)
        ? ADDR_WIDTH : cpu_pkg::BR_TARGET_WIDTH;
    wire [BR_EXT_WIDTH-1:0] branch_redirect_wide = BR_EXT_WIDTH'(branch_redirect_operand);
    wire [ADDR_WIDTH-1:0] branch_redirect_addr = branch_redirect_wide[ADDR_WIDTH-1:0];

    wire [ADDR_WIDTH-1:0] exec_read_addr;
    wire [ADDR_WIDTH-1:0] data_prefetch_addr;
    wire data_prefetch_valid;

    assign read_addr_ram = data_prefetch_valid ? data_prefetch_addr : exec_read_addr;

    Fetcher #(
        .DATA_WIDTH(DATA_WIDTH),
        .ADDR_WIDTH(ADDR_WIDTH)
    ) fetcher (
        .clock(cpu_clock),
        .fetch_instr(fetch_instr),
        .redirect_en(branch_redirect_en),
        .redirect_addr(branch_redirect_addr),
        .data_out_pc(data_out_pc),
        .data_in_pc(fetcher_pc),
        .fetched_addr(fetched_addr)
	 );
    
    cond_t        condition;
    instr_class_t instr_class;
    wire immediate;
    wire flag;
    wire [3:0] opcode;
    wire [3:0] rn;
    wire [3:0] rd;
    wire [11:0] second_operand;
    
    Decoder #(
        .DATA_WIDTH(DATA_WIDTH),
        .ADDR_WIDTH(ADDR_WIDTH)
    ) decoder (
        .decode_instr(decode_instr),
        .fetched_addr(fetched_addr),
        .instr_data(instr_data),

        .condition(condition),
        .instr_class(instr_class),
        .immediate(immediate),
        .flag(flag),
        .opcode(opcode),
        .rn(rn),
        .rd(rd),
        .second_operand(second_operand)
    );

    ProcessController process_controller (
        .clock(cpu_clock),
        .reset(core_reset),
        .loader_done(loader_done),
        .halted(halted),
        .exec_done(exec_done),
        .exec_pc_write_en(exec_pc_write_en),
        .cpsr(data_in_cpsr),
        .condition(condition),
        .instr_class(instr_class),
        .immediate(immediate),
        .flag(flag),
        .opcode(opcode),
        .rn(rn),
        .rd(rd),
        .second_operand(second_operand),
        .fetch_instr(fetch_instr),
        .decode_instr(decode_instr),
        .exec_instr(exec_instr),
        .branch_redirect_en(branch_redirect_en),
        .branch_redirect_operand(branch_redirect_operand),
        .ex_condition(ex_condition),
        .ex_instr_class(ex_instr_class),
        .ex_immediate(ex_immediate),
        .ex_flag(ex_flag),
        .ex_opcode(ex_opcode),
        .ex_rn(ex_rn),
        .ex_rd(ex_rd),
        .ex_second_operand(ex_second_operand)
    );

    wire [ADDR_WIDTH-1:0] data_in_ledr_exec;
    wire [ADDR_WIDTH-1:0] data_out_ledr;
    assign data_out_ledr = data_in_ledr_exec;

    wire [ADDR_WIDTH-1:0] data_in_hex_exec;
    wire [ADDR_WIDTH-1:0] data_out_hex;
    assign data_out_hex = data_in_hex_exec;

    wire        vga_fb_write;
    wire [cpu_pkg::VGA_FB_ADDR_WIDTH-1:0] vga_fb_addr;
    wire [7:0]  vga_fb_data;

    wire [cpu_pkg::VGA_FB_ADDR_WIDTH-1:0] vga_fb_rd_addr;
    wire [7:0]  vga_fb_rd_data;

    MMIO #(
        .DATA_WIDTH(DATA_WIDTH),
        .ADDR_WIDTH(ADDR_WIDTH)
    ) mmio (
        .clock              (cpu_clock),
        .reset              (core_reset),
        .read_addr          (read_addr_ram),
        .write_addr         (write_addr_ram_exec),
        .write_data         (data_in_ram_exec),
        .write_en           (write_ram_exec && loader_done),
        .write_hit          (mmio_write_hit),
        .read_sel           (mmio_read_sel),
        .read_data          (mmio_read_data),
        .key_n              (key_sync),
        .key_jtag           (jtag_key_sync),
        .led_value          (data_out_ledr),
        .hex_value          (data_out_hex),
        .led_write          (mmio_led_write),
        .hex_write          (mmio_hex_write),
        .display_write_byte (mmio_display_byte),
        .display_write_index(mmio_display_index)
    );

    Executer #(
        .DATA_WIDTH(DATA_WIDTH),
        .ADDR_WIDTH(ADDR_WIDTH),
        .CYCLES_PER_MS(CPU_CYCLES_PER_MS)
    ) executer (
        .clock(cpu_clock),
        .reset(core_reset),
        .execute_instr(exec_instr),
        .condition(ex_condition),
        .instr_class(ex_instr_class),
        .immediate(ex_immediate),
        .flag(ex_flag),
        .opcode(ex_opcode),
        .rn(ex_rn),
        .rd(ex_rd),
        .second_operand(ex_second_operand),
        .key_n(key_sync),
        .key_jtag(jtag_key_sync),
        .mmio_led_write(mmio_led_write),
        .mmio_hex_write(mmio_hex_write),
        .mmio_display_byte(mmio_display_byte),
        .mmio_display_index(mmio_display_index),
        .data_in_registers(data_in_registers_exec),
        .data_out_registers(data_out_registers),
        .data_out_pc(data_out_pc),
        .data_in_pc(executer_pc),
        .data_out_cpsr(data_out_cpsr),
        .data_in_cpsr(data_in_cpsr),
        .pc_write_en(exec_pc_write_en),
        .data_out_ledr(data_out_ledr),
        .data_in_ledr(data_in_ledr_exec),
        .data_out_hex(data_out_hex),
        .data_in_hex(data_in_hex_exec),
        .execute_done(exec_done),
        .halted(halted),
        .ram_read_addr(exec_read_addr),
        .data_prefetch_valid(data_prefetch_valid),
        .data_prefetch_addr(data_prefetch_addr),
        .ram_data_out(data_out_ram),
        .ram_write_en(write_ram_exec),
        .ram_write_addr(write_addr_ram_exec),
        .ram_write_data(data_in_ram_exec),
        .vga_fb_write(vga_fb_write),
        .vga_fb_addr(vga_fb_addr),
        .vga_fb_data(vga_fb_data)
    );
    
    assign data_in_pc = exec_pc_write_en ? executer_pc :
                        fetch_instr ? fetcher_pc : data_out_pc;
    
	 
    assign LEDR[9:0] = data_out_ledr[9:0];

    function automatic [6:0] nibble_to_7seg(input logic [3:0] nibble);
        case (nibble)
            4'h0: return 7'b1000000;
            4'h1: return 7'b1111001;
            4'h2: return 7'b0100100;
            4'h3: return 7'b0110000;
            4'h4: return 7'b0011001;
            4'h5: return 7'b0010010;
            4'h6: return 7'b0000010;
            4'h7: return 7'b1111000;
            4'h8: return 7'b0000000;
            4'h9: return 7'b0010000;
            4'hA: return 7'b0001000;
            4'hB: return 7'b0000011;
            4'hC: return 7'b1000110;
            4'hD: return 7'b0100001;
            4'hE: return 7'b0000110;
            4'hF: return 7'b0001110;
            default: return 7'b1111111;
        endcase
    endfunction


    localparam int NUM_NIBBLES = (ADDR_WIDTH + 3) / 4;
    wire [23:0] hex_padded = {{(24-ADDR_WIDTH){1'b0}}, data_out_hex};
    wire [6:0] hex_segs [5:0];
    genvar h;
    generate
        for (h = 0; h < 6; h = h + 1) begin : hex_decode
            if (h < NUM_NIBBLES)
                assign hex_segs[h] = nibble_to_7seg(hex_padded[h*4 +: 4]);
            else
                assign hex_segs[h] = 7'b1111111;
        end
    endgenerate

    assign HEX0 = hex_segs[0];
    assign HEX1 = hex_segs[1];
    assign HEX2 = hex_segs[2];
    assign HEX3 = hex_segs[3];
    assign HEX4 = hex_segs[4];
    assign HEX5 = hex_segs[5];

    wire vga_clk;
    wire vga_fb_rd_clk;
    wire pll_locked;

    logic [1:0] reset_sync = 2'b11;
    always_ff @(posedge cpu_clock or negedge pll_locked) begin
        if (!pll_locked)
            reset_sync <= 2'b11;
        else
            reset_sync <= {reset_sync[0], 1'b0};
    end
    assign core_reset = reset_sync[1];

    `ifdef SIMULATION
        assign vga_clk   = clock;
        assign pll_locked = 1'b1;
    `else
        vga_pll pll_inst (
            .inclk0 (clock),
            .c0     (vga_clk),
            .locked (pll_locked)
        );
    `endif

    `ifdef WEB_FAST_SIMULATION
        assign vga_fb_rd_clk = 1'b0;
    `else
        assign vga_fb_rd_clk = vga_clk;
    `endif

    vga_framebuffer fb_inst (
        .wr_clk  (cpu_clock),
        .wr_en   (vga_fb_write),
        .wr_addr (vga_fb_addr),
        .wr_data (vga_fb_data),
        .rd_clk  (vga_fb_rd_clk),
        .rd_addr (vga_fb_rd_addr),
        .rd_data (vga_fb_rd_data)
    );

    `ifdef WEB_FAST_SIMULATION
        assign vga_fb_rd_addr = '0;
        assign VGA_R          = 8'h00;
        assign VGA_G          = 8'h00;
        assign VGA_B          = 8'h00;
        assign VGA_HS         = 1'b1;
        assign VGA_VS         = 1'b1;
        assign VGA_BLANK_N    = 1'b0;
        assign VGA_SYNC_N     = 1'b0;
        assign VGA_CLK        = 1'b0;
    `else
        vga_controller vga_inst (
            .vga_clk    (vga_clk),
            .reset_n    (pll_locked),
            .VGA_R      (VGA_R),
            .VGA_G      (VGA_G),
            .VGA_B      (VGA_B),
            .VGA_HS     (VGA_HS),
            .VGA_VS     (VGA_VS),
            .VGA_BLANK_N(VGA_BLANK_N),
            .VGA_SYNC_N (VGA_SYNC_N),
            .VGA_CLK    (VGA_CLK),
            .fb_addr    (vga_fb_rd_addr),
            .fb_data    (vga_fb_rd_data)
        );
    `endif

endmodule

module CPU_tb;
    reg clock = 1'b0;
    reg [3:0] key_n = 4'hF;
    wire [9:0] LEDR;
    wire [6:0] HEX0, HEX1, HEX2, HEX3, HEX4, HEX5;
    localparam real clock_period = 0.2;
    
    CPU #(
        .USE_SLOW_CLOCK(0),
        .CLOCK_FREQ_HZ(1)
    ) CPU (
        .clock(clock),
        .KEY(key_n),
        .LEDR(LEDR),
        .HEX0(HEX0),
        .HEX1(HEX1),
        .HEX2(HEX2),
        .HEX3(HEX3),
        .HEX4(HEX4),
        .HEX5(HEX5)
    );

    initial begin
        $dumpfile("cpu.vcd");
        $dumpvars(0, CPU);
    end

    initial begin
        clock = 1'b0;
        forever #(clock_period/2) clock = ~clock;
    end
    
    initial begin
        #1000000;
        $display("\nERROR: Simulation timeout - CPU did not halt");
        $finish;
    end

endmodule
