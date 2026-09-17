Architecture, Pipeline, and Timing
==================================

What this document is about
----------------------------

This CPU is a custom, ARM-like processor described in SystemVerilog and built
to run on an Altera/Intel DE1-SoC board (a Cyclone V, part number
``5CSEMA5F31C6``). ``quartus/CPUFrFr.qpf`` is the only synthesis project for
it, and the top-level module, ``hdl/CPU.sv``, wires the design straight to
that board's four push-buttons (``KEY[3:0]``), its six seven-segment
displays, and its ADV7123 VGA output. The same design also runs, instruction
for instruction and cycle for cycle, under the free Icarus Verilog simulator,
which is how it gets tested without needing a physical board on hand.

A Python program called the *encoder* turns human-readable assembly source
into the flat binary image that actually gets loaded into the processor at
power-on; [assembly syntax](assembly.md) and [the toolchain](toolchain.md)
cover that side. This document stays on the hardware side of that boundary:
what the registers are, how an instruction actually moves through the chip
cycle by cycle, how memory is laid out, and how a program gets from a file on
disk into the processor's memory in the first place.

Later, the processor was extended with hardware support for running small,
already-quantized neural networks extra registers, extra instructions, and
a dedicated engine that can execute a whole neural-network layer on its own.
That extension is big enough to deserve its own document,
[quantized inference](tinyml.md); this one only describes the one place
where it reaches back into the core: how the new engine borrows the same
memory port the CPU itself uses.

The registers
-------------

Registers are the small, fast storage locations an instruction reads its
inputs from and writes its result to everything the ALU touches passes
through one. This processor gives a program **15 general-purpose registers**,
named ``R0`` through ``R14``, each ``ADDR_WIDTH`` bits wide (16 bits in the
default configuration, matching the address bus). Four of those fifteen slots
carry an extra, conventional meaning on top of being ordinary registers:

- **R15, the Program Counter (PC)** is kept in its own register, separate
  from the R0–R14 file, because it changes every cycle in a way no ordinary
  register does a whole fetch-decode stage exists just to keep it moving.
- **R14, the Link Register (LR)**, holds the address to return to after a
  ``BL`` (branch-and-link) instruction, the way a call instruction on any
  other processor remembers where it was called from.
- **R13, the Stack Pointer (SP)**, is where ``PUSH`` and ``POP`` read and
  write. At reset it is initialised to ``MMIO_BASE`` the first address of
  the memory-mapped peripheral window described below so that the very
  first ``PUSH``, which decrements the pointer before writing, lands safely
  in ordinary RAM rather than on top of a peripheral register.
- **CPSR, the Current Program Status Register**, is not one of the numbered
  registers at all; it is a small bundle of four flag bits (N, Z, C, V),
  packed into bits [31:28], that the comparison instructions set and that
  conditional instructions read.
  [The ISA reference](isa.md) covers exactly which instructions touch it and
  what each flag means.

Two more registers are special not because of calling convention but because
they are wired straight to physical hardware on the board:

- **LE**, the LED register, drives the ten red LEDs (``LEDR[9:0]``) directly:
  whatever bit pattern ends up in LE is whatever pattern lights up.
- **HEX** drives the on-board seven-segment displays, one hexadecimal digit
  per nibble.

Both LE and HEX are ordinary registers from an instruction's point of view
any data-processing instruction that can write to a destination register can
write to LE or HEX instead, and either can be read back as a source operand
too. The trick that makes this possible without spending two more register
numbers is described in [the ISA reference](isa.md#why-register-14-and-register-15-mean-four-different-things):
LE reuses the bit pattern that would otherwise mean R15/PC, and HEX reuses
the one that would mean R14/LR, with one spare bit in the instruction word
disambiguating which of the pair is meant.

On top of the general-purpose file, the quantized-inference extension adds
two register files of its own, used only by the vector and tensor
instructions described in [quantized inference](tinyml.md):

- **Q0–Q7**, eight 64-bit *vector* registers. Each one holds eight 8-bit
  lanes side by side think of it as eight small numbers travelling
  together in one register with lane 0 living in the lowest byte.
- **A0–A3**, four 32-bit signed *accumulators*. These exist because summing
  many INT8 products together can overflow a 16-bit register quickly: a
  64-term dot product of two INT8 vectors can reach roughly 2²⁰, which
  R0–R14 simply cannot hold. Rather than aliasing the accumulators onto the
  general-purpose file and hoping nothing overflows, they are kept as
  separate, wider storage.

Both extra register files show up alongside the general-purpose ones in the
simulator's register snapshots, so nothing about them is hidden from view
during debugging.

### The fixed numbers behind the design

A handful of constants pin down exactly how wide everything is. Most are
defined once, in ``hdl/cpu_pkg.sv``, and then propagate through the rest of
the design as module parameters, so changing one in that single file is
enough to reshape the processor:

| Parameter             | Value                   | Notes                                           |
|-----------------------|-------------------------|--------------------------------------------------|
| ``DATA_WIDTH``        | 8 bits                  | Width of a single RAM cell (byte-addressable)    |
| ``RAM_ADDR_WIDTH``    | 16 bits (configurable)  | Yields 64 KB of addressable memory               |
| ``BR_TARGET_WIDTH``   | 20 bits                 | Absolute target reach of ``B``/``BL``            |
| ``MMIO_WINDOW_BYTES`` | 256 bytes               | Peripheral window at the top of the address space |
| Register width        | ``ADDR_WIDTH`` bits     | Matches the address bus (16 bits by default)     |
| Instruction width     | 32 bits                 | Fixed-length encoding                            |
| General-purpose regs  | 15 (R0–R14)             | R13 = SP, R14 = LR; R15/PC is separate            |
| Special registers     | PC, CPSR, LE, HEX       | See above                                        |
| Vector registers      | 8 × 64 bits (Q0–Q7)     | Eight INT8 lanes each; ``NPU_LANES``, ``NPU_VREGS`` |
| Accumulators          | 4 × 32 bits (A0–A3)     | Signed; ``NPU_ACCS``                             |
| Tensor window cache   | 512 × 9 bits            | ``NPU_PATCH_DEPTH`` in ``hdl/cpu_pkg.sv``; storage in ``hdl/npu.sv`` |
| Clock                 | 40.625 MHz core         | PLL output from the 50 MHz board clock; optional divider (``USE_SLOW_CLOCK``) |

``RAM_ADDR_WIDTH`` is the one most worth knowing about if you ever want a
bigger address space: it can be raised in ``hdl/cpu_pkg.sv`` to 20 bits
(1 MB) or 24 bits (16 MB), though 24 bits means a considerably longer
synthesis run and is only worth it if a program genuinely needs that much
memory.

The core does not run from the board's 50 MHz pin. That pin feeds the PLL
in ``hdl/vga_pll.v``, whose 325 MHz VCO drives two outputs: 65 MHz for the
VGA pixel clock and 40.625 MHz for the core. The reason is the execute
stage below: reading the instruction word, selecting Operand2, shifting it
and finishing the operation all happen in one clock period, and the
accumulator paths need 22.3 ns of it, so a 20 ns period missed setup by
2.3 ns. The two PLL outputs are declared asynchronous in
``hdl/CPUFrFr.sdc``; the framebuffer is the only state both domains touch
and it is a true dual-port RAM with one clock per port. If you shorten the
execute stage and want the core faster, lower ``clk1_divide_by`` in the PLL
and raise ``CLOCK_FREQ_HZ`` in ``hdl/cpu_pkg.sv`` to match: the VCO is fixed
at 325 MHz, so the reachable rates are 325/N MHz, and ``CLOCK_FREQ_HZ`` is
what ``WAIT`` counts milliseconds with.

How an instruction actually gets executed
------------------------------------------

The processor is **pipelined**, which just means that fetching the next
instruction and executing the current one happen at the same time rather
than one strictly after the other otherwise every instruction would pay
the full cost of both stages back to back. Two small state machines run
side by side to make this work, both managed by a compact controller module
called ``ProcessController``:

1. A **fetch-decode** state machine that only ever needs two states,
   ``FD_IDLE`` and ``FD_DECODE_DISPATCH``. It leaves ``FD_IDLE`` the moment
   the very first instruction is fetched, and then simply stays in
   ``FD_DECODE_DISPATCH`` fetching and decoding one instruction overlap
   with dispatching the previous one, cycle after cycle, with no need to
   return to idle in between. Only a reset, a halt, or a pipeline flush
   sends it back.
2. An **executer** state machine that runs in parallel, working through one
   instruction at a time, starting from an idle state (``EX_IDLE``) whenever
   there's nothing to do. Simple instructions pass through in a single
   cycle; instructions that need more time move through states such as
   ``EX_WAITING``, ``EX_WAIT_KEY``, the memory states ``EX_MEM_STORE_MULTI``
   and ``EX_MEM_LOAD_WAIT``, the matrix-multiplication states, the vector
   transfer states (``EX_VEC_LOAD``, ``EX_VEC_STORE``), and ``EX_NPU_RUN``
   for the tensor engine. There is no separate write-back stage tacked on
   at the end whichever state finishes an instruction commits its result
   directly, from that state.

The datapath and the write-back logic itself live in ``executer.sv``;
instruction dispatch and all of these multi-cycle state handlers are split
out into ``executer_dispatch.svh`` and ``executer_states.svh`` to keep that
file manageable. The text-rendering font lookup is its own separate module
again.

### Why straight-line code can run at one instruction per cycle

While the executer is busy with the instruction it currently has, the
fetch-decode side keeps working ahead: it fetches the next sequential
instruction and has it ready to go the moment the execution slot frees up.
Because a just-dispatched instruction can also trigger the fetch of the one
after it in that same cycle, ordinary ALU-style code the kind with no
branches or memory waits can sustain one instruction retired per clock
cycle once it gets going.

That overlap is suppressed, and fetching pauses, in exactly three
situations: when the executer is writing the PC this very cycle, when the
execution slot is still occupied by a multi-cycle instruction, or when the
loader hasn't finished bringing the program in yet (or the CPU is halted).

Branches get special treatment so they don't cost a pipeline flush every
time. ``B`` and ``BL`` are resolved by ``ProcessController`` at decode time,
and the fetcher is redirected to the branch target in that same cycle no
flush needed. Every *other* way of writing the PC (for example ``MOV PC,
R14`` to return from a subroutine) does cost a flush: whatever instruction
had already been fetched behind it gets thrown away, and fetching restarts
from the new address.

### How the processor avoids stalling on read-after-write hazards

A very common hazard in any pipelined design is reading a register in the
same cycle, or the cycle right after, another instruction just wrote to it
if the read went straight to the register file, it might see the old
value because the write hasn't landed yet. This processor solves it with a
small **forwarding path** rather than by stalling: it remembers the most
recent register written (``last_written_reg`` / ``last_written_value``) and
also the second-most-recent one (``last_written_reg2`` /
``last_written_value2`` needed because ``POP`` writes both its
destination register and ``SP`` in the same instruction). When a later
instruction reads a register, this logic checks whether either of those two
just-written values matches, and if so hands back that value directly,
bypassing the register file's own clock-edge delay entirely.

### Why a memory read can complete before the executer even asks for it

Main RAM is synchronous block RAM, which normally means: present an address
on one clock edge, get the data back on the next. Rather than pay that
penalty in the middle of executing every load, the executer resolves the
address for certain reads early during decode/dispatch, before execution
even properly starts and drives the data RAM's read address a cycle
ahead of when it's needed. By the time execution actually reaches the
instruction that wants the byte, it's often already sitting there waiting.

This early-read trick, called *prefetch*, is used for single-byte loads,
``POP``, the individual bytes of a ``MOVM``, uncached floating-point literal
bytes, the inner-loop reads of ``MMUL``, and the eight bytes a ``VLD``
transfers. It has to be disabled falling back to the older, slower
wait-state path whenever a RAM write is still pending, whenever the
instruction's condition hasn't been satisfied, or whenever the next safe
read address simply isn't known early enough to prefetch it.

### Why floating-point arithmetic costs three cycles instead of one

The unit that implements half-precision (binary16) arithmetic,
``fp16_unit``, is one large block of combinational logic meaning it
computes its answer through pure gate delay rather than through clocked
steps but it is too deep to settle within one 20 ns clock period at this
processor's target frequency. Rather than slow the whole clock down for the
sake of one unit, the executer spreads the operation across multiple
cycles: it registers the operands and the chosen operation
(``fp_a_r``, ``fp_b_r``, ``fp_op_r``) at dispatch, lets the combinational
cloud settle for ``FP_SETTLE_CYCLES + 1`` clock periods, and only then
commits the result directly into the register file, CPSR, or a display
register on the edge that ends the last settle cycle. That final step
*is* the architectural write-back; there's no intermediate staging register
involved. With the default ``FP_SETTLE_CYCLES = 1``, that's three cycles
total for any of ``FADD``/``FSUB``/``FMUL``/``FCMP``/``FMOV``:

1. **dispatch** the operands and the operation selector are captured into
   registers;
2. **settle** the combinational cloud works out the answer;
3. **settle/retire** the destination register, CPSR, or display register
   captures the result, and ``execute_done`` fires.

``fp_op_r`` exists purely so the timing tools can be told the truth about
this path: the multicycle exception in ``CPUFrFr.sdc`` is declared from the
FP launch registers to the write-back registers, but ``ex_opcode_r`` cannot
be one of those launch registers, because it also drives the plain,
single-cycle integer ALU into those same write-back registers. One timing
exception cannot separate two different paths that share a destination, so
``fp_op_r`` keeps the FP path distinct from the integer one.

``FDIV`` is the one floating-point operation that doesn't follow this
pattern cleanly: it still passes through a state called ``EX_FP_START``,
because the mantissa divider it uses can only see its operands once the
dispatch edge has actually landed, unlike the rest of the combinational
cloud.

### How the processor knows to stop

A null instruction all 32 bits zero is the halt signal. In the verbose
simulation build, hitting it ends the run with Icarus's ``$finish``; under
``SNAPSHOT_MODE``, which is what both ``run_snapshot`` and the web simulator
compile with, the testbench itself stops the run instead of relying on
``$finish``. On real hardware, the ``halted`` signal is simply asserted and
the pipeline stops advancing.

### How long each kind of instruction actually takes

Not every instruction costs the same number of cycles, and the differences
mostly follow directly from everything above a plain ALU op is one cycle
because nothing about it needs settling time or a memory round-trip, a
floating-point op costs three because of the settle logic just described,
and so on:

| Instruction type          | Cycles |
|---------------------------|--------|
| Data processing (ALU)     | 1      |
| B / BL                    | 1; decode redirects the fetch without a pipeline flush |
| Other writes to PC        | Instruction cost plus pipeline flush |
| Scalar MUL                | 1      |
| Scalar DIV                | Data-dependent; sequential radix-4 divider with leading-zero skip |
| FP add/sub/mul/cmp/mov    | ``FP_SETTLE_CYCLES + 2`` 3 at the current value of 1 |
| FP divide (FDIV)          | 20, operand-independent shares ``divider_seq`` with integer DIV |
| FP literal Operand2       | +0 on cache hit, +2 on prefetched miss, +3 on fallback miss |
| Memory load               | 2 with prefetch, 3 on fallback path |
| MOVM load / POP           | ``N + 1`` with continued prefetch, up to ``2 × N + 1`` on fallback path |
| Memory store              | 1 ``SAVE`` retires on issue; the RAM write commits behind it |
| SAVEM store / PUSH        | ``N + 1`` (one write cycle per byte, then commit) |
| PIXEL                     | 3 with an empty queue (issue plus the commit wait), more while a backlog drains |
| PIXELNB                   | 1 (stalls only when framebuffer queue is full) |
| TEXT                      | Hardware draw: ≈44 cycles/char plus startup/termination, capped at 16 chars; assembler setup/teardown adds cost |
| WAIT                      | ``N × CYCLES_PER_MS`` of stall, plus 2 for issue and exit |
| WAITK                     | Unbounded (until selected key press) |
| WAITKNB                   | 1 (returns current selected key hit mask) |
| Matrix MUL (m×k × k×n)   | ≈ one cycle per inner element after row/column read startup |
| Quantized scalar ops (QADD..SXTB) | 1 |
| Vector ALU (VDOT, VSUM, VDUP, VEXT, VINS, VMAXR) | 1 |
| Accumulator ops (ACLR, ASET, AGET, AGETS, AQMUL, ARSHR) | 1 |
| NPUCFG                    | 1 |
| VLD / VST                 | 9 (one byte per cycle plus issue) |
| NPURUN                    | Data-dependent; ≈ one cycle per weight byte in the inner loop |

How the tensor engine borrows the CPU's memory port
-----------------------------------------------------

``hdl/npu.sv`` is the tensor engine that [quantized inference](tinyml.md)
describes in full the module that can run an entire neural-network layer,
convolution or pooling or activation, from a single instruction. What
belongs in *this* document is the one place it reaches back into the core
design: it has no memory port of its own, so it has to share the CPU's.

The data RAM has exactly one 8-bit synchronous read port. Rather than build
a second port or an arbiter to referee between two masters, the design takes
a simpler route: while the engine is running (``npu_busy``), it takes over
the address, write-enable, and write-data lines that would normally belong
to the executer, the same way ``MMUL`` already did for matrix
multiplication. The executer keeps stalled in ``EX_NPU_RUN`` for the engine's
entire run, and the actual RAM lines are just a two-way switch between the
executer's own registers and the engine's:

    assign ram_read_addr  = npu_busy ? npu_mem_raddr : ram_read_addr_r;

That switch is what lets two different pieces of hardware share one
single-port RAM without needing a second port or any arbitration logic
between them but the price is that literally nothing else can run while a
layer is executing. There's no interrupt the engine can raise and no way for
a program to poll it early; a program that issues ``NPURUN`` simply waits
until the whole layer is done.

One consequence follows directly from the engine writing RAM behind the
executer's back: whenever ``EX_NPU_RUN`` finishes, the CPU throws away its
*entire* floating-point literal cache, rather than trying to work out which
individual addresses the engine might have touched. It would be more
precise to track exactly which bytes changed, but far simpler and safer
against a subtle bug to just assume the cache might be stale and rebuild
it on demand.

As for how fast the engine actually runs: the ceiling isn't the multiplier,
it's the memory. Because the data RAM has only one 8-bit read port, no
design can do better than one multiply-accumulate per cycle if it has to
fetch a fresh weight byte for every single multiply. The tensor engine gets
close to that ceiling by caching the reduction window once, which frees the
port to stream weight bytes continuously instead of splitting its time
between weights and activations. [Quantized inference](tinyml.md) has the
measured numbers comparing this engine against the plain scalar loop and
the eight-lane vector loop.

How a program is laid out in memory
-------------------------------------

When the encoder assembles a program, it produces an image with this shape:

    Address 0–3:     Bootstrap branch (B <entry_address>, 20-bit target)
    Address 4..X-1:  Data section (variables, matrices, result buffers)
    Address X..end:  Code section (encoded 32-bit instructions)

and, working down from the top of the address space instead of up from the
bottom:

    MMIO_BASE..top:  Memory-mapped peripheral window (256 bytes)
    ..MMIO_BASE-1:   Stack, growing down from the reset value of SP

The very first word in memory is always a branch instruction, not data
this is the "bootstrap" that gets the processor from address zero to
wherever the actual program begins. It used to be a plain ``MOV PC,
V<addr>``, but that instruction's 12-bit immediate field could only reach
the first 4 KB of memory, even though the program's *code* could quite
easily extend past that boundary once it started running. The bootstrap
word is now a proper ``B`` instruction instead, which carries a full 20-bit
target and can point anywhere the address space reaches.

Laying out the data section is entirely the encoder's job, and it always
happens in the same order:

1. every variable declared under ``space:`` gets an address, starting at
   offset zero;
2. then the encoder appends whatever data the code itself implies needed to
   exist, in a fixed order: deduplicated, NUL-terminated ``TEXT`` string
   blobs and their spill slots first, then inline matrix literals and the
   result buffers matrix multiplication needs, then deduplicated
   floating-point literals;
3. four bytes are added to every data address to leave room for the
   bootstrap word, and the whole data section is padded so that code always
   starts on a 4-byte boundary;
4. code labels are resolved next, which requires counting how many words
   each pseudo-instruction expands to matrix ``MUL``, ``TEXT``, register
   lists, and wide constant loads all expand to more than one word;
5. finally, the bootstrap branch itself is emitted, pointing at ``main:``
   when the program defines one, or otherwise at the very first instruction
   in the code section. This is why helper subroutines are allowed to sit
   physically *before* ``main:`` in the source file the bootstrap branch
   jumps straight past them.

How a program actually gets loaded onto the chip
---------------------------------------------------

A ``USE_INIT_FILE`` parameter in ``cpu_pkg.sv`` chooses between two entirely
different ways the assembled image reaches the processor:

1. **Init-file mode** (``USE_INIT_FILE = 1``, the default) bakes the program
   straight into the FPGA bitstream: ``file.mif`` initialises the
   instruction ROM and ``data.mif`` initialises data RAM at synthesis time,
   before the chip is even programmed. Because there's nothing left to
   load at runtime, the loader simply asserts ``loader_done`` immediately.
2. **Runtime loading** (``USE_INIT_FILE = 0``) instead brings the program in
   after the chip is already running: a module called ``Loader`` reads the
   canonical ``file.hex`` into an internal array, then copies it one byte
   per clock cycle into data RAM and a separate instruction memory,
   followed by one final null (halt) instruction. From that point on, CPU
   stores only ever touch data RAM, which keeps the same Harvard-style split
   between instructions and data that init-file mode has for free. The
   generated ``program_size.svh`` tells the loader exactly how many bytes to
   expect. Once every byte has been copied, ``loader_done`` releases the
   program counter and execution begins at address 0.

   This staging path has a real limit: it can hold at most
   ``LOADER_MAX_PROGRAM_SIZE`` bytes (63.75 KiB the RAM below
   ``MMIO_BASE`` including the trailing null word), because a bigger image
   would spill into the peripheral window. Init-file mode has no such
   ceiling and can use the entire configured ROM depth. The staging array
   itself is always declared, whichever mode is active, but synthesis tools
   constant-fold it away when ``USE_INIT_FILE = 1``, so choosing init-file
   mode costs no block RAM for a loader that will never run.

Getting key presses without a keyboard
-----------------------------------------

The DE1-SoC only gives the FPGA fabric four physical push-buttons, and its
USB host port is wired to the ARM-based HPS side of the chip rather than to
the fabric so plugging in a USB keyboard would mean routing its input all
the way through the ARM processor, which this design deliberately avoids.
Instead, the four-bit ``KEYS`` slot accepts presses from a *second* source
that needs no extra pins and no separate processor at all: an
``altsource_probe`` instance inside ``CPU.sv``, whose input register sits on
the JTAG SLD hub and can be written from the host computer over the exact
same USB-Blaster cable that programs the board in the first place.

Both places in the design that consume key presses ``mmio.sv`` for the
``KEYS`` MMIO slot, and ``executer.sv`` directly for ``WAITK``/``WAITKNB``,
which read the pins rather than going through the bus simply OR the two
sources together into one mask:

    keys_pressed = ~key_n | key_jtag

The consequence, and the whole point of building it this way, is that a
program has no way to tell a physical button press apart from a host-driven
one. Every program written against the ``KEYS`` slot before this mechanism
existed keeps working completely unchanged. The JTAG source is active-high,
so an idle host session contributes nothing at all, and with no host
connected, only the board's own physical buttons are ever seen. Because the
JTAG signal changes in its own clock domain (``TCK``), it crosses into the
CPU's clock domain through its own two-flop synchronizer the identical
technique already used for the physical keys.

Icarus Verilog has no library of Altera's proprietary megafunctions, and the
simulation build compiles every file under ``hdl/*.sv``, so this JTAG
instance sits behind an ``` `ifdef SIMULATION ``` guard and is simply tied to
zero when simulating there's no host to drive it in a test run anyway. A
dedicated MMIO testbench, ``tests/test_jtag_keys.py``, exercises the merge
logic directly instead.

### How the host side actually drives it

On the host computer, a Tcl script (``scripts/board/jtag_keys.tcl``) runs
under Quartus's ``quartus_stp`` tool and holds one In-System Sources session
open for as long as it's needed. Opening that session costs several
seconds, which rules out spawning a fresh process for every single
keystroke so it has to stay open and be driven repeatedly instead.

The two sides of this bridge talk to each other over a loopback network
socket, and that choice is load-bearing rather than a stylistic preference:
``quartus_stp`` routes its Tcl output through its own internal message
manager, which block-buffers whenever standard output is a pipe rather than
a terminal. Measured directly: a line written immediately and a line
written four seconds later both only appeared once the process exited
and a session that's *meant* to stay open for the whole interaction never
exits, so a client reading the child's stdout would simply hang forever
before seeing anything, even with an explicit flush. A socket doesn't have
this problem: each line arrives the moment it's written. The child's own
stdout is instead redirected to a log file, which only gets read back and
shown if the session actually fails.

``scripts/board/jtag_keys.py`` is the client that talks to that Tcl script.
By default it maps the number keys ``1``–``4`` onto KEY0–KEY3, but a single
binding can cover several keys at once (``--map a=0,f=12``), which is what
makes chords possible the built-in ``--preset doom`` binding, for
example, maps WASD plus ``f`` for the KEY1+KEY2 trigger that
``programs/doom.de1`` reads as a chord. Only a changed mask is ever shifted
out over the socket, and the JTAG cable itself measures at roughly 0.5 ms
per update on a DE1-SoC fast enough that the cable is never what limits
how responsive this feels. What actually limits the feel is how the host
learns that a key is down at all, which is where the two input modes below
come in.

A plain terminal only ever reports that a key was *pressed*, never that it
was *released*. Driven naively, that would force every press into a
fixed-length pulse, and holding a key down would just look like the
operating system's own autorepeat one press, a pause of a few hundred
milliseconds, then a stream of repeats. That stutter is exactly why the
default on Windows instead reads live key state through
``GetAsyncKeyState``: a held key simply reads as a held button the whole
time it's down, and movement stays continuous. The trade-off is that this
kind of key state is global to the whole system, so a key registers no
matter which window currently has focus. Passing ``--pulse`` restores the
older, typed-character model instead, which only ever sees keys typed into
this particular window; ``--toggle`` builds on that same model but latches
each bit on until its key is pressed again, which suits a mode-switch
button far better than a momentary one.

In pulse mode, how long a press lasts is set by ``--hold`` milliseconds, and
each binding tracks its own expiry independently, so pressing two keys in
quick succession doesn't cut either one short turning while firing, for
instance, keeps working correctly. ``--toggle``, because latching needs a
discrete press to flip a bit on, necessarily implies the pulse model too.

Both input modes quit on ``q`` or Escape, with one exception: if a binding
map assigns something to the ``q`` key itself, that mapping keeps driving
its KEY as normal, and Escape becomes the *only* way to quit a key a
binding actually uses must never silently double as the exit key too.

One last constraint worth knowing: the Programmer, SignalTap, and the
In-System Sources and Probes editor all need the JTAG cable to themselves,
so none of them can be open at the same time as one of these sessions.
