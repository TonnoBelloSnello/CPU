module text_glyph_rom (
    input  logic [7:0] ascii_char,
    input  logic [2:0] row,
    output logic [4:0] row_bits
);
    localparam int GLYPH_HEIGHT = 7;
    localparam int GLYPH_WIDTH = 5;
    localparam logic [7:0] FALLBACK_CHAR = 8'd63;

    logic [7:0] normalized_char;
    logic [34:0] glyph;
    integer bit_base;

    always_comb begin
        normalized_char = (ascii_char >= 8'd32 && ascii_char <= 8'd126)
            ? ascii_char : FALLBACK_CHAR;

        case (normalized_char)
            8'd32: glyph = 35'h000000000;
            8'd33: glyph = 35'h108420080;
            8'd34: glyph = 35'h294000000;
            8'd35: glyph = 35'h00BF57E80;
            8'd36: glyph = 35'h11CC219C4;
            8'd37: glyph = 35'h26AE75640;
            8'd38: glyph = 35'h114CAC9A0;
            8'd39: glyph = 35'h108000000;
            8'd40: glyph = 35'h0C8842083;
            8'd41: glyph = 35'h608210898;
            8'd42: glyph = 35'h114450000;
            8'd43: glyph = 35'h000023880;
            8'd44: glyph = 35'h000000084;
            8'd45: glyph = 35'h000070000;
            8'd46: glyph = 35'h000000080;
            8'd47: glyph = 35'h044221108;
            8'd48: glyph = 35'h19294A4C0;
            8'd49: glyph = 35'h1184211C0;
            8'd50: glyph = 35'h3042221C0;
            8'd51: glyph = 35'h304C10980;
            8'd52: glyph = 35'h08CA78840;
            8'd53: glyph = 35'h390C10980;
            8'd54: glyph = 35'h190E4A4C0;
            8'd55: glyph = 35'h3C2221080;
            8'd56: glyph = 35'h19264A4C0;
            8'd57: glyph = 35'h1929384C0;
            8'd58: glyph = 35'h000400080;
            8'd59: glyph = 35'h000400084;
            8'd60: glyph = 35'h002260820;
            8'd61: glyph = 35'h000F03C00;
            8'd62: glyph = 35'h010419100;
            8'd63: glyph = 35'h382220080;
            8'd64: glyph = 35'h1933ADE0F;
            8'd65: glyph = 35'h008A57E20;
            8'd66: glyph = 35'h01CA629C0;
            8'd67: glyph = 35'h00E8420E0;
            8'd68: glyph = 35'h01C94A5C0;
            8'd69: glyph = 35'h01C8721C0;
            8'd70: glyph = 35'h01C872100;
            8'd71: glyph = 35'h00E85A4E0;
            8'd72: glyph = 35'h01297A520;
            8'd73: glyph = 35'h01C4211C0;
            8'd74: glyph = 35'h01C210980;
            8'd75: glyph = 35'h012A62920;
            8'd76: glyph = 35'h0108421E0;
            8'd77: glyph = 35'h023BAD620;
            8'd78: glyph = 35'h012D5A520;
            8'd79: glyph = 35'h01D18C5C0;
            8'd80: glyph = 35'h01C972100;
            8'd81: glyph = 35'h01D18C5C2;
            8'd82: glyph = 35'h018A62920;
            8'd83: glyph = 35'h00C820980;
            8'd84: glyph = 35'h03E421080;
            8'd85: glyph = 35'h01294A4C0;
            8'd86: glyph = 35'h0129498C0;
            8'd87: glyph = 35'h0235AA940;
            8'd88: glyph = 35'h022A22A20;
            8'd89: glyph = 35'h022A21080;
            8'd90: glyph = 35'h01E1321E0;
            8'd91: glyph = 35'h188421086;
            8'd92: glyph = 35'h410821042;
            8'd93: glyph = 35'h30842108C;
            8'd94: glyph = 35'h114A8C400;
            8'd95: glyph = 35'h00000001F;
            8'd96: glyph = 35'h208000000;
            8'd97: glyph = 35'h000C139E0;
            8'd98: glyph = 35'h210E4A5C0;
            8'd99: glyph = 35'h0006420C0;
            8'd100: glyph = 35'h084E949C0;
            8'd101: glyph = 35'h0004720C0;
            8'd102: glyph = 35'h0C8F21080;
            8'd103: glyph = 35'h00074BC2E;
            8'd104: glyph = 35'h210A6A520;
            8'd105: glyph = 35'h100C21080;
            8'd106: glyph = 35'h080E1084C;
            8'd107: glyph = 35'h210A62920;
            8'd108: glyph = 35'h308421080;
            8'd109: glyph = 35'h0015FD6A0;
            8'd110: glyph = 35'h000A6A520;
            8'd111: glyph = 35'h00064A4C0;
            8'd112: glyph = 35'h000E4A5C8;
            8'd113: glyph = 35'h000E949C2;
            8'd114: glyph = 35'h000A62100;
            8'd115: glyph = 35'h000660980;
            8'd116: glyph = 35'h008F21040;
            8'd117: glyph = 35'h00094ACA0;
            8'd118: glyph = 35'h0009498C0;
            8'd119: glyph = 35'h0015AB940;
            8'd120: glyph = 35'h000931920;
            8'd121: glyph = 35'h0009498DC;
            8'd122: glyph = 35'h000E321C0;
            8'd123: glyph = 35'h088441082;
            8'd124: glyph = 35'h108421084;
            8'd125: glyph = 35'h208411088;
            8'd126: glyph = 35'h00006C800;
            default: glyph = 35'h382220080;
        endcase
        bit_base = (GLYPH_HEIGHT - 1 - row) * GLYPH_WIDTH;
        row_bits = glyph[bit_base +: GLYPH_WIDTH];
    end
endmodule
