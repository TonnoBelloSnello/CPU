Assembly Language Syntax
========================

What an operand can look like
--------------------------------

Every instruction reads its operands from a fairly rich set of possible
forms, and it helps to think of them in a few natural groups rather than as
one flat list.

**Registers themselves** come in a few flavours: the plain general-purpose
``R0``–``R14``, with ``SP`` and ``LR`` as friendlier names for ``R13`` and
``R14``, and ``PC`` for the program counter. Alongside them sit the two
peripheral registers, ``LE`` (reads and writes the ten LEDs, ``LEDR[9:0]``)
and ``HEX`` (the seven-segment display register, usable as a destination
or as an ``Operand2`` source). The quantized-inference extension adds two
more register families on top: ``Q0``–``Q7``, the eight-lane INT8 vector
registers, and ``A0``–``A3``, the 32-bit accumulators both accepted only
where the vector instruction class actually expects them. Neither is named
starting with ``V``, because ``Vn`` already means something else entirely
(see immediates, just below); and both namespaces are reserved exactly the
way ``R`` already is, so a data symbol or code label named ``Q3`` or ``A0``
is rejected at assembly time rather than silently shadowing the register.
[Quantized inference](tinyml.md) has the full list of vector and tensor
instructions these registers feed into.

**Immediate values** plain numbers written directly into an instruction
come in a few written forms: decimal with a ``V`` prefix (``V123`` means
123), binary with a ``VB`` prefix (``VB1010`` means 10), and a negative
version of either (``V-5``, ``VB-1010``). A negative immediate isn't always
usable exactly as written: the assembler only rewrites it into an
equivalent instruction when an exact one-instruction equivalent genuinely
exists ``ADD``/``SUB``, ``ADC``/``SBC``, ``CMP``/``CMN`` and ``MOV``/
``MVN`` all have one and for anything else, a negative immediate is
rejected outright rather than silently changing what the instruction means.
Floating-point literals get their own prefix, ``F1.5`` or ``F-0.25``,
understood as binary16 and only accepted where a floating-point instruction
expects a value. And a single-character string in quotes, ``"A"``, is
itself a valid immediate: it's simply the UTF-8 codepoint of that one
character, so ``MOV R1, "a"`` loads 97.

**Named things** resolve to a number at assembly time rather than being
written out as one directly. A bare variable name resolves to that
variable's address in the data section; a name declared with ``const``
resolves to whatever value it was given, anywhere an immediate is accepted
and subject to that particular instruction's own range limit. A whole
expression built out of constants, written as ``V(expr)`` for example
``V(1 << 11)`` or ``V(MAP_SIZE + 32)`` is evaluated at assembly time and
its result is encoded directly into the instruction's immediate field; this
is a compile-time convenience, not a wide-load mechanism, so it's still
bound by the same 12-bit range an ordinary immediate has.

**Memory access** comes in a named and an indirect form: ``[variable_name]``
loads or stores the byte living at that variable's address, while
``[Rn]`` does the same thing through whatever address happens to be sitting
in a register useful the moment an address needs to be computed rather
than known up front.

**Shifted register operands** let ``Operand2`` be a register value modified
in flight rather than used as-is: ``Rm LSL Vn``, ``Rm LSR Vn``, ``Rm ASR
Vn``, ``Rm ROR Vn`` (or the ARM-style spelling with an extra comma before
the shift). Floating-point instructions don't accept this form at all
shifting a float bit pattern isn't a meaningful operation and it's
unrelated to the vector lane/register selectors vector instructions use,
which are a separate operand form of their own. The same four shift
operations are also available as standalone pseudo-instructions,
``LSL``/``LSR``/``ASR``/``ROR Rd, Rm, amount``, with a shorter two-operand
spelling, ``LSL/LSR/ASR/ROR Rd, amount``, that implicitly reuses ``Rd`` as
``Rm``.

**Wider constants than one instruction can hold** get their own syntax,
``=expr``, usable only as the source of a ``MOV`` covered in its own
section below, since it quietly expands into more than one instruction.

**Register lists**, written ``{R4-R7, LR}``, are accepted only by ``PUSH``
and ``POP``, and are pure assembler sugar rather than a new kind of
operand in hardware: see the register-list rules below.

**Tensor configuration fields** are the odd one out in this list, because
they're not really values at all they're bare names, like ``MODE``,
``IN_BASE`` or ``K_W``, that only make sense as the first operand of
``NPUCFG``.
[Quantized inference](tinyml.md) lists every field a layer can configure.

One more thing every program gets for free, without declaring anything:
the full set of ``NPU_*`` constants ``NPU_CONV``, ``NPU_DEPTHWISE``,
``NPU_MAXPOOL``, ``NPU_AVGPOOL``, ``NPU_LUT``, ``NPU_ARGMAX``, the flag
bits ``NPU_ACC_IN``/``NPU_ACC_OUT``/``NPU_NO_BIAS``, the result codes
``NPU_OK``/``NPU_ERR_SHAPE``/``NPU_ERR_PATCH``, and ``NPU_LANES`` and
``NPU_PATCH_DEPTH`` are already in scope everywhere, so a layer
configuration reads as ``NPUCFG MODE, V(NPU_MAXPOOL)`` rather than some
bare, unexplained number. Because these names are always in scope,
declaring a ``const`` that happens to reuse one of them is treated as an
outright error rather than a silent shadow that would only bite later.

The overall shape of a program
----------------------------------

::

    include "shared.de1"

    const TEX_BASE = 0x8000

    space:
        variable_name = binary_value
        another_var   = binary_value

    main:
        instruction1
        instruction2
        B label_name

    label_name:
        instruction3

A program is really just directives, one optional data section, and then
code in that conceptual order, even though, as the next section
explains, directives themselves are allowed to appear anywhere in the
file.

### Directives: resolved before anything else

Directives are handled in a pass that happens before the file is even split
into sections, which is exactly why they're allowed to appear anywhere in
the source rather than being pinned to the top by the time the rest of
assembly begins, they've already been resolved away and neither the parser
nor the encoder ever sees them as such.

``include "file"`` splices another source file in, textually, at the exact
point it appears. The path given is relative to whichever file contains the
``include``, and both circular include chains and chains that nest too
deeply are rejected rather than silently mishandled. This directive is only
available when assembling an actual file on disk the in-memory
simulation and web-editor paths have no source directory to resolve a
relative path against, and simply report that rather than guessing one.

Because inclusion is purely textual, an included file is allowed to open
the data section itself, leaving the including program to continue and
complete it. For instance, ``data/weights.de1`` might contain nothing but::

    space:
        weights = {{1,255,1,255}}

and the program that uses those compile-time weights would then read::

    include "data/weights.de1"
        output: 8

    main:
        NPUCFG W_BASE, weights

There still has to be exactly one ``space:`` section after every include
has been expanded the assembler allocates the imported data in
declaration order and folds it into the same image and MIF files a program
without any includes would produce, so no separate weight MIF is ever
needed. A file that only declares a data section, with no code at all, is
perfectly valid as editor input on its own, even though it isn't a runnable
program by itself.

The VS Code extension goes a step further with includes: it resolves
imported symbols for autocompletion and Go to Definition, reports errors
against their original source files rather than the including file, and
uses the in-memory contents of any open, unsaved DE1 files while doing so.
Actually compiling or encoding, though, always reads from disk so every
dependency needs to be saved first and an untitled, never-saved document
can't resolve a relative include at all, since it has no path of its own to
resolve one against.

``const NAME = expression`` declares a compile-time integer constant. A
constant is allowed to reference any constant declared earlier in the
file, which is what lets a whole memory map be written out once, in terms
of itself::

    const TEX_BASE = 0x8000
    const MAP_BASE = TEX_BASE + 0x1000
    const MAP_SIZE = 32 * 32

A constant name, once declared, resolves exactly like a data symbol
wherever an operand is expected (``ADD R0, R0, MAP_SIZE``), can size a
buffer reservation (``grid: MAP_SIZE``), and is not allowed to collide with
either a data symbol or a code label.

### Constant expressions: what can appear inside `V(...)`

Expressions can combine integer literals decimal, or prefixed with
``0x``, ``0b`` or ``0o`` with previously declared constants, using the
operators ``+ - * / % << >> & | ^ ~`` and ordinary parentheses for
grouping; division always truncates as integer division. These expressions
are evaluated over a deliberately restricted grammar rather than by a
general-purpose interpreter, which is a safety property as much as a
simplicity one: there's no way for an expression to do anything other than
compute a number.

The expression evaluator itself doesn't stop at 12 bits whatever
instruction or directive actually consumes the result is what sets the
real range. For most instructions, ``V(expr)`` becomes an ordinary
``Operand2`` immediate and has to evaluate to something between 0 and
4095; ``B`` and ``BL`` instead accept a full 20-bit target, and shift
amounts keep their own separate 0–31 range regardless of context. To get a
wider non-negative value like ``1 << 15`` into a register at all, the
wide-load form below is what's needed ``V(...)`` alone cannot reach it.

### Wide constant loads: getting a big number into a register

An ordinary immediate ``Operand2`` only has 12 bits to work with, so any
constant above 4095 simply can't be written as ``V(expr)`` it has to be
built up out of shifts instead. Writing ``MOV Rd, =expr`` does exactly
that for you: the assembler works out how large the value actually is and
emits whatever ``MOV``/``LSL``/``ORR`` chain is needed to build it, all in
one line of source. A value up to 4095 costs just one plain ``MOV``; larger
values are built up byte by byte, and an ``ORR`` is simply skipped for any
byte that happens to be zero. This isn't guaranteed to be the shortest
possible sequence for every value just a correct one::

    MOV R11, =0x6600      # MOV R11, V102 ; LSL R11, V8
    MOV R0, =MAP_BASE     # names and expressions are both accepted
    MOV R1, =buffer + 32  # data symbol addresses work too

A condition suffix on the ``MOV`` carries through to *every* word the
expansion produces (``MOVEQ R0, =0x1234`` conditions the whole chain, not
just its first instruction). One real restriction follows directly from
how this expansion works: because the number of words it expands to
depends on the actual value being loaded, a ``=`` expression is only
allowed to reference constants and data symbols, whose values are already
known by the time code addresses are being computed a code label's
address isn't known yet at that point, so referencing one here is reported
as an assembly error rather than silently guessed at.

The data section (`space:`)
--------------------------------

This is where a program's variables are declared, along with whatever
initial value each one should start with. Several different kinds of
initialiser are accepted, and each behaves a little differently once it's
actually in memory:

A **binary literal**, like ``counter = 00000000``, is the simplest case
here, an 8-bit value initialised to zero. Anything wider than 8 bits still
works, but takes ``ceil(bits/8)`` bytes to store: the assembler first pads
the literal on the left with zero bits up to a whole number of bytes, and
then stores those bytes in address order, lowest byte at the lowest
address. Because ``MOVM``/``SAVEM`` read memory little-endian, that
leftmost, zero-padded byte ends up being the **least significant** byte
once a ``MOVM`` reads it back::

    wide = 0110011000000000    # bytes 0x66, 0x00
    MOV  R0, [wide]            # R0 = 0x66   (first byte)
    MOVM R0, [wide]            # R0 = 0x0066 (NOT 0x6600)

As a second example, the 9-bit literal ``100000000`` gets padded up to
``0000000100000000``, stored as the two bytes ``0x01, 0x00``, and a
``MOVM`` reads that back as ``0x0001`` which is worth working through by
hand once, since the padding direction is easy to get backwards from
memory.

Float literals behave differently on purpose: ``pi = F3.5`` stores its
binary16 value little-endian to begin with, so a ``MOVM`` reads it back
completely unchanged, with none of the padding subtlety binary literals
have. In practice, if the goal is really just to build a specific 16-bit
constant like ``0x6600``, it's usually clearer to build it directly in a
register (``MOV R0, V102`` then ``LSL R0, V8``) than to reason about
byte ordering in a binary literal by hand.

Beyond binary and float literals, ``space:`` also accepts a **string
literal** (``greeting = "Hi"``, stored as sequential UTF-8 bytes), a
**matrix literal** (``A = {{1, 2}, {3, 4}}``, stored row-major, one byte
per element), and a plain **reserved buffer** (``buffer: 8``, meaning
eight zero-initialised bytes with no particular structure imposed on them
at all).

Labels
---------

Labels are what branch instructions actually target, and they follow a
short set of rules: a label has to end with a colon, has to appear alone
on its own line, can use letters, digits and underscores as long as it
starts with a letter or underscore, has to be unique across the whole
program, must not collide with any data symbol, and must not start with
``__`` that prefix is reserved for symbols the assembler itself
generates, such as the hidden ``TEXT`` blob and alias names described in
[VGA and text rendering](vga.md).

``main:`` is not a magic keyword it's an ordinary, branchable label, but
one with a special role: when it's present, it's what the bootstrap branch
described in [architecture](architecture.md) jumps to first. That's
exactly why helper subroutines are allowed to appear *before* ``main:`` in
the source file; the bootstrap simply skips over them on its way to the
real entry point. The optional ``space:`` section, if a program has one,
always has to come before any executable code, regardless of where
``main:`` itself sits.

String literals, in more detail
------------------------------------

String literals can appear in exactly two places, and they behave
differently in each. As an **immediate operand**, only a single-byte UTF-8
literal is accepted ``MOV R1, "A"`` loads the number 65 and there's no
way to write a multi-character immediate directly; a string longer than
one character has to be written into ``space:`` instead and read back byte
by byte from memory. As a ``space:`` **initialiser**, on the other hand,
any non-empty string is accepted and its bytes are simply stored in
sequence, one after another.

``TEXT`` is the one instruction that relaxes the single-character rule: it
accepts a genuine multi-character string literal, or the name of a string
label declared in ``space:``, and the assembler quietly builds a hidden
NUL-terminated copy of that text for the renderer to draw from the full
mechanics of that are covered in [VGA and text rendering](vga.md).
