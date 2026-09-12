module BarrelShifter #(
    parameter DATA_WIDTH = 32
)(
    input  logic [DATA_WIDTH-1:0] value,
    input  logic [1:0]            shift_type,
    input  logic [4:0]            shift_amount,
    output logic [DATA_WIDTH-1:0] shifted
);

    always_comb begin
        int unsigned rotate_amount;
        rotate_amount = (DATA_WIDTH > 0) ? (shift_amount % DATA_WIDTH) : 0;
        case (shift_type)
            2'b00: shifted = value << shift_amount;
            2'b01: shifted = value >> shift_amount;
            2'b10: shifted = $signed(value) >>> shift_amount;
            default: begin
                if (rotate_amount == 0)
                    shifted = value;
                else
                    shifted = (value >> rotate_amount) | (value << (DATA_WIDTH - rotate_amount));
            end
        endcase
    end
endmodule
