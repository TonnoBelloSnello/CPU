module vga_pll (
    input  wire inclk0,  // 50 MHz board clock
    output wire c0,  // 65 MHz pixel clock
    output wire c1,  // 40.625 MHz CPU core clock
    output wire locked
);

    wire [4:0] sub_wire0;
    wire       sub_wire2;

    assign c0     = sub_wire0[0];
    assign c1     = sub_wire0[1];
    assign locked = sub_wire2;

    altpll #(
        .bandwidth_type          ("AUTO"),
        .clk0_divide_by          (10),
        .clk0_duty_cycle         (50),
        .clk0_multiply_by        (13),
        .clk0_phase_shift        ("0"),
        .clk1_divide_by          (16),
        .clk1_duty_cycle         (50),
        .clk1_multiply_by        (13),
        .clk1_phase_shift        ("0"),
        .compensate_clock        ("CLK0"),
        .inclk0_input_frequency  (20000),
        .intended_device_family  ("Cyclone V"),
        .lpm_hint                ("CBX_MODULE_PREFIX=vga_pll"),
        .lpm_type                ("altpll"),
        .operation_mode          ("NORMAL"),
        .pll_type                ("AUTO"),
        .port_activeclock        ("PORT_UNUSED"),
        .port_areset             ("PORT_UNUSED"),
        .port_clkbad0            ("PORT_UNUSED"),
        .port_clkbad1            ("PORT_UNUSED"),
        .port_clkloss            ("PORT_UNUSED"),
        .port_clkswitch          ("PORT_UNUSED"),
        .port_configupdate       ("PORT_UNUSED"),
        .port_fbin               ("PORT_UNUSED"),
        .port_inclk0             ("PORT_USED"),
        .port_inclk1             ("PORT_UNUSED"),
        .port_locked             ("PORT_USED"),
        .port_pfdena             ("PORT_UNUSED"),
        .port_phasecounterselect ("PORT_UNUSED"),
        .port_phasedone          ("PORT_UNUSED"),
        .port_phasestep          ("PORT_UNUSED"),
        .port_phaseupdown        ("PORT_UNUSED"),
        .port_pllena             ("PORT_UNUSED"),
        .port_scanaclr           ("PORT_UNUSED"),
        .port_scanclk            ("PORT_UNUSED"),
        .port_scanclkena         ("PORT_UNUSED"),
        .port_scandata           ("PORT_UNUSED"),
        .port_scandataout        ("PORT_UNUSED"),
        .port_scandone           ("PORT_UNUSED"),
        .port_scanread           ("PORT_UNUSED"),
        .port_scanwrite          ("PORT_UNUSED"),
        .port_clk0               ("PORT_USED"),
        .port_clk1               ("PORT_USED"),
        .port_clk2               ("PORT_UNUSED"),
        .port_clk3               ("PORT_UNUSED"),
        .port_clk4               ("PORT_UNUSED"),
        .port_clk5               ("PORT_UNUSED"),
        .self_reset_on_loss_lock ("OFF"),
        .width_clock             (5)
    ) altpll_inst (
        .inclk  ({1'b0, inclk0}),
        .clk    (sub_wire0),
        .locked (sub_wire2),
        .activeclock (),
        .areset (1'b0),
        .clkbad (),
        .clkena ({6{1'b1}}),
        .clkloss (),
        .clkswitch (1'b0),
        .configupdate (1'b0),
        .enable0 (),
        .enable1 (),
        .extclk (),
        .extclkena ({4{1'b1}}),
        .fbin (1'b1),
        .fbmimicbidir (),
        .fbout (),
        .fref (),
        .icdrclk (),
        .pfdena (1'b1),
        .phasecounterselect ({4{1'b1}}),
        .phasedone (),
        .phasestep (1'b1),
        .phaseupdown (1'b1),
        .pllena (1'b1),
        .scanaclr (1'b0),
        .scanclk (1'b0),
        .scanclkena (1'b1),
        .scandata (1'b0),
        .scandataout (),
        .scandone (),
        .scanread (1'b0),
        .scanwrite (1'b0),
        .sclkout0 (),
        .sclkout1 (),
        .vcoithout ()
    );

endmodule
