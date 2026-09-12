Quantized Inference: Scalar Ops, Vector ISA and the Tensor Engine
=================================================================

What got added, and why it needed three different pieces
-------------------------------------------------------------

This document is the canonical reference for everything the CPU gained in
order to run quantized neural-network inference a term that just means
running a neural network whose numbers have already been squeezed down from
the 32-bit floats they were trained with into 8-bit integers, small enough
that ordinary embedded hardware can multiply and add them cheaply. Three
things were added to make that fast: eight new branch-class scalar
operations, a whole new vector register file with its own instruction
class, and a tensor engine that can execute an entire neural-network layer
convolution, pooling, whatever the layer is starting from a single
instruction.

These three pieces exist at three deliberately different levels of how
tightly they're wired into the hardware, and comparing them side by side is
really the point of building all three rather than just the fastest one:

| Level | Where it lives | Granularity | What it costs |
|-------|-----------------|-------------|------------------|
| Scalar quantization ops | Branch class, one cycle | one value | 8 opcodes |
| Vector ISA | Memory-class escape, 1–9 cycles | eight INT8 lanes | 1 opcode, 8×64-bit + 4×32-bit of state |
| Tensor engine | `hdl/npu.sv`, blocking | a whole layer | one FSM, a 512-entry window cache |

Measured on an identical 640-MAC layer (`programs/tinyml_bench.de1`, run on
the cycle-accurate RTL simulator so the comparison is a real hardware
timing measurement, not a simulator artifact), the three levels land here:

| Implementation | Cycles | Cycles/MAC | Speedup |
|----------------|--------|------------|-----------|
| Scalar `MADD` loop | 7790 | 12.2 | 1.0× |
| Eight-lane `VDOT` loop | 2040 | 3.19 | 3.8× |
| One `NPURUN` | 928 | 1.45 | 8.4× |

Each step up the table trades a little generality for a large speedup, and
later sections explain exactly where each speedup comes from and why the
tensor engine still can't quite reach one cycle per multiply-accumulate no
matter how it's built.

### Why the instruction encoding ended up looking the way it does

None of this could simply be bolted on as new opcodes, because there
weren't any left. By the time this extension was designed, the
data-processing and extended instruction classes had all sixteen of their
four-bit opcodes already assigned to something. Before the extension, the
memory class only used opcodes ``0xA``–``0xF`` and the branch class only
used ``0x0``–``0x7`` which meant exactly two places in the whole
encoding still had room, and both of them ended up used:

- the eight free **branch-class** opcodes became the new scalar
  operations, which is a natural fit ``ABS``, ``MAX``, ``MIN`` and
  ``MADD`` already lived in that class as its established home for
  arithmetic that doesn't redirect the program counter;
- the one free **memory-class** opcode, ``0x0``, became an *escape*: rather
  than meaning one instruction, it tells the decoder that the real
  operation is named by a sub-opcode hiding in the ``Rn`` field instead.
  That one trick turns what would have been one wasted opcode into room
  for sixteen new instructions the same idea RISC-V uses for its
  ``custom-0`` space and ARM uses for its coprocessor instructions, and it
  leaves room for this extension to keep growing without needing another
  redesign.

Vector registers are named ``Q0``–``Q7`` rather than the perhaps more
obvious ``V0``–``V7``, for a very concrete reason: ``Vn`` is already how
this ISA writes an immediate number (``V5`` means the plain number five,
not a register), so reusing that letter for registers too would have made
every vector instruction ambiguous to read. ``Q`` follows ARM NEON's
convention instead and collides with nothing already in use. Accumulators
are named ``A0``–``A3``. Both of these namespaces are reserved the same way
``R`` already is a data symbol or label named ``Q3`` or ``A0`` is
rejected outright at assembly time, rather than silently shadowing the
register.

The accumulator file is kept entirely separate from the general-purpose
register file because of a very specific overflow problem: on a 16-bit
core, a long reduction simply doesn't fit. A 64-term INT8 dot product can
reach roughly 2²⁰, while ``MADD`` accumulating into an ordinary
register wraps back around to zero at 2¹⁶. ``VDOT`` instead accumulates
into a full 32 bits, and ``AGETS`` is the instruction that brings a value
back down to something a 16-bit register can hold, saturating rather than
wrapping if it's still too big.

One more design choice worth explaining rather than just stating: the
tensor engine is configured through ordinary instructions
(``NPUCFG``), not through memory-mapped I/O. Routing configuration through
MMIO instead would have needed no new opcode at all, which sounds
appealing but every single configuration write would then cost a
two-cycle store instead of one cycle, and worse, the whole configuration
file would have to be threaded as roughly 350 wires between three separate
modules. Keeping configuration behind one instruction, ``NPUCFG``, keeps
all of that state in one place at the cost of a single sub-opcode.

Branch-class scalar operations
----------------------------------

These eight instructions are encoded as class ``11``, opcodes
``0x8``–``0xF``. Every one of them accepts a condition suffix and the usual
two-operand shorthand (``QADD R0, V5`` means exactly the same thing as
``QADD R0, R0, V5``), and none of them ever redirect the program counter
they're ordinary sequential arithmetic, just quantization-flavoured
arithmetic:

| Mnemonic | Syntax | Operation |
|----------|--------|-------------|
| `QADD` | `QADD Rd, Rn, Operand2` | signed saturating add |
| `QSUB` | `QSUB Rd, Rn, Operand2` | signed saturating subtract |
| `SSAT` | `SSAT Rd, Rn, Operand2` | clamp to a signed field of *Operand2* bits |
| `USAT` | `USAT Rd, Rn, Operand2` | clamp to an unsigned field of *Operand2* bits |
| `QRDMULH` | `QRDMULH Rd, Rn, Operand2` | saturating rounding doubling high multiply |
| `RSHR` | `RSHR Rd, Rn, Operand2` | arithmetic shift right, rounding half away from zero |
| `RELU` | `RELU Rd, Rn, Operand2` | clamp to `[0, Operand2]` |
| `SXTB` | `SXTB Rd, Operand2` | sign-extend the low byte |

A few of these deserve more explanation than the table can give:

- **`QRDMULH` and `RSHR` are gemmlowp's `SaturatingRoundingDoublingHighMul`
  and `RoundingDivideByPOT`** the two arithmetic primitives that TFLite
  Micro's own `MultiplyByQuantizedMultiplier` is built out of. In practice,
  ``QRDMULH Rd, Rn, M`` computes ``round(Rn × M / 2¹⁵)``, treating ``M`` as
  a Q0.15 fixed-point multiplier the fractional-bit convention where all
  fifteen bits after the implicit point are fraction. That's a real, and
  deliberate, precision reduction next to the Q0.31 multiplier TFLite
  itself stores on a 32-bit host; it belongs in a proper evaluation of the
  design's accuracy, not buried as a footnote, which is why the
  [quantization model](#quantization-model) section below discusses exactly
  what it costs.
- **`RELU`'s ceiling of zero doesn't mean "clamp to zero"; it means "no
  ceiling at all."** A ceiling that was literally zero would only ever be
  useful as a way to force the output to zero, which is a constant anyone
  could get another way so that encoding is repurposed instead, and it's
  what lets ``RELU Rd, Rn, V0`` mean plain ReLU while ``RELU Rd, Rn, V6``
  means ReLU6, both in exactly one cycle.
- **`SXTB` exists because plain byte loads always zero-extend.** A stored
  INT8 weight of ``-56`` reads back from memory as ``200`` if nothing
  corrects it, since the load has no way to know the byte was meant to be
  signed. Before this instruction existed, fixing that up cost two separate
  instructions, ``LSL #8`` followed by ``ASR #8``; now it's one.
- **`SSAT Rd, Rn, V0` is the identity operation, not a clamp to nothing.**
  The same holds for any width at or above the register's own width the
  clamp simply has nothing left to do. That makes it safe to compute a
  clamp width at runtime and feed it straight into `SSAT` without special-
  casing zero or "no clamp needed" separately.
- A negative immediate on `QADD` or `QSUB` gets rewritten by the assembler
  into the other mnemonic, exactly the way plain `ADD`/`SUB` already do
  and it's exact here too, since both saturate identically regardless of
  which direction the arithmetic came from.

Vector and accumulator instructions
----------------------------------------

These live on the memory-class escape class ``10``, opcode ``0x0``, with
the real sub-opcode packed into ``Rn``:

    [31:28]  Condition
    [27:26]  10 (memory class)
    [25]     Immediate flag
    [24:21]  0000 (MEM_NPU escape)
    [20]     Flag the configuration index's top bit for NPUCFG, else unused
    [19:16]  Sub-opcode (npu_op_t)
    [15:12]  Primary selector: Qd, Ad or Rd depending on the sub-opcode
    [11:0]   Operand2, packed per sub-opcode

The state behind these instructions is eight 64-bit vector registers,
``Q0``–``Q7``, each holding **eight INT8 lanes with lane 0 in the low
byte** so ``Q0``'s low byte is the first number in whatever eight-value
group it holds, and the highest byte is the eighth plus four 32-bit
signed accumulators, ``A0``–``A3``. Both register files show up in
simulator snapshots right alongside the ordinary general-purpose
registers, so nothing about their state is hidden during debugging.

| Mnemonic | Syntax | Operation | Cycles |
|----------|--------|-------------|----------|
| `VLD` | `VLD Qd, [Rn]` / `VLD Qd, [buffer]` | load eight bytes, lane 0 lowest | 9 |
| `VST` | `VST Qd, [Rn]` | store eight bytes | 9 |
| `VDOT` | `VDOT Ad, Qn, Qm` | `Ad += Σ s8(Qn[i]) × s8(Qm[i])` | 1 |
| `VSUM` | `VSUM Ad, Qn` | `Ad += Σ s8(Qn[i])` | 1 |
| `VMAXR` | `VMAXR Rd, Qn` | signed maximum lane into a register | 1 |
| `VDUP` | `VDUP Qd, Operand2` | broadcast the low byte to every lane | 1 |
| `VEXT` | `VEXT Rd, Qn, lane` | sign-extend one lane into a register | 1 |
| `VINS` | `VINS Qd, Rm, lane` | write a register's low byte into one lane | 1 |
| `ACLR` | `ACLR Ad` | `Ad = 0` | 1 |
| `ASET` | `ASET Ad, Operand2` | `Ad = sign_extend32(Operand2)` | 1 |
| `AGET` | `AGET Rd, An` | `Rd = An[15:0]` | 1 |
| `AGETS` | `AGETS Rd, An` | `Rd = saturate_int16(An)` | 1 |
| `AQMUL` | `AQMUL Ad, Operand2` | multiply by a Q0.15 value, round to nearest, saturating | 1 |
| `ARSHR` | `ARSHR Ad, Operand2` | `RoundingDivideByPOT(Ad, n)` | 1 |
| `NPUCFG` | `NPUCFG FIELD, Operand2` | write one engine configuration field | 1 |
| `NPURUN` | `NPURUN Rd` | run the configured layer; `Rd` = result word | data-dependent |

Notice that ``VLD``/``VST`` cost 9 cycles one per byte, since they move
eight bytes plus one for issuing the instruction while every other
vector or accumulator operation costs exactly 1. That gap is the whole
reason the vector loop in the benchmark table above only reaches 3.19
cycles/MAC rather than something closer to 1: every dot product needs its
two operand vectors loaded first, and those loads dominate the cost.

`VSUM` is there to support a correction software sometimes needs: when a
model uses asymmetric weights (weights with a nonzero zero-point), the true
dot product has to be corrected by ``weight_zero_point × Σ activations``,
and ``VSUM`` is what computes that sum efficiently. The tensor engine
itself never needs this correction, because it requires a weight zero
point of exactly zero by contract see
[Quantization Model](#quantization-model) below for why.

``AQMUL`` is worth a second look because it behaves slightly differently
from the engine's own multiplier field: it reads its multiplier as
**signed**, whereas the engine's always-positive ``MULT`` field cannot be
negative. In practice a Q0.15 multiplier is almost never small enough to
fit in the 12-bit immediate field, so it normally has to be built in a
register first and then used like this:

```
    MOV R0, =26214        # 0.8 in Q0.15
    AQMUL A0, R0
    ARSHR A0, V4
    AGETS R1, A0
    SSAT  R1, R1, V8      # the INT8 the next layer consumes
```

That short sequence is a complete, self-contained requantization: multiply
the accumulator by a fractional scale, round-and-shift it back down,
narrow it to 16 bits with saturation, and finally clamp it to the INT8
range the next layer expects to read.

The tensor engine
---------------------

`hdl/npu.sv` is the module that runs an entire layer from one instruction.
Convolution, depthwise convolution, and pooling all share one window cache
and one output pipeline; table lookup and argmax instead run their own
simple linear scans inside the same overall state machine.

### The six modes

| `MODE` | Constant | Reduction | Weights |
|--------|-----------|-------------|-----------|
| 0 | `NPU_CONV` | over `k_h × k_w × in_c` | `[out_c][k_h][k_w][in_c]` |
| 1 | `NPU_DEPTHWISE` | over `k_h × k_w`, channel by channel | `[k_h][k_w][channels]` |
| 2 | `NPU_MAXPOOL` | maximum over the window | none |
| 3 | `NPU_AVGPOOL` | sum over the window | none |
| 4 | `NPU_LUT` | element-wise table lookup | none |
| 5 | `NPU_ARGMAX` | index of the largest signed byte | none |

Two of these modes are worth a closer look, because what they *don't* need
is as important as what they do:

**A fully connected layer is just `NPU_CONV` with a 1×1 kernel over a
1×1×C input** there's no separate "dense layer" mode at all, because none
is needed. TFLite already stores its dense weights output-channel-major,
which happens to be exactly the layout a 1×1 convolution already expects,
so the data needs no repacking to be reinterpreted this way.

**Average pooling has no divider in hardware.** Rather than build one, it's
computed as a sum that gets requantized by ``1/count`` afterward: set
``MULT`` to ``round(32768 / count)`` 8192 for a 2×2 window, 3641 for a
3×3 one. Padding is excluded from the sum itself, but the multiplier is
fixed for the whole run, so windows sitting on the border with fewer valid
elements than a full window are *not* automatically renormalized for
having fewer real inputs the exporter has to supply the right multiplier
explicitly rather than assume one.

Pooling in general operates on the raw signed input bytes and ignores
``IN_ZP`` entirely. To keep the input's original scale and zero point
intact through a pooling layer, set ``OUT_ZP = 0`` (and, for max pooling
specifically, ``MULT = 0`` and ``SHIFT = 0`` too) otherwise the stored
zero point would effectively get added a second time on the way out.
Depthwise convolution, meanwhile, only supports the common case of one
output channel per input channel (``OUT_C = IN_C``, depth multiplier of 1).

### The configuration file

Every field below is written the same way, with a mnemonic field name
rather than a bare number: ``NPUCFG FIELD, Operand2``. Fields persist
across runs rather than resetting automatically, so chaining several
layers only ever needs to rewrite whatever actually changed between them;
every field's own reset value, before anything is written, is zero.

| Field | Meaning |
|-------|-----------|
| `MODE` | one of the six modes above |
| `FLAGS` | `NPU_ACC_IN`, `NPU_ACC_OUT`, `NPU_NO_BIAS` |
| `IN_BASE`, `IN_W`, `IN_H`, `IN_C` | input tensor, NHWC |
| `W_BASE` | weight base |
| `B_BASE` | bias base, INT32 little-endian, one per output channel |
| `OUT_BASE`, `OUT_W`, `OUT_H`, `OUT_C` | output tensor, NHWC |
| `K_W`, `K_H` | kernel width and height |
| `STRIDE` | x in bits [7:0], y in bits [15:8] |
| `PAD` | x in bits [7:0], y in bits [15:8] |
| `IN_ZP` | signed INT8 input zero point, subtracted for convolution/depthwise; ignored by pooling, LUT and argmax |
| `OUT_ZP` | output zero point, added after requantization |
| `MULT` | unsigned 16-bit multiplier with 15 fractional bits (`MULT / 32768`); **zero means "skip the multiply"** |
| `SHIFT` | rounding right shift applied after `MULT`; low five bits, 0..31 |
| `ACT_MIN`, `ACT_MAX` | activation clamp, signed bytes |
| `ACC_BASE` | INT32 partial-accumulator buffer |
| `LUT_BASE` | 256-entry table for `NPU_LUT` |

Two of these conventions are easy to get backwards, so they're worth
calling out on their own before they cause a confusing bug:

- **`MULT = 0` means "skip the multiply entirely,"** not "multiply by
  zero." Since the engine's fields all reset to zero, this makes an
  unconfigured scale behave as the identity rather than silently zeroing
  every output which matters because it's exactly the state a layer is
  in before anyone has calibrated its scale at all.
- **`ACT_MIN == ACT_MAX` means the *full* INT8 range, unclamped**, not "clamp
  everything to this one value." Since both fields reset to zero, they'd
  otherwise start out equal by default and a layer that clamped every
  single output to one constant would be a meaningless layer anyway, so
  that equal case is repurposed to mean "no clamp" instead of wasting the
  encoding on something useless.

### How a layer's output actually gets produced

Convolution, depthwise convolution, and pooling all end their computation
by pushing the raw accumulator through the same fixed pipeline:

    acc  ->  x (MULT / 32768), round to nearest
         ->  RoundingDivideByPOT(SHIFT)
         ->  + OUT_ZP
         ->  clamp to [ACT_MIN, ACT_MAX]
         ->  one INT8 byte at OUT_BASE + index

Setting ``NPU_ACC_OUT`` diverts this: instead of running through
requantization at all, the raw 32-bit accumulator is written straight to
``ACC_BASE``, which is how multi-pass reductions (below) hand a partial
sum from one pass to the next.

The two remaining modes skip this pipeline entirely, because neither one
produces a requantized value in the first place: ``NPU_LUT`` simply copies
``table[input_byte]`` to each output byte, treating the input as an
*unsigned* byte index into the table, and ignores both requantization and
the accumulator flags. ``NPU_ARGMAX`` writes no output tensor at all it
returns the index of the first byte with the greatest signed value. Both of
these scan ``OUT_W × OUT_H × OUT_C`` input bytes directly and bypass the
window cache completely, since neither one needs a sliding window.

### When a reduction is bigger than the window cache can hold

The engine caches an entire reduction window in a 512-entry buffer
(``NPU_PATCH_DEPTH``), which is what lets it stream weight bytes at full
speed without re-reading the activation window from RAM for every output
channel. That cache has a real limit, though: ``K_H × K_W × IN_C`` for
convolution, or ``K_H × K_W`` for depthwise and pooling. A window bigger
than that returns ``NPU_ERR_PATCH`` rather than silently computing a wrong
answer over a truncated window. LUT and argmax have no such limit, since
they never use the window cache at all.

Convolution and depthwise reductions that genuinely need a bigger window
can still be computed correctly, just in more than one pass, chained
through the INT32 side buffer:

```
    NPUCFG FLAGS, V(NPU_ACC_OUT)                # first chunk: bias + partial sum
    NPURUN R1
    ...advance IN_BASE and W_BASE...
    NPUCFG FLAGS, V(NPU_ACC_IN)                 # last chunk: seed and requantize
    NPURUN R1
```

The key detail that makes this safe rather than silently double-counting
the bias: ``NPU_ACC_IN`` seeds the accumulator from ``ACC_BASE`` **instead
of** ``B_BASE`` it never adds the bias a second time. A bias-free layer
should set ``NPU_NO_BIAS`` on the *first* pass only; every pass in between
the first and last should combine both flags,
``NPU_ACC_IN | NPU_ACC_OUT``. Every pass in a chain like this has to agree
on dimensions and tensor/weight layout simply moving the base addresses
forward does not, on its own, correctly repack channel slices out of a
general NHWC convolution, so this technique only works when the underlying
math genuinely does split into independent partial sums. Pooling, notably,
ignores ``NPU_ACC_IN`` altogether, so this chaining scheme doesn't extend
to pooling layers.

### What NPURUN hands back

``NPURUN Rd`` always writes a result word, and what it means depends on
which mode just ran:

| Value | Meaning |
|-------|-----------|
| `OUT_BASE` | success, for every mode but argmax |
| the index | success, for `NPU_ARGMAX` |
| `NPU_ERR_SHAPE` (1) | zero output dimension; also zero kernel extent for window modes or zero `IN_C` for convolution |
| `NPU_ERR_PATCH` (2) | the reduction exceeds `NPU_PATCH_DEPTH` |

For every mode that returns ``OUT_BASE``, values 1 and 2 happen to collide
with the two error codes but this isn't actually ambiguous in practice,
because the assembler never allocates a real buffer at address 1 or 2;
ordinary buffers start at address 4 or later, so a genuine success value
never looks like an error code. Argmax is the one mode where this
protection doesn't apply: indices 1 and 2 are perfectly valid results
there, so the return word alone genuinely cannot tell a real answer of "1"
apart from an error a program using argmax has to validate its
configured shape itself before trusting the result.

Cost model
-------------

Unlike a black-box accelerator, this engine's timing is fully analytic
worked out from first principles rather than only measured which is
exactly what makes it usable for a real design study rather than just a
demo. Per output pixel, the cost breaks down into four pieces:

- **window load** 3 cycles for every element genuinely inside the input
  bounds, only 1 cycle for every padded (out-of-bounds) element, since a
  padded element needs no real memory access;
- **accumulator seed** 1 cycle if ``NPU_NO_BIAS`` is set, since that
  skips the bias fetch (though not the pipeline state itself), or roughly
  9 cycles otherwise, to fetch the four bias bytes;
- **multiply-accumulate** ``2 + window_length`` cycles, streaming one
  weight byte per cycle once it gets going;
- **output** roughly 3 cycles to push the result through requantization
  and write it out.

For ``NPU_CONV`` specifically, the input window only has to be loaded once
and is then reused for every output channel, which is where a large part
of the engine's speed advantage actually comes from. Working through the
640-MAC benchmark by hand: loading the window costs roughly ``64×3``
cycles, and then each of the ten output channels costs about
``2 + 64 + 3`` cycles for its own multiply-accumulate and output a total
of roughly ``64×3 + 10×(2 + 64 + 3) = 882`` cycles, plus whatever
configuration writes and FSM overhead sit around the edges. That
back-of-envelope number lines up closely with the 928 cycles actually
measured. Depthwise convolution and pooling can't share the window this
way and have to reload it once per channel; depthwise also reads a genuine
weight per element, where pooling reads no weights and does no
multiply-accumulates at all. LUT and argmax, as already noted, use their
own separate linear scans instead of any of this.

**The real floor on speed is one byte per cycle, and that floor is set by
the memory, not the multiplier.** The data RAM has a single 8-bit
synchronous read port full stop, regardless of how the multiplier
itself is built. The tensor engine gets close to that floor, at roughly 1
cycle per MAC, only because caching the reduction window makes the
activation data resident and frees the memory port to stream weight bytes
continuously. The eight-lane ``VDOT`` loop cannot do the same trick: eight
vector registers simply aren't enough room to hold both operands of a long
reduction at once, so it has to pay for two vector loads per dot product,
which is exactly why it lands at 3.2 cycles/MAC instead of something
closer to 1. Widening that single memory port is the one hardware change
that would actually move this ceiling and it's the obvious next
experiment for anyone picking this design back up.

Quantization model
----------------------

The engine supports asymmetric INT8 activations together with symmetric
INT8 weights, and a single scale shared across an entire layer. TFLite's
own INT8 specification also allows *per-channel* weight scales for
convolution and depthwise convolution, and those cannot be copied into this
engine directly anyone converting a real TFLite model needs to be aware
of that gap; see the
[official quantization specification](https://developers.google.com/edge/litert/conversion/tensorflow/quantization/quantization_spec)
for what TFLite itself guarantees.

Two limitations in particular follow from how the scale is represented in
hardware:

1. **The multiplier has 15 fractional bits rather than TFLite's 31** 16
   fewer bits of fractional precision, or roughly 4.8 fewer decimal digits
   of precision in the fraction. The engine reads its ``MULT`` field as
   unsigned, while the two related instructions, ``QRDMULH`` and
   ``AQMUL``, read their multipliers as signed Q0.15 values instead.
2. **Per-channel quantization has no representation at all.** There's
   exactly one multiplier per layer here, so a model quantized per-channel
   has to be requantized to a single per-tensor scale before it can run on
   this engine.

The weight zero point is assumed to be exactly zero throughout, matching
the signed INT8 weight contract this engine expects. For convolution and
depthwise convolution, ``IN_ZP`` is subtracted as the window is read in,
so the engine directly computes ``bias + Σ (a − za)w`` no separate
correction step is needed for the activation side. It's worth working
through why the weight side needs no correction at all: expanding the fully
general asymmetric product gives

    Σ (a − za)(w − zw) = Σ a·w − za Σ w − zw Σ a + N·za·zw

and setting ``zw = 0`` the engine's own assumption makes both terms
that depend on the weight zero point vanish entirely. The one term that
survives, ``−za Σ w``, is exactly the correction the engine already
performs by subtracting ``IN_ZP`` from the window as it reads it; folding
that same correction into the bias as well would double-count it. Software
that instead uses ``VDOT`` directly on raw bytes doesn't get this
correction for free and has to apply its own zero-point correction by
hand which is exactly the case ``VSUM`` exists to help with, for a
nonzero weight zero point.

Turning a trained model into a program
-------------------------------------------

`scripts/ml/tinyml_export.py` sits in front of the assembler rather than
inside it it's a separate compilation step, not part of the encoder
itself. It reads a JSON description of a model that has *already* been
quantized to INT8, lays its tensors out in the ``space:`` data section, and
emits one ``NPUCFG``/``NPURUN`` block per layer. Supported layer types are
``conv2d``, ``depthwise_conv2d``, ``fully_connected``, ``max_pool_2d``,
``average_pool_2d``, ``lut`` and ``argmax``.

```powershell
uv run python scripts/ml/tinyml_export.py scripts/models/digits8x8/model.json -o programs/tinyml_digits.de1
```

It's worth being precise about what this script does *not* do: the JSON it
reads has to already use this engine's supported shapes and its particular
quantization parameter format the exporter does not convert a
TFLite model's floating-point scales into this engine's fixed-point
``MULT``/``SHIFT`` pair, and it does not repack TFLite's per-channel
weights into the single per-layer scale this engine requires. Reading an
actual ``.tflite`` FlatBuffer and adapting its quantization into this
JSON format is a separate conversion step that isn't supplied in this
repository at all the script's own docstring documents exactly which
JSON fields it expects, once a model has already been through that
conversion.

``programs/tinyml_digits.de1`` is the committed output of running this
exporter against ``scripts/models/digits8x8/model.json``, and
``tests/test_tinyml_programs.py`` regenerates it from the same model and
compares the two on every test run so the checked-in program and the
model it was built from can never quietly drift apart.

The programs that demonstrate all this
--------------------------------------------

- **`programs/tinyml_digits.de1`** generated straight from
  `scripts/models/digits8x8/model.json`. It holds ten 8×8 stencils, each
  pixel either +1 or −1, as one INT8 fully-connected layer. Because both
  input and stencil are ±1, the dot product between them works out to
  ``64 − 2 × hamming_distance``, so picking the largest dot product (via
  argmax) is exactly the same as picking the *closest* stencil by Hamming
  distance a small, self-contained piece of reasoning worth having in
  mind when reading the program. The committed sample input is digit 3
  with two pixels deliberately flipped, and the predicted class ends up on
  both HEX and LEDR. `tests/test_tinyml_programs.py` regenerates the whole
  program from the model and compares it, so program and model can never
  drift apart.
- **`programs/tinyml_bench.de1`** the very same 640-MAC layer, computed
  three separate ways (scalar, vector, tensor engine) and timed using the
  `CYCLES` MMIO counter, with a check that all three land on the exact same
  answer byte for byte. Only the RTL engine actually counts real clock
  edges; the architectural simulator instead counts instruction steps and
  virtual waits, so the speed comparison in the table at the top of this
  document is only meaningful when run under `run_snapshot`, the
  cycle-accurate path.
- **`programs/tinyml_vga_digits.de1`** the visible demo version. For each
  of the ten digits, it rebuilds that digit's stencil, flips a
  deterministic pseudo-random selection of its pixels, classifies the
  noisy result, and draws both the noisy input and the recognised stencil
  side by side on the framebuffer green if the classification was
  correct, red if it wasn't. Ten such cells fill the whole screen, and once
  the program halts, the framebuffer simply keeps showing the finished
  result.

  Its 640-byte stencil table lives in
  `programs/data/digits8x8_weights.de1` and is pulled in at assembly time
  with a plain `include`; that included file opens the data section, and
  the demo program itself adds its bias and working buffers immediately
  after it. The test suite resolves that include and checks the table
  against the JSON model directly, so moving where the table's source text
  lives never changes a RAM address or requires a separate MIF file.

  The noise generator is a 16-bit xorshift with shift amounts (7, 9, 8),
  seeded with the fixed constant `0x27EF` a full-period generator (all
  65535 nonzero states), built from three `EOR`s and three shifts. Using a
  constant seed is a deliberate choice, not an oversight: a demo whose
  displayed images changed on every single reset could never be regression
  tested at all, and this one is the test suite reimplements the exact
  same generator in Python and checks the last sample it produces byte for
  byte against the hardware.

  The amount of noise the demo tolerates is a property of the *model*, not
  of the hardware. The ten stencils sit as close as 3 pixels apart from
  each other at their nearest (digits 6 and 8, and separately 8 and 9), so
  a flip probability of 1 in 16 was chosen deliberately: with the fixed
  seed above, every digit ends up with somewhere between 4 and 10 flipped
  pixels, and every single one of the ten still classifies correctly, with
  a minimum margin of 6 points over its nearest runner-up. Making the demo
  tolerate more noise than that would require stencils that are further
  apart to begin with a change to the model, not to the engine.

Limits worth knowing before they surprise you
---------------------------------------------------

- Convolution is bounded by `K_H × K_W × IN_C ≤ 512`; depthwise and pooling
  by `K_H × K_W ≤ 512`. Reductions that genuinely need to be bigger can
  still be computed correctly by chaining passes through `ACC_BASE`, as
  described above.
- Tensor dimensions are 16-bit values, and the entire address space is only
  64 KB weights, activations, and every intermediate buffer a model
  needs all have to share that space with the program itself.
- The engine blocks the whole CPU core for its entire run. There is no
  interrupt it can raise and no way to poll it partway through which is
  precisely the trade that lets it own the RAM port outright with no
  arbiter needed, as [architecture](architecture.md) explains.
- Vector loads and stores tolerate unaligned addresses, but always move
  exactly eight bytes there's no narrower vector transfer.
- The output multiplier is fixed per layer, with 15 fractional bits, and
  pooling in particular has no automatic adjustment for border windows
  that have fewer valid elements than a full window would.
