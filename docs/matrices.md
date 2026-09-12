Matrix Instructions
===================

> `MMUL` predates the tensor engine and is kept only for the programs that
> already use it. It multiplies **unsigned** bytes and truncates each result
> to a byte, with no saturation, and its dimensions live in 4-bit fields, so
> it tops out at 15×15. For anything actually quantized signed INT8, a
> 32-bit accumulator, bias, requantization and an activation clamp, with
> 16-bit dimensions use the tensor engine instead: see
> [quantized inference](tinyml.md). A fully connected layer there is just a
> 1×1 convolution and needs no separate mode of its own.

Why this instruction exists at all
------------------------------------

Multiplying two matrices in software means three nested loops and one
multiply-accumulate per inner iteration perfectly ordinary work for a
CPU, but slow to write out by hand and slower still to run one instruction
at a time. ``MUL Rd, A, B`` gives a program a shortcut: write the two
matrix operands where a normal ``MUL`` would take two numbers, and the
assembler and the hardware do the rest between them, offloading the whole
triple loop to a small dedicated state machine instead of general-purpose
code.

How one `MUL` turns into four real instructions
---------------------------------------------------

There's no single opcode that says "multiply these two matrices" instead,
the moment the assembler sees ``MUL`` used with two matrix operands, it
expands that one line into a fixed **four-word sequence**, each word a
perfectly ordinary instruction in its own right::

    SETMA addr_A, rows_A, cols_A   # load matrix A descriptor
    SETMB addr_B, cols_B           # load matrix B descriptor
    SETMR addr_R                   # set result buffer address
    MMUL  Rd                       # execute; Rd = addr_R on completion

The first three instructions do nothing more than tell the hardware where
each matrix lives and how big it is; ``MMUL`` is the one that actually
starts the multiplication and, once it finishes, leaves the address of the
result buffer in ``Rd`` so the calling code knows where to read the answer
from.

To make this work, the hardware keeps a small set of internal registers of
its own that no assembly instruction can name directly they exist purely
to hold the state ``SETMA``/``SETMB``/``SETMR``/``MMUL`` pass between each
other:

| Register       | Width         | Purpose                          |
|----------------|---------------|--------------------------------------|
| ``MAR_A``      | ADDR_WIDTH    | Start address of matrix A in RAM |
| ``MAR_B``      | ADDR_WIDTH    | Start address of matrix B in RAM |
| ``MAR_R``      | ADDR_WIDTH    | Start address of result buffer   |
| ``mat_rows_a`` | 4 bits        | Row count of A                   |
| ``mat_cols_a`` | 4 bits        | Column count of A (= rows of B)  |
| ``mat_cols_b`` | 4 bits        | Column count of B                |
| ``mat_i/j/k``  | 4 bits each   | Loop indices                     |
| ``mat_a_row_cache`` | 16 × DATA_WIDTH | Current A row, preloaded once per row |
| ``mat_accum``  | 32 bits       | Dot-product accumulator          |

Notice that the three loop-index registers, ``mat_i``/``mat_j``/``mat_k``,
are exactly what a hand-written triple loop over rows, columns, and the
shared dimension would need the hardware is quite literally running that
same loop structure, just without fetching and decoding an instruction for
every inner step.

How the executer actually walks through the multiplication
--------------------------------------------------------------

Once ``MMUL`` is detected, the executer stops running ordinary instructions
one at a time and instead steps through a small dedicated state machine
until the whole matrix product is done::

    EX_IDLE
     └─ MMUL detected → initialise counters, prime A[0][0] read
    EX_MAT_WAIT_A  – wait for the first A row byte after a row change
    EX_MAT_WAIT_A2 – fill mat_a_row_cache, prefetching the next row byte when possible
    EX_MAT_WAIT_B  – wait for the first B column byte after a column/result write
    EX_MAT_WAIT_B2 – accumulate A[i][k] × B[k][j], prefetching the next B byte when possible
    Result write/advance logic – update (i, j) indices; loop or complete → IDLE

Reading that as a story rather than a diagram: every time the row of A
changes, the engine has to wait one RAM read to get the first byte of the
new row, then it streams the rest of that row into a small cache
(``mat_a_row_cache``) so it doesn't have to re-fetch it for every column of
B. Symmetrically, every time the column of B changes it waits for the first
byte of that column, then streams the accumulation across the shared
dimension, prefetching each next byte while it multiplies the current one.
Once a full dot product is done, the result byte is written out and the
loop indices step forward to the next column, and then the next row
until every cell of the result has been produced. Because the row of A is
cached and reused across every column of B, the *steady-state* cost, once
that first RAM wait for a given row or column segment is paid, really is
just one cycle per inner element the loop only pays for memory access
when it genuinely has to.

What this instruction cannot do
------------------------------------

Two limits are baked into the hardware rather than being a software
choice, so they're worth stating plainly: matrix dimensions cannot exceed
15×15 in either direction, because the row/column counters are only 4 bits
wide, and every element has to be an unsigned byte (0–255) there is no
signed or wider-than-a-byte version of this instruction. Anything that
needs signed values, saturation, or bigger tensors belongs on the tensor
engine described in [quantized inference](tinyml.md) instead.

There's a second, easier-to-miss limit as well: ``SETMA``, ``SETMB`` and
``SETMR`` each carry their address in the ordinary 12-bit ``Operand2``
field, exactly like any other immediate operand which means both
operand matrices and the result buffer the assembler generates for them
must all live below address 4096. A matrix laid out above that boundary
isn't silently truncated or misread; assembly simply fails outright at
build time, which is much easier to debug than a wrong answer at runtime
would be.

A worked example
-----------------

::

    space:
        A = {{1, 2, 3}, {4, 5, 6}}       # 2×3 matrix
        B = {{7, 8}, {9, 10}, {11, 12}}   # 3×2 matrix

    main:
        MUL R0, A, B        # hardware multiply; R0 = result address
        MOV R1, [R0]         # R1 = result[0][0] = 58
        ADD R0, R0, V1
        MOV R2, [R0]         # R2 = result[0][1] = 64
        ADD R3, R1, R2       # R3 = 122

Here A is 2×3 and B is 3×2, so the shared dimension is 3 and the result is
a 2×2 matrix, stored row-major starting at the address ``MUL`` returns in
R0. Reading the first row byte by byte ``result[0][0]`` then
``result[0][1]`` is just ordinary pointer arithmetic on that returned
address, exactly as it would be for any other buffer in RAM.
