module Loader
    import cpu_pkg::*;
#(
    parameter DATA_WIDTH = 8,
    parameter ADDR_WIDTH = 24,
    parameter MAX_PROGRAM_SIZE = cpu_pkg::LOADER_MAX_PROGRAM_SIZE
)(
    input  logic clock,
    input  logic reset,

    output logic        write_ram = 1'b0,
    output logic [(DATA_WIDTH-1):0]  data_in_ram = '0,
    output logic [ADDR_WIDTH-1:0] write_addr_ram = '0,
    output logic        loader_done = 1'b0
);
    logic [(DATA_WIDTH-1):0] program_mem [0:MAX_PROGRAM_SIZE-1];

`ifdef SIMULATION
    `include "program_size.svh"
`else
    `include "../program_size.svh"
`endif

    localparam int PROGRAM_SIZE = PROGRAM_IMAGE_SIZE + 4;

    initial begin
        if (!USE_INIT_FILE) begin
            if (PROGRAM_SIZE > MAX_PROGRAM_SIZE)
                $fatal(1,
                    "Runtime program is %0d bytes including its halt word; loader capacity is %0d",
                    PROGRAM_SIZE, MAX_PROGRAM_SIZE);
            if (PROGRAM_SIZE > (2**ADDR_WIDTH))
                $fatal(1,
                    "Runtime program is %0d bytes; address space is %0d",
                    PROGRAM_SIZE, 2**ADDR_WIDTH);

            if (PROGRAM_SIZE <= MAX_PROGRAM_SIZE && PROGRAM_SIZE <= (2**ADDR_WIDTH)) begin
                for (int i = 0; i < MAX_PROGRAM_SIZE; i++) begin
                    program_mem[i] = '0;
                end

`ifdef SIMULATION
                if (PROGRAM_IMAGE_SIZE > 0)
                    $readmemh("file.hex", program_mem, 0, PROGRAM_IMAGE_SIZE - 1);
`else
                if (PROGRAM_IMAGE_SIZE > 0)
                    $readmemh("../file.hex", program_mem, 0, PROGRAM_IMAGE_SIZE - 1);
`endif
            end
        end
    end

    typedef enum logic [1:0] {IDLE, LOAD, DONE} state_t;
    state_t st = IDLE;

    logic [ADDR_WIDTH:0] load_addr = '0;

    always_ff @(posedge clock or posedge reset) begin
        if (reset) begin
            st             <= IDLE;
            load_addr      <= '0;
            write_ram      <= 1'b0;
            data_in_ram    <= '0;
            write_addr_ram <= '0;
            loader_done    <= 1'b0;
        end else begin
            case (st)
                IDLE: begin
                    if (USE_INIT_FILE) begin
                        loader_done <= 1'b1;
                        st          <= DONE;
                    end else begin
                        st <= LOAD;
                    end
                end

                LOAD: begin
                    if (load_addr < PROGRAM_SIZE) begin
                        write_ram      <= 1'b1;
                        data_in_ram    <= program_mem[load_addr];
                        write_addr_ram <= load_addr[ADDR_WIDTH-1:0];
                        load_addr      <= load_addr + 1'b1;
                    end else begin
                        write_ram     <= 1'b0;
                        loader_done   <= 1'b1;
                        st            <= DONE;
                    end
                end

                DONE: begin
                    write_ram <= 1'b0;
                end
            endcase
        end
    end

endmodule
