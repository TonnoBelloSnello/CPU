module RAM
    import cpu_pkg::*;
#(
    parameter DATA_WIDTH = 8,
    parameter ADDR_WIDTH = 24
)(
    input  wire [(DATA_WIDTH-1):0] data,
    input  wire [(ADDR_WIDTH-1):0] read_addr,
    input  wire [(ADDR_WIDTH-1):0] write_addr,
    input  wire               write,
    input  wire               clock,
    output wire [(DATA_WIDTH-1):0] q,
    input  wire [(ADDR_WIDTH-1):0] instr_read_addr,
    input  wire                       instr_load_write,
    input  wire [(ADDR_WIDTH-1):0]    instr_load_addr,
    input  wire [(DATA_WIDTH-1):0]    instr_load_data,
    output wire [31:0]             instr_q
);

    (* ram_init_file = "../data.mif" *) logic [(DATA_WIDTH-1):0] ram [(2**ADDR_WIDTH-1):0];

`ifdef SIMULATION
    initial begin
        if (!USE_INIT_FILE) begin
            for (int i = 0; i < 2**ADDR_WIDTH; i++)
                ram[i] = '0;
        end
    end
`endif

    logic [(DATA_WIDTH-1):0] q_sync = '0;

    always_ff @(posedge clock) begin
        if (write)
            ram[write_addr] <= data;
        q_sync <= ram[read_addr];
    end

    assign q = q_sync;
    
    generate
        if (USE_INIT_FILE) begin : gen_instr_fpga
            (* ram_init_file = "../file.mif" *) logic [31:0] instr_rom [0:2**(ADDR_WIDTH-2)-1];
            logic [31:0] instr_q_r = '0;
            always_ff @(posedge clock)
                instr_q_r <= instr_rom[instr_read_addr[ADDR_WIDTH-1:2]];
            assign instr_q = instr_q_r;
        end else begin : gen_instr_sim
            (* ram_init_file = "../file.mif" *) logic [31:0] instr_rom [0:2**(ADDR_WIDTH-2)-1];
            logic [31:0] instr_q_r = '0;

`ifdef SIMULATION
            initial begin
                for (int i = 0; i < 2**(ADDR_WIDTH-2); i++)
                    instr_rom[i] = '0;
            end
`endif

            always_ff @(posedge clock) begin
                if (instr_load_write) begin
                    case (instr_load_addr[1:0])
                        2'd0: instr_rom[instr_load_addr[ADDR_WIDTH-1:2]][7:0]
                            <= instr_load_data;
                        2'd1: instr_rom[instr_load_addr[ADDR_WIDTH-1:2]][15:8]
                            <= instr_load_data;
                        2'd2: instr_rom[instr_load_addr[ADDR_WIDTH-1:2]][23:16]
                            <= instr_load_data;
                        2'd3: instr_rom[instr_load_addr[ADDR_WIDTH-1:2]][31:24]
                            <= instr_load_data;
                    endcase
                end
                instr_q_r <= instr_rom[instr_read_addr[ADDR_WIDTH-1:2]];
            end
            assign instr_q = instr_q_r;
        end
    endgenerate

endmodule
