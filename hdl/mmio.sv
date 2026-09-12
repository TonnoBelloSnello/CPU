module MMIO
    import cpu_pkg::*;
#(
    parameter DATA_WIDTH = 8,
    parameter ADDR_WIDTH = cpu_pkg::RAM_ADDR_WIDTH
)(
    input  logic                  clock,
    input  logic                  reset,

    input  logic [ADDR_WIDTH-1:0] read_addr,
    input  logic [ADDR_WIDTH-1:0] write_addr,
    input  logic [DATA_WIDTH-1:0] write_data,
    input  logic                  write_en,

    output logic                  write_hit,
    output logic                  read_sel = 1'b0,
    output logic [DATA_WIDTH-1:0] read_data = '0,

    input  logic [3:0]            key_n,  // synchronized, active low
    input  logic [3:0]            key_jtag,

    input  logic [ADDR_WIDTH-1:0] led_value,
    input  logic [ADDR_WIDTH-1:0] hex_value,
    output logic                  led_write,
    output logic                  hex_write,
    output logic [DATA_WIDTH-1:0] display_write_byte,
    output logic [1:0]            display_write_index
);

    localparam int REG_BYTES = (ADDR_WIDTH + DATA_WIDTH - 1) / DATA_WIDTH;
    localparam int SLOT_BITS = MMIO_ADDR_BITS - 2;

    function automatic logic in_window(input logic [ADDR_WIDTH-1:0] addr);
        return &addr[ADDR_WIDTH-1:MMIO_ADDR_BITS];
    endfunction

    wire [SLOT_BITS-1:0] read_slot  = read_addr[MMIO_ADDR_BITS-1:2];
    wire [1:0]           read_byte  = read_addr[1:0];
    wire [SLOT_BITS-1:0] write_slot = write_addr[MMIO_ADDR_BITS-1:2];

    logic [(2*ADDR_WIDTH)-1:0] cycle_counter = '0;

    wire [3:0]            keys_pressed = ~key_n | key_jtag;
    wire [ADDR_WIDTH-1:0] keys_value   = {{(ADDR_WIDTH-4){1'b0}}, keys_pressed};

    function automatic logic [DATA_WIDTH-1:0] select_byte(
        input logic [ADDR_WIDTH-1:0] value,
        input logic [1:0]            index
    );
        select_byte = '0;
        for (int b = 0; b < REG_BYTES; b++)
            if (index == 2'(b))
                select_byte = value[b*DATA_WIDTH +: DATA_WIDTH];
    endfunction

    logic [ADDR_WIDTH-1:0] read_register;
    always_comb begin
        case (read_slot)
            SLOT_BITS'(MMIO_OFF_LED       >> 2): read_register = led_value;
            SLOT_BITS'(MMIO_OFF_HEX       >> 2): read_register = hex_value;
            SLOT_BITS'(MMIO_OFF_KEYS      >> 2): read_register = keys_value;
            SLOT_BITS'(MMIO_OFF_CYCLES_LO >> 2): read_register = cycle_counter[ADDR_WIDTH-1:0];
            SLOT_BITS'(MMIO_OFF_CYCLES_HI >> 2): read_register = cycle_counter[(2*ADDR_WIDTH)-1:ADDR_WIDTH];
            default: read_register = '0;
        endcase
    end

    assign write_hit = write_en && in_window(write_addr);

    always_comb begin
        led_write = 1'b0;
        hex_write = 1'b0;
        if (write_hit) begin
            case (write_slot)
                SLOT_BITS'(MMIO_OFF_LED >> 2): led_write = 1'b1;
                SLOT_BITS'(MMIO_OFF_HEX >> 2): hex_write = 1'b1;
                default: ;
            endcase
        end
    end

    assign display_write_byte  = write_data;
    assign display_write_index = write_addr[1:0];

    always_ff @(posedge clock) begin
        if (reset) begin
            read_sel      <= 1'b0;
            read_data     <= '0;
            cycle_counter <= '0;
        end else begin
            cycle_counter <= cycle_counter + 1'b1;
            read_sel      <= in_window(read_addr);
            read_data     <= select_byte(read_register, read_byte);
        end
    end

endmodule
