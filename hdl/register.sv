module Register #(
    parameter size = 24
)(
    input  wire         clock,
    input  wire         reset, 
    input  wire [size-1:0] data_in,
    output logic  [size-1:0] data_out = '0
);

always_ff @(posedge clock or posedge reset) begin
    if (reset) begin
        data_out <= '0;
    end else begin
        data_out <= data_in;
    end
end

endmodule
