/*
 * Copyright (c) 2026 Anton Maurovic
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none

module tt_um_algofoogle_hello_world (
//    input  wire       VGND,
//    input  wire       VDPWR,    // 1.8v power supply
////    input  wire       VAPWR,    // 3.3v power supply
    input  wire [7:0] ui_in,    // Dedicated inputs
    output wire [7:0] uo_out,   // Dedicated outputs
    input  wire [7:0] uio_in,   // IOs: Input path
    output wire [7:0] uio_out,  // IOs: Output path
    output wire [7:0] uio_oe,   // IOs: Enable path (active high: 0=input, 1=output)
//    inout  wire [7:0] ua,       // Analog pins, only ua[5:0] can be used
    input  wire       ena,      // always 1 when the design is powered, so you can ignore it
    input  wire       clk,      // clock
    input  wire       rst_n     // reset_n - low to reset
);

	reg [15:0] counter;

	always @(posedge clk) begin
		if (~rst_n)
			counter <= 0;
		else
			counter <= counter + 16'd1;
	end

	assign {uio_out,uo_out} = counter + {8'b0, ui_in};
	assign uio_oe = '1; // All 1.

	wire _unused = &{ena, 1'b0};

endmodule
