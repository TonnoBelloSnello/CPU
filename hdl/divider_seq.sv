module divider_seq #(
    parameter int NUM_WIDTH = 32,
    parameter int DEN_WIDTH = 16,
    parameter int RADIX_BITS = 2,
    parameter int SKIP_GRANULARITY = 4
)(
    input  logic                   clock,
    input  logic                   reset,

    input  logic                   start,
    input  logic [NUM_WIDTH-1:0]   numerator,
    input  logic [DEN_WIDTH-1:0]   denominator,

    output logic [NUM_WIDTH-1:0]   quotient    = '0,
    output logic                   rem_nonzero = 1'b0,
    output logic                   busy        = 1'b0,
    output logic                   done        = 1'b0
);

    localparam int DIGIT_MAX   = (1 << RADIX_BITS) - 1;
    localparam int STEP_WIDTH  = DEN_WIDTH + RADIX_BITS;
    localparam int MAX_STEPS   = NUM_WIDTH / RADIX_BITS;
    localparam int COUNT_WIDTH = $clog2(MAX_STEPS + 1);

    localparam int SKIP_STEPS  = (SKIP_GRANULARITY == 0)
                               ? 0
                               : (NUM_WIDTH / SKIP_GRANULARITY) - 1;

    logic [NUM_WIDTH-1:0]   quo_shift = '0;
    logic [DEN_WIDTH-1:0]   rem       = '0;
    logic [STEP_WIDTH-1:0]  den_mult [1:DIGIT_MAX];
    logic [COUNT_WIDTH-1:0] count     = '0;

    integer m;

    wire [STEP_WIDTH-1:0] rem_shifted = {rem, quo_shift[NUM_WIDTH-1 -: RADIX_BITS]};

    logic [RADIX_BITS-1:0] digit;
    logic [STEP_WIDTH-1:0] sub_value;

    always_comb begin
        digit     = '0;
        sub_value = '0;
        for (m = 1; m <= DIGIT_MAX; m = m + 1) begin
            if (rem_shifted >= den_mult[m]) begin
                digit     = RADIX_BITS'(m);
                sub_value = den_mult[m];
            end
        end
    end

    wire [STEP_WIDTH-1:0] rem_full = rem_shifted - sub_value;
    wire [DEN_WIDTH-1:0]  rem_step = rem_full[DEN_WIDTH-1:0];
    wire [NUM_WIDTH-1:0]  quo_step = {quo_shift[NUM_WIDTH-RADIX_BITS-1:0], digit};

    logic [NUM_WIDTH-1:0]   start_shift;
    logic [COUNT_WIDTH-1:0] start_count;

    integer k;

    always_comb begin
        start_shift = numerator;
        start_count = COUNT_WIDTH'(MAX_STEPS);
        for (k = 1; k <= SKIP_STEPS; k = k + 1) begin
            if ((numerator >> (NUM_WIDTH - (k * SKIP_GRANULARITY))) == '0) begin
                start_shift = numerator << (k * SKIP_GRANULARITY);
                start_count = COUNT_WIDTH'(MAX_STEPS -
                                           ((k * SKIP_GRANULARITY) / RADIX_BITS));
            end
        end
    end

    initial begin
        for (m = 1; m <= DIGIT_MAX; m = m + 1)
            den_mult[m] = '0;
    end

    always_ff @(posedge clock) begin
        if (reset) begin
            quotient    <= '0;
            rem_nonzero <= 1'b0;
            busy        <= 1'b0;
            done        <= 1'b0;
            quo_shift   <= '0;
            rem         <= '0;
            count       <= '0;
            for (m = 1; m <= DIGIT_MAX; m = m + 1)
                den_mult[m] <= '0;
        end else begin
            done <= 1'b0;

            if (start && !busy) begin
                quo_shift <= start_shift;
                rem       <= '0;
                count     <= start_count;
                busy      <= 1'b1;
                for (m = 1; m <= DIGIT_MAX; m = m + 1)
                    den_mult[m] <= STEP_WIDTH'(denominator) * STEP_WIDTH'(m);
            end else if (busy) begin
                rem       <= rem_step;
                quo_shift <= quo_step;

                if (count == COUNT_WIDTH'(1)) begin
                    busy        <= 1'b0;
                    done        <= 1'b1;
                    quotient    <= quo_step;
                    rem_nonzero <= (rem_step != '0);
                end else begin
                    count <= count - COUNT_WIDTH'(1);
                end
            end
        end
    end

endmodule
