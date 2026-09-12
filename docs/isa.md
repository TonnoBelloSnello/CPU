Instruction Set Architecture
============================

What every instruction looks like
------------------------------------

Every single instruction this processor understands is exactly one 32-bit
word there is no shorter or longer form, which keeps fetching and decoding
simple at the cost of never being especially compact. Reading that word from
the top bit down, it splits into these fields:

    [31:28]  Condition code   (4 bits)
    [27:26]  Instruction class (2 bits)
    [25]     Immediate flag    (1 bit)
    [24:21]  Opcode            (4 bits)
    [20]     Flag bit          (1 bit)
    [19:16]  Rn                (4 bits) first source register
    [15:12]  Rd                (4 bits) destination register
    [11:0]   Operand2          (12 bits) immediate value or register index

Reading that as a sentence rather than a diagram: the top four bits decide
*whether* the instruction runs at all this cycle (the condition), the next
two decide which broad family it belongs to, one bit says whether the last
operand is a literal number or a register, four bits pick the specific
operation within its family, one bit is overloaded for a couple of special
cases described below, and the remaining sixteen bits name up to two
registers and a twelve-bit operand.

``B`` and ``BL`` break this pattern on purpose. Neither one uses ``Rn`` or
``Rd`` for anything, so instead of wasting those eight bits, the encoding
lets them merge with ``Operand2`` to form one wide, **20-bit absolute
branch target**:

    [31:28]  Condition code
    [27:26]  11 (branch class)
    [25]     unused
    [24:21]  Opcode (0 = B, 1 = BL)
    [20]     unused
    [19:0]   Branch target

The hardware only ever looks at the low ``ADDR_WIDTH`` bits of that target,
so on the default 16-bit core a branch can still reach anywhere across the
full 64 KB address space. Every other branch-class instruction and there
turn out to be quite a few, since that class also carries a set of
non-branching ALU operations described further down keeps the ordinary
``Rn``/``Rd``/``Operand2`` layout.

### What Operand2 means when it's a register instead of a number

The **immediate flag** (bit 25) decides how ``Operand2`` should be read.
When it's clear meaning Operand2 names a register rather than holding a
literal value those twelve bits are further broken down into a shift
specification and a register index:

    [11:7]  Shift amount (0..31)
    [6:5]   Shift type   (00=LSL, 01=LSR, 10=ASR, 11=ROR)
    [4]     HEX source marker (used only when register index is 14)
    [3:0]   Source register (R0-R15 / LE / LR)

If the shift amount happens to be zero, Operand2 is simply used unshifted,
exactly as written. On the assembly side, both ``OP Rd, Rn, Rm LSL Vn`` and
the more ARM-flavoured ``OP Rd, Rn, Rm, LSL Vn`` (with the extra comma) are
accepted and mean the same thing.

Shifting a register is common enough that it also gets its own family of
pseudo-instructions, which the assembler simply lowers into a ``MOV`` with a
shifted Operand2 rather than needing any hardware of its own:

- ``LSL Rd, Rm, amount`` / ``LSR Rd, Rm, amount`` / ``ASR Rd, Rm, amount`` /
  ``ROR Rd, Rm, amount``
- and a shorter two-operand form, ``LSL Rd, amount`` and so on, which is
  exactly equivalent to writing ``Rm = Rd``.

### Why register 14 and register 15 mean four different things

The **flag bit** (bit 20) exists to resolve an ambiguity on purpose, not by
accident: the two highest register indices, 14 and 15, each secretly stand
for *two* different registers depending on that one bit.

| Rd field | Flag bit | Write target                    |
|----------|----------|---------------------------------|
| 15       | 0        | PC (program counter)            |
| 15       | 1        | LE (LED register)               |
| 14       | 0        | LR (link register)              |
| 14       | 1        | HEX (7-segment display register) |

None of this is something a programmer needs to manage by hand the
assembler sets the flag bit automatically the moment ``LE`` or ``HEX``
appears as a destination operand in the source text, so writing ``MOV LE,
V10`` just works, and the underlying encoding trick stays invisible.

### The four instruction classes

Bits [27:26] sort every instruction into one of four families:

| Bits [27:26] | Class      | Mnemonic range                                      |
|--------------|------------|-----------------------------------------------------|
| ``00``       | Data Processing | AND, EOR, SUB, RSB, ADD, ADC, SBC, RSC, TST, TEQ, CMP, CMN, ORR, MOV, BIC, MVN |
| ``01``       | Extended   | MUL (scalar), DIV (scalar), SETMA, SETMB, SETMR, MMUL, PIXEL, TEXT, WAIT, WAITK, FADD, FSUB, FMUL, FDIV, FCMP, FMOV |
| ``10``       | Memory     | MOV (load), SAVE (store), MOVM, SAVEM, PUSH, POP, plus the NPU escape |
| ``11``       | Branch     | B, BL, ABS, MAX, MIN, MADD, PIXELNB, WAITKNB, QADD, QSUB, SSAT, USAT, QRDMULH, RSHR, RELU, SXTB |

One entry in that table is doing more work than it looks like it is: opcode
``0x0`` of the memory class is an **escape**. Rather than meaning one
specific instruction, it tells the decoder that the *real* operation is
named by a sub-opcode hiding in the ``Rn`` field instead which turns what
would otherwise be one wasted opcode into room for sixteen more
instructions. This is why the sixteen vector, accumulator, and
tensor-engine instructions from the quantized-inference extension only cost
one opcode in total rather than sixteen. That extension needed somewhere to
go precisely because, by the time it was added, the data-processing and
extended classes already had every one of their sixteen opcodes spoken for
so it split across the two places that still had room: the free
branch-class opcodes ``0x8``–``0xF`` picked up the new scalar operations
(fitting naturally alongside ``ABS``, ``MAX``, ``MIN`` and ``MADD``, which
already lived there as the class's home for non-branching ALU work), and
the one free memory-class opcode became the vector/tensor escape described
above. The full story, and the complete list of what rides on that escape,
is in [quantized inference](tinyml.md).

### Condition codes: making every instruction optional

Every single instruction not just branches carries a four-bit condition
in its top bits, and only actually executes if the CPSR flags satisfy that
condition. This is what lets short, branch-free ``if`` statements be written
as one plain instruction with a suffix, rather than a branch around a block:

| Code   | Suffix | Meaning                  | Flags tested         |
|--------|--------|--------------------------|-----------------------|
| 0000   | EQ     | Equal                    | Z = 1                |
| 0001   | NE     | Not equal                | Z = 0                |
| 0010   | CS     | Carry set / unsigned ≥   | C = 1                |
| 0011   | CC     | Carry clear / unsigned < | C = 0                |
| 0100   | MI     | Negative                 | N = 1                |
| 0101   | PL     | Positive or zero         | N = 0                |
| 0110   | VS     | Overflow                 | V = 1                |
| 0111   | VC     | No overflow              | V = 0                |
| 1000   | HI     | Unsigned higher          | C = 1 and Z = 0      |
| 1001   | LS     | Unsigned lower or same   | C = 0 or Z = 1       |
| 1010   | GE     | Signed ≥                 | N = V                |
| 1011   | LT     | Signed <                 | N ≠ V                |
| 1100   | GT     | Signed >                 | Z = 0 and N = V      |
| 1101   | LE     | Signed ≤                 | Z = 1 or N ≠ V       |
| 1110   | AL     | Always (default)         |                    |
| 1111   | NV     | Never (reserved)         | never executes        |

A suffix can be appended to any mnemonic in the source text for example,
``ADDNE R0, R1, R2`` only actually adds when the zero flag is clear (i.e.
when the previous comparison found its operands unequal); leaving the
suffix off is the same as writing ``AL``, and the instruction simply always
runs.

Instruction reference
-----------------------

The quantized-inference extension the scalar operations riding on the
branch class, the whole vector instruction class, and the tensor engine
gets its own dedicated reference in [quantized inference](tinyml.md), since
there's a lot to say about *why* it's shaped the way it is and how the
numbers behave. The tables in this document only give its raw encodings for
completeness; the semantics, the cost model and the quantization contract
all live over there.

### Data processing

#### Arithmetic

| Mnemonic | Syntax                    | Operation               |
|----------|---------------------------|--------------------------|
| ADD      | ``ADD Rd, Rn, Operand2``  | Rd = Rn + Op2           |
| ADC      | ``ADC Rd, Rn, Operand2``  | Rd = Rn + Op2 + C       |
| SUB      | ``SUB Rd, Rn, Operand2``  | Rd = Rn − Op2           |
| SBC      | ``SBC Rd, Rn, Operand2``  | Rd = Rn − Op2 − (1 − C) |
| RSB      | ``RSB Rd, Rn, Operand2``  | Rd = Op2 − Rn           |
| RSC      | ``RSC Rd, Rn, Operand2``  | Rd = Op2 − Rn − (1 − C) |
| MUL      | ``MUL Rd, Rn, Operand2``  | Rd = Rn × Op2 (scalar)  |
| DIV      | ``DIV Rd, Rn, Operand2``  | Rd = Rn ÷ Op2 (unsigned scalar) |

``MUL`` and ``DIV`` are listed here because they read naturally as
arithmetic, but strictly speaking they aren't data-processing instructions
at all they're encoded in the **extended** class ``01`` (opcodes ``0x1``
and ``0xF``), which the *Extended Instructions* section below covers in
more depth.

``ADC``, ``SBC``, and ``RSC`` each fold the current CPSR carry flag into
their result, following the same carry/no-borrow convention ARM uses, which
is what lets a program chain them together to do arithmetic wider than one
register.

Every three-operand instruction in this table also accepts a shorter,
two-operand form, where ``Rn`` is simply assumed to be the same register as
``Rd``:

    ADD R0, V5        # equivalent to ADD R0, R0, V5

Negative immediates are handled transparently wherever an exactly
equivalent instruction exists: ``ADD R0, V-5``, for instance, is silently
rewritten by the assembler into ``SUB R0, R0, V5``, since adding a negative
number and subtracting its positive counterpart are the same operation.
That rewriting only ever happens when it's provably safe an operation
with no such equivalent, such as ``AND`` or scalar ``MUL``, simply rejects a
negative immediate outright rather than silently reinterpreting it, and the
value has to be materialized into a register first instead.

#### Logical

| Mnemonic | Syntax                    | Operation               |
|----------|---------------------------|--------------------------|
| AND      | ``AND Rd, Rn, Operand2``  | Rd = Rn & Op2           |
| EOR      | ``EOR Rd, Rn, Operand2``  | Rd = Rn ^ Op2           |
| ORR      | ``ORR Rd, Rn, Operand2``  | Rd = Rn \| Op2          |
| BIC      | ``BIC Rd, Rn, Operand2``  | Rd = Rn & ~Op2          |

#### Comparison flags only, no result

| Mnemonic | Syntax                 | Operation                |
|----------|------------------------|---------------------------|
| CMP      | ``CMP Rn, Operand2``   | flags ← Rn − Op2        |
| CMN      | ``CMN Rn, Operand2``   | flags ← Rn + Op2        |
| TST      | ``TST Rn, Operand2``   | flags ← Rn & Op2        |
| TEQ      | ``TEQ Rn, Operand2``   | flags ← Rn ^ Op2        |

These four, together with the floating-point comparison ``FCMP``, are the
**only** instructions in the whole ISA that ever touch the CPSR flags.
That's worth stating plainly because it's easy to assume otherwise coming
from an architecture with an ``S`` suffix: ordinary ``ADD``, ``SUB``,
``AND`` and the rest never update the flags here, no matter how they're
written, and none of them write a result anywhere except their destination
register comparisons compute a result purely to inspect its flags, then
throw the result itself away.

#### Move

| Mnemonic | Syntax              | Operation         |
|----------|----------------------|--------------------|
| MOV      | ``MOV Rd, Operand2`` | Rd = Op2          |
| MVN      | ``MVN Rd, Operand2`` | Rd = ~Op2         |

A negative immediate on ``MOV`` follows the same rewriting rule as
arithmetic above: ``MOV R0, V-1`` becomes ``MVN R0, V0``, since moving a
negative number and moving the bitwise complement of its positive
counterpart land on the same bit pattern.

#### Shift pseudo-instructions

| Mnemonic | Syntax                              | Operation                |
|----------|---------------------------------------|-----------------------------|
| LSL      | ``LSL Rd, Rm, amount``              | Rd = Rm << amount        |
| LSR      | ``LSR Rd, Rm, amount``              | Rd = logical(Rm >> amount)    |
| ASR      | ``ASR Rd, Rm, amount``              | Rd = arithmetic(Rm >> amount) |
| ROR      | ``ROR Rd, Rm, amount``              | Rd = rotate_right(Rm, amount) |

All four also accept the shorter two-operand form:

    LSL R1, V2      # equivalent to LSL R1, R1, V2
    ROR R3, V0      # equivalent to ROR R3, R3, V0

``amount`` accepts any of the usual immediate spellings (``Vn``, ``VB...``,
a plain decimal literal, with or without a leading ``#``) and must fall
between 0 and 31 inclusive the shift-amount field genuinely has nowhere
to put a larger number.

### The LE register: the LEDs as an ordinary destination

``LE`` drives the board's ten red LEDs (``LEDR[9:0]``) directly, but from an
instruction's point of view it behaves like any other register: anything
that can write to a destination register can write to LE instead, and LE
can just as easily appear as a source operand feeding into some other
calculation.

As covered above, LE shares its bit-field encoding, **15**, with PC, and the
flag bit is what tells them apart flag = 0 means PC, flag = 1 means LE.
One detail worth knowing: when register 15 is read as a *source* (as ``Rn``
or inside ``Operand2``), what comes back is always the current LE value,
never the program counter reading the PC as a plain operand isn't a thing
this ISA supports.

Each of LE's ten low bits maps directly onto one LED: a 1 turns that LED
on, a 0 turns it off.

Examples::

    MOV LE, V10        # LE = 0b1010 → LEDR1 and LEDR3 on
    MOV LE, R0         # LE = R0
    ADD LE, R0, R1     # LE = R0 + R1
    SUB LE, LE, V1     # LE = LE − 1
    ADD R0, LE, R1     # R0 = LE + R1  (LE as first source)
    ADD R0, R1, LE     # R0 = R1 + LE  (LE as second source)
    AND LE, R0, V15    # LE = R0 & 15
    MOVNE LE, V1       # conditional: LE = 1 if NE
    CMP LE, V5         # compare LE with 5, set flags

Writing ``MOV PC, Rn`` is still a genuine branch (flag = 0) writing to LE
never has any effect on the program counter, and the two operations stay
completely independent despite sharing a register number.

### The HEX register: four seven-segment digits

``HEX`` drives the board's seven-segment displays. Exactly how many of them
are active depends on the address width the core was built with:

    NUM_NIBBLES = (ADDR_WIDTH + 3) / 4

With the default 16-bit address width, that works out to **four nibbles**
(HEX0–HEX3), and the remaining two displays, HEX4 and HEX5, simply stay
blank. Each nibble is decoded into its own hexadecimal digit, 0 through F.

HEX shares its bit-field encoding, **14**, with LR, and once again the flag
bit disambiguates: flag = 0 means LR, flag = 1 means HEX. The assembler
marks HEX automatically whenever it appears as ``Operand2``, so writing
``MOV R0, HEX`` or ``ADD R0, R1, HEX`` correctly reads the display
register rather than the link register. One asymmetry to keep in mind: the
``Rn`` field has no equivalent HEX marker, so HEX can only be read as
Operand2, never as the first source register of an instruction an
unmarked register-14 source in that position is always LR.

| Bits         | Display | Content                         |
|--------------|---------|-----------------------------------|
| [3:0]        | HEX0    | least-significant hex digit      |
| [7:4]        | HEX1    | second hex digit                 |
| [11:8]       | HEX2    | third hex digit                  |
| [15:12]      | HEX3    | most-significant hex digit       |

For example, ``MOV HEX, V255`` writes 0xFF, which appears on the displays
as ``00FF`` across HEX3:HEX2:HEX1:HEX0.

Examples::

    MOV HEX, V255      # displays "00FF"
    MOV HEX, R0        # HEX = R0
    ADD HEX, R0, R1    # HEX = R0 + R1
    MOVEQ HEX, V0      # conditional: HEX = 0 if EQ
    MOV R2, HEX        # read HEX through Operand2

### Memory operations

| Mnemonic       | Syntax                       | Operation                             |
|----------------|------------------------------|------------------------------------------|
| MOV (address)  | ``MOV Rd, variable``         | Rd = address of *variable*            |
| MOV (load)     | ``MOV Rd, [variable]``       | Rd = RAM[address of *variable*]       |
| MOV (reg-ind)  | ``MOV Rd, [Rn]``            | Rd = RAM[Rn]                          |
| MOVM (load)    | ``MOVM Rd, [variable]``      | Rd = little_endian_load(RAM, addr, N) |
| MOVM (reg-ind) | ``MOVM Rd, [Rn]``            | Rd = little_endian_load(RAM, Rn, N)   |
| SAVE (store)   | ``SAVE Rs, [variable]``      | RAM[address of *variable*] = Rs[7:0]  |
| SAVE (reg-ind) | ``SAVE Rs, [Rn]``           | RAM[Rn] = Rs[7:0]                     |
| SAVEM (store)  | ``SAVEM Rs, [variable]``     | little_endian_store(RAM, addr, Rs, N) |
| SAVEM (reg-ind)| ``SAVEM Rs, [Rn]``           | little_endian_store(RAM, Rn, Rs, N)   |

Both loads and stores accept register-indirect addressing (``[Rn]``), where
the address to access comes from a register rather than being written out
by name. The plain ``MOV``/``SAVE`` byte forms only ever move the low 8 bits
(``DATA_WIDTH``); a byte-sized load is zero-extended back up to the full
register width on the way in.

``MOVM``/``SAVEM`` move several bytes in a single instruction, transferring
``N = ceil(ADDR_WIDTH / DATA_WIDTH)`` bytes at a time 2 bytes on the
default 16-bit core, which is exactly enough to move a whole register's
worth of address in one go. Byte order is little-endian: the byte stored at
the lowest address ends up in bits ``[7:0]`` of the resulting register
value.

### Stack operations

| Mnemonic | Syntax           | Operation                                            |
|----------|------------------|----------------------------------------------------------|
| PUSH     | ``PUSH Rn``      | SP ← SP − N; little_endian_store(RAM, SP, Rn, N)     |
| POP      | ``POP Rd``       | Rd = little_endian_load(RAM, SP, N); SP ← SP + N     |
| PUSH     | ``PUSH {list}``  | one PUSH per listed register, highest register first |
| POP      | ``POP {list}``   | one POP per listed register, lowest register first   |

The stack grows *downward*: ``PUSH`` decrements the stack pointer before
writing (pre-decrement), and ``POP`` increments it after reading
(post-increment) the same convention most stack-based architectures use.

A stack slot is exactly one register wide: ``N = ceil(ADDR_WIDTH /
DATA_WIDTH)``, the identical transfer size ``MOVM``/``SAVEM`` use. Because a
slot is a whole register wide, ``PUSH LR`` preserves a complete return
address in one go, which is precisely what makes nested calls and
recursion work at all::

    my_routine:
        PUSH {R4-R6, LR}
        ...
        POP  {R4-R6, PC}       # restore and return; expands to four POPs

As mentioned earlier, SP starts out pointing at ``MMIO_BASE`` at reset
the very first address of the peripheral window precisely so that the
first pre-decrementing ``PUSH`` a program executes lands safely in normal
RAM instead of overwriting a peripheral register.

### Register lists: syntax sugar, not new hardware

``PUSH`` and ``POP`` both accept a braced list of registers, including
inclusive ``Rn-Rm`` ranges for example, ``PUSH {R4, R7-R9, LR}``. This is
purely an assembler convenience: the list is lowered into one ordinary
single-register instruction per element before it ever reaches the
encoder, so it costs no new opcode and needs no new hardware state at all.

The ordering follows ARM's convention for a reason: ``PUSH`` transfers its
registers in descending order, which leaves the lowest-numbered register
sitting at the lowest address in memory, and ``POP`` transfers in ascending
order, so that the very same list round-trips correctly no matter which
direction it's read in. Range endpoints must always be plain ``R``-numbered
registers, and naming the same register twice in one list is treated as an
outright error rather than silently transferring it twice.

### Vector, accumulator and tensor instructions a pointer, not the reference

These live on the memory-class escape, opcode ``0x0``, with the real
sub-opcode packed into the ``Rn`` field as described above. Eight 64-bit
vector registers, ``Q0``–``Q7``, each hold eight INT8 lanes; four 32-bit
accumulators, ``A0``–``A3``, hold reductions too wide for a 16-bit
register to survive:

| Mnemonic | Syntax | Operation |
|----------|--------|-----------|
| VLD      | ``VLD Qd, [Rn]``          | load eight bytes, lane 0 lowest |
| VST      | ``VST Qd, [Rn]``          | store eight bytes |
| VDOT     | ``VDOT Ad, Qn, Qm``       | ``Ad += Σ s8(Qn[i]) × s8(Qm[i])`` |
| VSUM     | ``VSUM Ad, Qn``           | ``Ad += Σ s8(Qn[i])`` |
| VMAXR    | ``VMAXR Rd, Qn``          | signed maximum lane into a register |
| VDUP     | ``VDUP Qd, Operand2``     | broadcast the low byte to every lane |
| VEXT     | ``VEXT Rd, Qn, lane``     | sign-extend one lane into a register |
| VINS     | ``VINS Qd, Rm, lane``     | write a register's low byte into a lane |
| ACLR     | ``ACLR Ad``               | ``Ad = 0`` |
| ASET     | ``ASET Ad, Operand2``     | ``Ad = sign_extend32(Op2)`` |
| AGET     | ``AGET Rd, An``           | ``Rd = An[15:0]`` |
| AGETS    | ``AGETS Rd, An``          | ``Rd = saturate_int16(An)`` |
| AQMUL    | ``AQMUL Ad, Operand2``    | multiply by a Q0.15 value, saturating |
| ARSHR    | ``ARSHR Ad, Operand2``    | ``RoundingDivideByPOT(Ad, n)`` |
| NPUCFG   | ``NPUCFG FIELD, Operand2``| write one tensor-engine configuration field |
| NPURUN   | ``NPURUN Rd``             | run the configured layer; ``Rd`` = result word |

``Q`` and ``A`` are reserved register namespaces, exactly the way ``R`` is:
a data symbol or a code label named ``Q3`` or ``A0`` is rejected at
assembly time rather than silently shadowing the register. Vector
registers were deliberately not named ``V0``–``V7``, since ``Vn`` is
already how immediates are written (``V5`` means the plain number 5, not a
register) reusing that letter for registers too would have made every
vector instruction ambiguous to read. [Quantized inference](tinyml.md)
explains what each of these instructions is actually for, how they cost
what they cost, and how they fit into a real quantized model.

### Memory-mapped I/O

Rather than invent new instructions for every peripheral, the top
``MMIO_WINDOW_BYTES`` (256) bytes of the address space simply decode to
peripheral registers instead of RAM, so any ordinary load or store already
reaches them. That matters more than it might sound: the extended
instruction class has all sixteen of its opcodes spoken for already, so
memory-mapped I/O is really the *only* way a new peripheral could be added
without redesigning the encoding.

With the default ``RAM_ADDR_WIDTH = 16``, this window sits at
``0xFF00``–``0xFFFF``:

| Address  | Name        | Access | Contents                                    |
|----------|-------------|--------|-----------------------------------------------|
| ``0xFF00`` | LED       | R/W    | Same register as ``LE``; bits [9:0] drive LEDR |
| ``0xFF04`` | HEX       | R/W    | Same register as ``HEX``; hexadecimal digits |
| ``0xFF08`` | KEYS      | R      | Pressed-key mask, bits [3:0] (active high), board or host |
| ``0xFF0C`` | CYCLES_LO | R      | Free-running cycle counter, low half         |
| ``0xFF10`` | CYCLES_HI | R      | Its high half                                |

A few things about this window are worth spelling out, because they're
easy to get wrong by assumption:

- LED and HEX here are the *exact same physical registers* that the
  ``LE``/``HEX`` operands reach not separate copies kept in sync.
  ``MOV LE, V5`` and a plain store to ``0xFF00`` are two different ways of
  looking at one underlying value, and a change made through either path
  is immediately visible through the other.
- Both byte-sized and full-register-width accesses work as expected: a
  plain ``SAVE`` writes one byte and merges it into the existing register
  value, while ``SAVEM`` overwrites the whole slot at once.
- KEYS and the two CYCLES registers are read-only: writing to them is
  silently ignored, and reading always returns their current live value.
  Any address in the window that isn't listed above simply ignores writes
  and reads back as zero.
- ``CYCLES`` counts real clock edges on actual hardware. Under the
  architectural (FAST) simulator, it counts something different
  instruction steps, including the halt word, plus a correction for
  virtual waits: each ``WAIT VN`` adds ``max(N, 1)`` beyond its own
  instruction step, and every pending ``WAITK`` poll adds one more. It is
  *not* a retired-instruction count, and under FAST it is not a timing
  measurement at all in the hardware sense.
- KEYS reports the union of the board's physical ``KEY[3:0]`` pins and
  whatever mask the host drives over the JTAG cable with
  ``scripts/board/jtag_keys.py`` useful when four buttons genuinely
  aren't enough and no PS/2 keyboard is close at hand. A program has no way
  to tell which source a given press came from. ``WAITK`` waits on that
  same combined mask, and ``WAITKNB`` polls it without blocking. See
  *Getting key presses without a keyboard* in
  [architecture](architecture.md) for how that merge actually works in
  hardware.

Example::

    const MMIO   = 0xFF00
    const KEYS   = MMIO + 8

        MOV R0, =KEYS
        MOVM R1, [R0]      # non-blocking key poll through the bus

### Branch instructions

| Mnemonic | Syntax       | Operation                                    |
|----------|--------------|-------------------------------------------------|
| B        | ``B label``  | PC = address of *label*                       |
| BL       | ``BL label`` | LR = PC (return address); PC = address of *label* |

Both carry the full 20-bit absolute target described earlier, rather than
the 12-bit immediate an ordinary instruction gets, precisely so that branch
targets can reach well past the first 4 KB that a 12-bit immediate would
allow.

Every condition suffix is valid on a branch, giving the familiar set:
``BEQ``, ``BNE``, ``BLT``, ``BGE``, ``BGT``, ``BLE``, ``BCS``, ``BCC``,
``BMI``, ``BPL``, ``BVS``, ``BVC``, ``BHI``, ``BLS``.

Returning from a subroutine is simply ``MOV PC, R14`` there's no separate
``RET`` instruction, since moving the link register into the program
counter already does exactly what's needed.

#### The branch class's other job: non-branching ALU instructions

Somewhat surprisingly, the branch class also carries a whole set of
instructions that don't branch anywhere at all they execute in strict
sequence like any ordinary arithmetic instruction, and simply happen to
live in this class because, as covered above, it had opcode space free when
they were added:

| Mnemonic | Syntax                       | Operation |
|----------|--------------------------------|-------------|
| ABS      | ``ABS Rd, Operand2``         | ``Rd = abs(Op2)`` |
| MAX      | ``MAX Rd, Rn, Operand2``     | ``Rd = max_signed(Rn, Op2)`` |
| MIN      | ``MIN Rd, Rn, Operand2``     | ``Rd = min_signed(Rn, Op2)`` |
| MADD     | ``MADD Rd, Rn, Operand2``    | ``Rd = Rd + (Rn * Op2)`` |
| PIXELNB  | ``PIXELNB Rd, Rn, Operand2`` | enqueue framebuffer write |
| WAITKNB  | ``WAITKNB Rd, Operand2``     | non-blocking selected key poll |
| QADD     | ``QADD Rd, Rn, Operand2``    | signed saturating add |
| QSUB     | ``QSUB Rd, Rn, Operand2``    | signed saturating subtract |
| SSAT     | ``SSAT Rd, Rn, Operand2``    | clamp to a signed field of ``Op2`` bits |
| USAT     | ``USAT Rd, Rn, Operand2``    | clamp to an unsigned field of ``Op2`` bits |
| QRDMULH  | ``QRDMULH Rd, Rn, Operand2`` | saturating rounding doubling high multiply |
| RSHR     | ``RSHR Rd, Rn, Operand2``    | shift right, rounding half away from zero |
| RELU     | ``RELU Rd, Rn, Operand2``    | clamp to ``[0, Op2]``; ``Op2 = 0`` means no ceiling |
| SXTB     | ``SXTB Rd, Operand2``        | sign-extend the low byte |

These are encoded as class ``11``, opcodes ``0x2``..``0xF``. ``QADD``
through ``SXTB`` are the quantized-inference set ``QRDMULH`` and
``RSHR`` in particular are this ISA's versions of gemmlowp's
``SaturatingRoundingDoublingHighMul`` and ``RoundingDivideByPOT``, the pair
of primitives that a TFLite requantization step lowers into, one apiece.
[Quantized inference](tinyml.md) is the full reference for why they behave
the way they do. A couple of smaller details worth knowing: ``MAX``/``MIN``
compare as signed two's-complement numbers, and ``ABS`` wraps rather than
saturates at the minimum signed value (on a 16-bit core, ``ABS(0x8000) =
0x8000``, not the value one might expect from a true absolute value).

### Extended instructions

#### WAIT

    WAIT VN

Stalls the whole pipeline for *N* milliseconds. The actual number of cycles
this takes is computed as ``N × CYCLES_PER_MS``, which the hardware derives
from its own effective clock frequency so the same source code produces
the same real-world delay regardless of clock configuration.

#### WAITK

    WAITK Rd, Operand2

Blocks until at least one *selected* key becomes pressed through either
the active-low physical ``KEY[3:0]`` pins or the active-high JTAG key mask
described in [architecture](architecture.md) and then writes a bitmask of
which selected keys were found pressed into ``Rd`` before continuing.

``Operand2`` is the selection mask (an immediate or a register), and only
its low four bits are used. A selection mask of zero is treated specially,
as meaning "any key" (``0xF``), rather than "no key" waiting for nothing
would otherwise be a trivially useless instruction. If more than one
selected key happens to be down at once, the returned mask simply has more
than one bit set.

#### WAITKNB

    WAITKNB Rd, Operand2

The non-blocking twin of ``WAITK``: it samples whichever selected keys are
pressed *right now*, writes that hit mask into ``Rd``, and always continues
immediately in the same instruction issue there is no waiting involved at
all, hence "NB" for non-blocking.

The mask in ``Operand2`` means exactly the same thing as it does for
``WAITK``. If none of the selected keys happen to be pressed at the moment
of the check, ``Rd`` simply receives zero. It's encoded as branch-class
opcode ``0x7`` (``BR_WAITKNB``).

#### MUL (scalar)

    MUL Rd, Rn, Operand2

Computes ``Rd = Rn × Op2``, unsigned, truncated down to ``ADDR_WIDTH``
bits. This lives in instruction class ``01`` under opcode ``0x1`` it
reads like ordinary arithmetic, but as mentioned above it is genuinely part
of the extended class rather than data processing.

#### DIV (scalar)

    DIV Rd, Rn, Operand2

Computes ``Rd = Rn / Op2`` using unsigned integer division, truncating
toward zero the way ordinary unsigned quotients do. Dividing by zero is
explicitly defined rather than left undefined: the result is simply 0.

The cost of this instruction genuinely depends on the data involved:
``divider_seq.sv`` implements a sequential radix-4 restoring divider, which
retires two quotient bits per iteration and skips over leading zero bits in
the numerator, so smaller numerators finish faster. ``FDIV`` shares this
exact same divider hardware. It's encoded under instruction class ``01``,
opcode ``0xF``.

#### Floating point: IEEE-754 binary16

Floating-point values here are always half-precision IEEE-754 binary16,
16 bits wide stored in the low half of an otherwise ordinary
general-purpose register.

Every arithmetic operation and ``FCMP`` treat subnormal inputs as if they
were signed zero, and any arithmetic result that underflows into the
subnormal range gets flushed to signed zero rather than kept as a genuine
subnormal. So, for instance, ``FADD`` of the payloads ``0x0001`` and
``0x0000`` returns ``0x0000``, and ``FCMP`` considers those two values
equal. ``FMOV`` is the one exception: it preserves the exact payload bits
of whatever it moves, subnormals included, since it isn't doing arithmetic
at all.

| Mnemonic | Syntax                      | Operation |
|----------|-------------------------------|-------------|
| FADD     | ``FADD Rd, Rn, Operand2``   | Rd = Rn + Op2 |
| FSUB     | ``FSUB Rd, Rn, Operand2``   | Rd = Rn - Op2 |
| FMUL     | ``FMUL Rd, Rn, Operand2``   | Rd = Rn * Op2 |
| FDIV     | ``FDIV Rd, Rn, Operand2``   | Rd = Rn / Op2 |
| FCMP     | ``FCMP Rn, Operand2``       | CPSR flags from FP compare |
| FMOV     | ``FMOV Rd, Operand2``       | Rd = Op2 (bitwise fp16 payload) |

``Operand2`` for any of the floating-point arithmetic instructions can be
either a register or a literal written with an ``F`` prefix (for example
``F1.5`` or ``F-0.25``). Those literals don't fit in the instruction word
directly, so the assembler materialises them into a deduplicated pool of
floating-point constants in data memory, and the instruction itself simply
carries a 12-bit address pointing into that pool which is also why
assembly fails outright if that pool ever grows past address ``0xFFF``;
there's nowhere left for the pointer to reach.

``FCMP`` sets the CPSR flags in a way that mirrors the integer comparisons:
for an ordered comparison, ``N`` means less-than, ``Z`` means equal, and
``C`` means greater-or-equal; for an *unordered* comparison meaning at
least one operand was NaN ``V`` is set instead, flagging that the other
three flags can't be trusted to mean anything.

The floating-point opcodes, for reference, are ``FADD=0x7``,
``FSUB=0x8``, ``FMUL=0x9``, ``FDIV=0xA``, ``FCMP=0xB``, ``FMOV=0xC``,
alongside ``TEXT=0xE`` and ``DIV=0xF`` which share the same extended class.

CPU flags
----------

As already stated above but worth repeating on its own, since it's easy to
assume otherwise: the CPSR flags are updated **only** by the comparison
instructions ``CMP``, ``CMN``, ``TST``, ``TEQ``, and the floating-point
``FCMP``. Every ordinary data-processing instruction, ``ADD`` and ``SUB``
and ``MOV`` included, leaves the flags exactly as it found them.

- **N (Negative)** is set whenever the result's most significant bit is 1.
- **Z (Zero)** is set whenever the result is exactly zero.
- **C (Carry)** is set when an addition produces a carry out of the top
  bit, or when a subtraction produces *no* borrow.
- **V (Overflow)** is set when the result overflows as a signed value.

A small worked example makes the distinction between "computing" and
"comparing" concrete::

    MOV R0, V200
    MOV R1, V100
    SUB R2, R0, R1    # R2 = 100, flags unchanged
    CMP R2, R1        # 100 − 100, N=0 Z=1 C=1 V=0

Notice that the ``SUB`` above computes 100 into R2 but leaves the flags
completely untouched it's only the ``CMP`` on the next line, which
throws its own result away and keeps only the flags, that actually updates
CPSR.
