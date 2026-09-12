Toolchain and Simulation
========================

Getting from a `.de1` file to something the CPU can run
-------------------------------------------------------------

Nothing about the assembly programs this project ships with is hand-encoded
into binary a Python program, referred to throughout as the *encoder*,
does that translation. It lives in the ``src/cpu/encoder`` package and runs
from the project root as::

    python -m src.cpu.encoder.main <input_file.de1>

Running it produces ``src/cpu/encoder/out/<input_file>.bin`` and logs the
symbol table, the memory layout it computed, and every encoded instruction
at INFO level, so a build can be inspected after the fact without rerunning
anything. That logging is deliberate rather than incidental: the individual
pipeline stages only ever log, and nothing on the library import path
prints directly to standard output. That matters because the exact same
code that assembles a program from the command line,
``src/cpu/encoder/assemble.py``, is also what the simulator and the editor
analyzer import and call directly if a stage printed to stdout, it would
corrupt whatever structured output those other callers are trying to
produce. There is exactly one two-pass assembler implementation in this
whole project; the CLI and ``src/cpu/simulation/runner.py`` both assemble
through that same module rather than each keeping their own copy.

### The pipeline, stage by stage

::

    ┌──────────┐  include/const  ┌────────────┐   strip   ┌──────────┐
    │  .de1    │─────────────────│ directives │──comments─│  parser  │
    └──────────┘                 └────────────┘           └──────────┘
                                                                │
    ┌──────────┐   normalise   ┌──────────┐   sections/data         │
    │ prettify │<──────────────│  memory  │<────────────────────────┘
    └──────────┘               └──────────┘
          │
          │  encode   ┌──────────┐            ┌──────────────┐
          └──────────>│ encoder  │───────────>│  binary .bin │
                      └──────────┘            └──────────────┘

Reading this left to right rather than as a diagram: a source file first
passes through **directives**, which splice in every ``include`` and fold
every ``const`` declaration into a lookup table by the time this stage
finishes, everything downstream only ever sees plain instructions and data
declarations, never a directive. Next, **parse** strips out comments and
splits the file into its ``space:`` and code sections. **Memory** then lays
out the entire data section in one single pass: first the ``space:``
declarations themselves (binary values, float literals, strings, matrices,
in that order), and then whatever additional data blobs the code implies
``TEXT`` strings, inline matrix literals and the result buffers they'll
need, and inline float literals. The result of this stage is a
``DataSection`` object holding every symbol's address, its initial bytes,
and the shapes of any matrices everything downstream needs about data
layout comes from this one object, and the ``matrix`` module itself only
ever supplies the vocabulary it parses with, never placement decisions of
its own. **Prettify** then normalises the remaining two-operand shorthand
into full three-operand form and resolves negative immediates into their
equivalent instruction where one exists. Finally, **encode** turns each
normalised instruction into its 32-bit word: it lowers shift
pseudo-instructions into a ``MOV`` with a shifted ``Operand2``, expands a
matrix ``MUL`` into its four-word ``SETMA``/``SETMB``/``SETMR``/``MMUL``
sequence, lowers ``TEXT`` into its full register-preserving setup/draw/
teardown sequence, lowers ``PUSH``/``POP`` register lists into one word per
register, and expands ``MOV Rd, =expr`` into its ``MOV``/``LSL``/``ORR``
chain. The vector and tensor instruction class is handled specially even at
this late stage: it's routed to ``steps/npu.py`` before the generic
encoding path ever sees it, because its operands are register-file
selectors and configuration field names rather than ordinary
``Rd``/``Rn``/``Operand2`` triples.

Every pseudo-instruction that expands into more than one word matrix
``MUL``, ``TEXT``, register lists, wide constant loads reports its own
expanded length through a shared function, ``count_instruction_words``,
which is what keeps every label address correct even when the instructions
between a label and its use expand unpredictably. Because a ``=``
expansion's length genuinely depends on the value being loaded, the whole
data section has to be laid out *before* code addresses can be computed at
all there's a real ordering dependency here, not just a convenient one.

### How the editor gets the same answers without a full build

The VS Code extension's live analysis doesn't reimplement any of this: it
calls ``layout_source`` from ``assemble.py`` directly, for section
splitting, data placement, label addresses, and bootstrap validation, and
then validates each individual instruction using the real encoder rather
than a simplified approximation of it. Errors are collected through an
``on_error`` sink rather than stopping at the first broken line, so a file
with several mistakes reports all of them at once instead of one at a time
across several edit-and-rerun cycles. Constant declarations go through the
same validation path, via ``extract_constants``.

File-based analysis shares include expansion with the real assembler too,
and it keeps track of each line's original file and line number through
that expansion, so an error inside an included file is reported against
that file rather than against wherever it happened to be spliced in. The
analyzer's JSON input accepts a ``path`` (an absolute source filename) and
an optional ``documents`` map (absolute filenames mapped to the text of
their open, unsaved buffers), alongside the plain ``text`` of the file
being analyzed and without a file path at all, a relative include simply
can't be resolved, which is reported as a diagnostic rather than guessed
at. Diagnostics and definitions both carry an optional ``path`` of their
own; ``definitions`` includes symbols imported from elsewhere, while
``symbols`` only lists the current file's own outline. ``dependencies``
lists every include path the analysis resolved, including ones that don't
currently exist on disk, specifically so that creating the missing file
later causes the editor's diagnostics to recover automatically rather than
staying stale. VS Code itself invalidates a dependent file's analysis
whenever an edit or a filesystem change happens, and discards any reply
that's been superseded by newer input in the meantime.

### Turning an already-quantized model into a program

Assembling a `.de1` file by hand isn't how the neural-network demos in this
project are built. `scripts/ml/tinyml_export.py` is a separate step that
sits in front of the assembler: it takes a JSON description of a model
that's already been quantized to INT8 and compiles it into a complete
`.de1` program, laying its tensors out in the data section and emitting one
``NPUCFG``/``NPURUN`` block per layer. [Quantized inference](tinyml.md) is
where the full story lives exactly what the JSON has to contain, which
layer types are supported, and how the committed demo programs are
regenerated and checked against their models since it's really a
property of the tensor engine's contract, not of the general-purpose
toolchain described in this document.

### Small conversion utilities

Two small modules exist purely to reshape already-encoded output into
formats other tools expect, and both are run the same way, as Python
modules rather than bare scripts:

| Module                                | Purpose                                         |
|-----------------------------------------|----------------------------------------------------|
| ``src.cpu.encoder.utils.bin2hex``     | Convert ``.bin`` to text hex (one byte per line) |
| ``src.cpu.encoder.utils.hex_to_mif``  | Convert text hex to Altera ``.mif`` format       |

``hex_to_mif`` in particular supports two distinct output widths, because
Quartus expects different things for the two kinds of memory this design
initialises: ``--width 8`` (the default) produces a byte-addressed
``.mif``, while ``--width 32`` produces a 32-bit word-addressed ``.mif``
with little-endian byte packing the format the instruction ROM actually
needs, through the ``gen_instr_fpga`` path in ``RAM.sv``.

How a program gets run without any hardware at all
--------------------------------------------------------

``src/cpu/simulation/`` is a programmatic test harness that compiles and
runs assembly programs directly in Icarus Verilog, and it's what
``pytest`` uses under the hood to check individual instructions and whole
programs alike. Two entry points cover almost everything a test needs:
``run_program_trace(lines, expect_halt=True)`` returns the full verbose RTL
trace together with the symbol map shared by both the instruction-level
tests and the performance tracker, so benchmark code never has to import
test fixtures just to reuse this path and the more commonly used
snapshot form::

    from src.cpu.simulation.runner import run_snapshot

    result = run_snapshot("""
    main:
        MOV R0, V42
    """)
    # result["registers"]["R0"]["dec"] == 42

Internally, ``run_snapshot()`` walks through a fixed sequence: it assembles
the given program using the real encoder, builds (or, far more often,
reuses) a content-addressed Icarus harness compiled for the current RTL,
writes only the program's own bytes out to an isolated, per-run
``program.hex`` so concurrent runs never collide, passes the image size,
memory range, key state, and a cycle limit to ``vvp`` as plusargs, runs
``vvp`` and waits for the CPU to halt, dumps every register, the CPSR, and
a configurable range of memory, and finally returns all of that as one
structured dictionary of register values, memory contents, and resolved
labels.

The compiled harness itself is cached under the operating system's
temporary directory by default (overridable with ``CPU_SIM_CACHE_DIR``),
keyed by the byte contents of every ``hdl/*.sv`` and ``hdl/*.svh`` file,
the generated loader and testbench, the Icarus executable's own metadata,
the configured widths, and the compile-time defines in use. That cache key
is what decides whether a run pays for a fresh compile: editing the RTL or
the harness itself triggers exactly one rebuild, while changing only the
assembly program, the memory range, the keys, or ``max_cycles`` reuses the
already-compiled harness untouched. Even so, every request still gets its
own working directory, so concurrent web simulator runs never end up
sharing program data with each other by accident.

### FAST versus RTL: two different engines behind one editor

The web UI exposes a real choice between two simulation engines, and it's
worth understanding what each one actually is under the hood rather than
treating them as interchangeable:

- **FAST / ARCHITECTURAL** (the UI's default) executes the assembled words
  through a Python model that operates at the level of instructions rather
  than clock edges. It faithfully tracks every architectural register and
  flag, the Harvard split between data and instruction memory, FP16
  arithmetic, matrices, the vector registers and accumulators, the tensor
  engine, keys, text, and framebuffer output everything a program can
  actually observe but it deliberately does *not* model pipeline or FIFO
  timing, since that's not what it's built to answer.
- **RTL / CYCLE-ACCURATE** instead runs the genuine CPU RTL under Icarus,
  compiled with ``WEB_FAST_SIMULATION``, and stays the option to reach for
  when a question is actually about timing. That build suppresses the
  verbose per-instruction ``$display`` calls the plain test harness relies
  on, while still keeping live pixel events and architectural snapshots
  flowing; it gates the large floating-point combinational network off
  whenever no FP operation is active, to keep simulation fast; and it skips
  the continuously-scanning VGA timing block entirely, because the web UI
  reads the framebuffer directly rather than needing a simulated video
  raster.

The JSON API's default engine, for backward compatibility, is still
``engine="rtl"``; only the browser's own UI explicitly requests
``engine="fast"``. The plain Python and test API defaults follow the same
convention and stay on verbose RTL unless told otherwise. To keep the RTL
option from feeling slow the very first time someone clicks it, FastAPI
warms the cached RTL artifact in a background thread as soon as the server
starts, so switching engines in the browser doesn't force a cold compile
onto whichever request happens to ask for RTL first.

Both the snapshot and the streaming run modes enforce ``max_cycles``
strictly: exceeding it raises a ``SimulationError`` rather than quietly
handing back a partial, seemingly-successful snapshot, which matters for
catching an infinite loop as a real failure instead of a silent truncation.
Captured and streamed trace output is itself bounded in size, and closing a
stream early terminates its underlying ``vvp`` subprocess rather than
leaving it running unattended.

``simulation/snapshot.py`` is where the shared snapshot and streaming event
types are defined. When working with a streamed run, narrowing a
``StreamEvent`` by checking ``event["type"]`` first is what lets the type
checker actually verify the rest of the fields for that specific kind of
event, rather than treating every event as a generic, loosely-typed blob.
