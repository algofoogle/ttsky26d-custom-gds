/*
 * Copyright (c) 2026 Anton Maurovic
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none

module tt_um_algofoogle_hello_world (
	/*
`ifdef USE_POWER_PINS
    inout  wire       VDPWR,    // 1.8v power supply
////    inout  wire       VAPWR,    // 3.3v power supply
    inout wire       VGND,
`endif
*/
    input  wire [7:0] ui_in,    // Dedicated inputs
    output wire [7:0] uo_out,   // Dedicated outputs
    input  wire [7:0] uio_in,   // IOs: Input path
    output wire [7:0] uio_out,  // IOs: Output path
    output wire [7:0] uio_oe,   // IOs: Enable path (active high: 0=input, 1=output)
//    inout  wire [7:0] ua,       // Analog pins, only ua[5:0] can be used
    input  wire       ena,      // always 1 when the design is powered, so you can ignore it
    input  wire       clk,      // clock

//    // Example extra pins:
//    output wire k4,
//    output wire k3,
//    output wire k2,
//    output wire k1,
//    output wire k0,
    input  wire       rst_n     // reset_n - low to reset
);

	reg [15:0] counter;

	always @(posedge clk) begin
		if (~rst_n)
			counter <= 0;
		else
			counter <= counter + 16'd1;
	end

`ifdef AMM_USE_MACRO
	wire inverted;

	inverter_macro u_inverter (
		/*
		`ifdef USE_POWER_PINS
			.VCC(VDPWR),
			.VSS(VGND),
		`endif
		*/
			.A(ui_in[0]),
			.Y(inverted)
		);
		
	assign {uio_out,uo_out} = counter + { {8{inverted}} , ui_in};
`else
	assign {uio_out,uo_out} = counter + { 8'd0 , ui_in};
`endif
	assign uio_oe = '1; // All 1.

//    assign {k4,k3,k2,k1,k0} = counter[4:0];

	wire _unused = &{ena, uio_in, 1'b0};


endmodule
