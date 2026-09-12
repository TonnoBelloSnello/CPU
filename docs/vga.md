VGA, Pixel, and Text Rendering
==============================

How a program draws a single pixel
--------------------------------------

    PIXEL   Rx, Ry, color
    PIXELNB Rx, Ry, color

Both instructions write one colour byte into the VGA framebuffer, a
160×120 grid of pixels small by modern standards, but that's the whole
point: at that resolution, a program can address any pixel with two
ordinary 8-bit-range register values and still cover the entire visible
screen.

- **Rx** holds the X coordinate, 0 through 159.
- **Ry** holds the Y coordinate, 0 through 119.
- **color** is a single RGB332 byte (see below), given either as an
  immediate ``V0``–``V255`` or as a register.

The framebuffer itself is not part of the CPU's own RAM at all it's a
separate dual-port memory, 19,200 bytes (160 × 120), which the VGA
controller reads continuously at 65 MHz and scales up to fill the physical
1024×768 display. Keeping it separate means the video controller can read
pixels for the screen at its own steady pace without ever competing with
the CPU for the same memory port that programs and data live in.

Writing outside the valid range an X of 160 or more, or a Y of 120 or
more isn't an error; it's simply discarded silently, which is convenient
for code that computes coordinates near an edge without having to clamp
them by hand first.

### Why there are two versions of the same instruction

``PIXEL`` and ``PIXELNB`` write to the same framebuffer in the same way;
the difference between them is entirely about *when* the instruction
considers itself finished, which matters once a program is drawing many
pixels quickly. Every framebuffer write whether it comes from ``PIXEL``,
``PIXELNB``, or ``TEXT`` is actually routed through one shared internal
queue, 16 entries deep, and always committed in the exact order the
program issued them, regardless of which instruction produced each one.

- **``PIXEL`` is blocking-commit**: it doesn't complete until its own write
  has actually landed in the framebuffer. That makes it simple to reason
  about right after a ``PIXEL`` instruction, the pixel is definitely
  there at the cost of the instruction taking longer when the queue
  already has a backlog to drain.
- **``PIXELNB`` is enqueue-and-continue**: it completes as soon as its write
  is safely queued, without waiting for that write to actually commit. It
  only ever stalls if the queue is completely full, which makes it the
  right choice for a tight loop that's drawing many pixels and doesn't need
  to know the instant each one lands.
- **``TEXT``** enqueues one write per lit glyph pixel and only stalls, the
  same way ``PIXELNB`` does, if the queue fills up while it's drawing.

One more guarantee worth knowing: when the CPU halts, it doesn't just stop
it first drains whatever framebuffer writes are still sitting in the
queue, so a halted program never leaves the screen showing a partially
drawn frame.

RGB332: fitting a colour into one byte
-------------------------------------------

Since each pixel is only one byte, there's no room for the 24 bits a
typical modern colour would use. Instead, colours here are packed as
RGB332 3 bits of red, 3 of green, and only 2 of blue:

    Bit:  7  6  5  4  3  2  1  0
          R  R  R  G  G  G  B  B

| Bits  | Channel | Levels | Weight |
|-------|---------|--------|--------|
| [7:5] | Red     | 8      | ×32    |
| [4:2] | Green   | 8      | ×4     |
| [1:0] | Blue    | 4      | ×1     |

Put another way, a colour byte is built as
``color = (red << 5) | (green << 2) | blue``, where red and green each
range 0–7 and blue ranges only 0–3 blue gets the fewest levels because
the human eye is least sensitive to fine gradations of it, which is the
same reasoning many other 8-bit colour formats use.

A handful of common colours worked out for convenience:

| Colour  | Binary        | Decimal |
|---------|---------------|-----------|
| Black   | ``000_000_00`` | 0       |
| White   | ``111_111_11`` | 255     |
| Red     | ``111_000_00`` | 224     |
| Green   | ``000_111_00`` | 28      |
| Blue    | ``000_000_11`` | 3       |
| Yellow  | ``111_111_00`` | 252     |
| Cyan    | ``000_111_11`` | 31      |
| Magenta | ``111_000_11`` | 227     |
| Orange  | ``111_100_00`` | 240     |

How PIXEL and PIXELNB are actually encoded
-----------------------------------------------

``PIXEL`` lives in instruction class ``01`` under opcode ``0x6``
(``EXT_PIXEL``); its ``Rd`` field carries the X-coordinate register and
its ``Rn`` field carries the Y-coordinate register, with the colour in
``Operand2``. ``PIXELNB`` uses the same operand layout ``Rd`` for X,
``Rn`` for Y, ``Operand2`` for colour but sits in class ``11`` under
opcode ``0x6`` (``BR_PIXELNB``) instead, alongside ``WAITKNB`` at opcode
``0x7`` (``BR_WAITKNB``), which places its destination register in ``Rd``
and its selection mask in ``Operand2`` the same way ``WAITK`` does.

Both instructions accept a condition suffix, exactly like any other
instruction, which makes conditional drawing a single line rather than a
branch around a draw call::

    CMP R0, V10
    PIXELEQ R2, R3, V255      # draw only if R0 == 10
    PIXELNBNE R2, R3, V0      # enqueue draw only if R0 != 10

A small worked example filling the whole screen green shows the two
nested loops a full-screen draw needs, one over rows and one over columns
inside it::

    main:
        MOV R1, V0
    row_loop:
        MOV R0, V0
    col_loop:
        PIXEL R0, R1, V28       # green = 0b000_111_00 = 28
        ADD R0, R0, V1
        CMP R0, V160
        BLT col_loop
        ADD R1, R1, V1
        CMP R1, V120
        BLT row_loop

Drawing text with TEXT
--------------------------

Plotting individual pixels is enough to draw anything, but spelling out a
whole word letter by letter that way would be painfully slow to write.
``TEXT`` exists to make putting a short string of text on screen a single
instruction from the programmer's point of view, even though as the
assembler section below explains it actually expands into several real
instructions and draws through hardware one glyph at a time.

The user-facing syntax is::

    TEXT X, Y, SRC
    TEXT X, Y, SRC, COLOR

- ``X`` and ``Y`` can be given as ``R0``–``R12`` or as immediates (either
  ``V...`` or ``VB...`` form).
- ``SRC`` can be either a quoted string literal (``"HELLO"``, for example)
  or the name of a string variable declared in ``space:``.
- ``COLOR`` is optional, and can likewise be ``R0``–``R12`` or an
  immediate; leaving it out simply defaults to ``V255``, plain white.

A few things about how the rendering actually behaves are worth knowing
before relying on it:

- The font is a fixed 5×7 bitmap covering the printable ASCII range,
  32 through 126.
- Any byte outside that range, or otherwise non-printable, is drawn as a
  ``?`` rather than producing garbage or being skipped.
- Each character advances the cursor by 6 pixels 5 for the glyph itself,
  plus 1 pixel of spacing before the next one.
- Only the pixels that are actually *lit* in a glyph get written; the
  background and the spacing between characters are left completely
  untouched. This means redrawing shorter or different text over the same
  spot does **not** erase whatever was drawn there before a program that
  needs to erase old text has to paint over it explicitly.
- Anything that would fall outside the 160×120 framebuffer is clipped, the
  same as with ``PIXEL``.
- Rendering stops the moment it hits a NUL byte (``0x00``) in the source
  text, or after 16 characters, whichever comes first.

### What the assembler does behind the scenes

None of the mechanics above are visible to a program using ``TEXT`` from
the assembler's point of view, quite a lot happens to make one line of
source turn into pixels on screen:

- For both string literals and string labels, the assembler builds a
  deduplicated, NUL-terminated copy of the text in data memory (reusing an
  identical string if one already exists) and encodes a pointer to it
  the instruction itself never carries the text inline.
- When X, Y, or COLOR are given as plain immediates rather than registers,
  the assembler lowers them into small setup instructions that load those
  values into registers first, since the hardware drawing logic always
  reads them from registers.
- Because drawing needs to borrow a few registers internally, the setup and
  teardown sequence carefully preserves the complete values of ``R8``,
  ``R9``, and ``R12`` in private data-memory spill slots and it does this
  correctly even when one of *those* very registers happens to also be the
  source of X, Y, or COLOR for this particular call.
- A condition suffix on ``TEXT`` (``TEXTEQ``, for instance) applies to the
  *entire* lowered sequence as a unit, not just to one instruction within
  it the whole draw either happens or doesn't, never partially.

### Reaching into text that's already been drawn

Sometimes a program needs to change one character of text it already drew
updating a HUD counter, for instance without redrawing the whole
string and paying for a fresh lookup of its address. For every ``space:``
string label that's ever used as a ``TEXT`` source somewhere in the
program, the encoder quietly creates an extra symbol,
``__text_ref_label::<label>``, that points at the very same deduplicated
NUL-terminated blob the renderer reads from letting code reach in and
edit individual bytes of already-rendered text directly::

    MOV R6, __text_ref_label::ui_fps_line
    ADD R7, R6, V4
    SAVE R4, [R7]      # overwrite one ASCII character in the text blob

One caveat worth remembering: this alias only exists at all if that
particular label was actually used as a ``TEXT`` source somewhere in the
assembled program it isn't created automatically for every string in
``space:``, only for the ones ``TEXT`` actually draws.

### How TEXT itself is encoded

``TEXT`` uses instruction class ``01``, opcode ``0xE`` (``EXT_TEXT``). Its
``Rd`` field carries the X-coordinate register, its ``Rn`` field carries
the Y-coordinate register, and ``Operand2`` is a 12-bit immediate pointing
at the NUL-terminated text bytes described above. The colour, unusually,
isn't packed into the instruction word at all it's read from register
``R12`` at execution time instead, which is part of why the setup sequence
above takes care to preserve R12's original value across the call.

A few examples::

    TEXT V2, V4, "CPU"
    TEXT R0, R1, title
    TEXT V8, V12, "WARN", V224
