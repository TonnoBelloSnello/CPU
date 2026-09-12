export interface CompletionEntry {
  label: string;
  insertText: string;
  detail: string;
  documentation: string;
  category: "instruction" | "directive" | "register" | "symbol";
}

interface InstructionDoc {
  base: string;
  snippet: string;
  detail: string;
  documentation: string;
}

const CONDITION_DOCS: Record<string, string> = {
  EQ: "Execute when Z = 1 (equal).",
  NE: "Execute when Z = 0 (not equal).",
  CS: "Execute when C = 1 (carry set / unsigned >=).",
  CC: "Execute when C = 0 (carry clear / unsigned <).",
  MI: "Execute when N = 1 (negative).",
  PL: "Execute when N = 0 (positive or zero).",
  VS: "Execute when V = 1 (overflow).",
  VC: "Execute when V = 0 (no overflow).",
  HI: "Execute when C = 1 and Z = 0 (unsigned higher).",
  LS: "Execute when C = 0 or Z = 1 (unsigned lower or same).",
  GE: "Execute when N = V (signed >=).",
  LT: "Execute when N != V (signed <).",
  GT: "Execute when Z = 0 and N = V (signed >).",
  LE: "Execute when Z = 1 or N != V (signed <=).",
  AL: "Always execute.",
  NV: "Reserved never-execute condition.",
};

const INSTRUCTIONS: InstructionDoc[] = [
  { base: "AND", snippet: "AND ${1:Rd}, ${2:Rn}, ${3:Operand2}", detail: "Bitwise AND", documentation: "Bitwise AND: `Rd = Rn & Operand2`." },
  { base: "EOR", snippet: "EOR ${1:Rd}, ${2:Rn}, ${3:Operand2}", detail: "Bitwise XOR", documentation: "Bitwise XOR: `Rd = Rn ^ Operand2`." },
  { base: "SUB", snippet: "SUB ${1:Rd}, ${2:Rn}, ${3:Operand2}", detail: "Subtract", documentation: "Subtract Operand2 from Rn." },
  { base: "RSB", snippet: "RSB ${1:Rd}, ${2:Rn}, ${3:Operand2}", detail: "Reverse subtract", documentation: "Reverse subtract: `Rd = Operand2 - Rn`." },
  { base: "ADD", snippet: "ADD ${1:Rd}, ${2:Rn}, ${3:Operand2}", detail: "Add", documentation: "Add Operand2 to Rn." },
  { base: "MUL", snippet: "MUL ${1:Rd}, ${2:Rn}, ${3:Operand2}", detail: "Multiply", documentation: "Scalar multiply or matrix multiply when both operands are matrices." },
  { base: "DIV", snippet: "DIV ${1:Rd}, ${2:Rn}, ${3:Operand2}", detail: "Unsigned divide", documentation: "Unsigned scalar divide." },
  { base: "ADC", snippet: "ADC ${1:Rd}, ${2:Rn}, ${3:Operand2}", detail: "Add with carry", documentation: "Add Operand2 and the CPSR carry bit to Rn." },
  { base: "SBC", snippet: "SBC ${1:Rd}, ${2:Rn}, ${3:Operand2}", detail: "Subtract with carry", documentation: "Subtract Operand2 and NOT(CPSR carry) from Rn." },
  { base: "RSC", snippet: "RSC ${1:Rd}, ${2:Rn}, ${3:Operand2}", detail: "Reverse subtract with carry", documentation: "Subtract Rn and NOT(CPSR carry) from Operand2." },
  { base: "TST", snippet: "TST ${1:Rn}, ${2:Operand2}", detail: "Bit test", documentation: "Update flags from `Rn & Operand2` without writing a destination." },
  { base: "TEQ", snippet: "TEQ ${1:Rn}, ${2:Operand2}", detail: "Equality test", documentation: "Update flags from `Rn ^ Operand2`." },
  { base: "CMP", snippet: "CMP ${1:Rn}, ${2:Operand2}", detail: "Compare", documentation: "Update flags from `Rn - Operand2`." },
  { base: "CMN", snippet: "CMN ${1:Rn}, ${2:Operand2}", detail: "Compare negative", documentation: "Update flags from `Rn + Operand2`." },
  { base: "ORR", snippet: "ORR ${1:Rd}, ${2:Rn}, ${3:Operand2}", detail: "Bitwise OR", documentation: "Bitwise OR: `Rd = Rn | Operand2`." },
  { base: "SAVEM", snippet: "SAVEM ${1:Rs}, [${2:target}]", detail: "Store multi-byte", documentation: "Store a full-width register value to memory." },
  { base: "MOVM", snippet: "MOVM ${1:Rd}, [${2:source}]", detail: "Load multi-byte", documentation: "Load a full-width value from memory." },
  { base: "SAVE", snippet: "SAVE ${1:Rs}, [${2:target}]", detail: "Store byte", documentation: "Store the low byte of a register to memory." },
  { base: "MOV", snippet: "MOV ${1:Rd}, ${2:Operand2}", detail: "Move/load", documentation: "Move an immediate/register value or load a byte from memory." },
  { base: "BIC", snippet: "BIC ${1:Rd}, ${2:Rn}, ${3:Operand2}", detail: "Bit clear", documentation: "Bit clear: `Rd = Rn & ~Operand2`." },
  { base: "MVN", snippet: "MVN ${1:Rd}, ${2:Operand2}", detail: "Bitwise NOT", documentation: "Bitwise NOT move." },
  { base: "PUSH", snippet: "PUSH ${1:Rd}", detail: "Push register", documentation: "Push a register to the stack." },
  { base: "POP", snippet: "POP ${1:Rd}", detail: "Pop register", documentation: "Pop a register from the stack." },
  { base: "WAIT", snippet: "WAIT ${1:Operand2}", detail: "Delay", documentation: "Block execution for the requested duration or condition." },
  { base: "WAITK", snippet: "WAITK ${1:Rd}, ${2:mask}", detail: "Wait for key", documentation: "Block until one of the selected active-low keys is pressed." },
  { base: "PIXEL", snippet: "PIXEL ${1:X}, ${2:Y}, ${3:Color}", detail: "Framebuffer pixel write", documentation: "Write a pixel to the VGA framebuffer." },
  { base: "FADD", snippet: "FADD ${1:Rd}, ${2:Rn}, ${3:Operand2}", detail: "Float add", documentation: "Binary16 floating-point add." },
  { base: "FSUB", snippet: "FSUB ${1:Rd}, ${2:Rn}, ${3:Operand2}", detail: "Float subtract", documentation: "Binary16 floating-point subtract." },
  { base: "FMUL", snippet: "FMUL ${1:Rd}, ${2:Rn}, ${3:Operand2}", detail: "Float multiply", documentation: "Binary16 floating-point multiply." },
  { base: "FDIV", snippet: "FDIV ${1:Rd}, ${2:Rn}, ${3:Operand2}", detail: "Float divide", documentation: "Binary16 floating-point divide." },
  { base: "FCMP", snippet: "FCMP ${1:Rn}, ${2:Operand2}", detail: "Float compare", documentation: "Binary16 floating-point compare; updates flags only." },
  { base: "FMOV", snippet: "FMOV ${1:Rd}, ${2:Operand2}", detail: "Float move", documentation: "Load or move a binary16 floating-point value." },
  { base: "TEXT", snippet: "TEXT ${1:X}, ${2:Y}, ${3:Source}, ${4:Color}", detail: "Text renderer", documentation: "Render a string literal or `space:` string label to the framebuffer." },
  { base: "B", snippet: "B ${1:label}", detail: "Branch", documentation: "Branch to a label or address." },
  { base: "BL", snippet: "BL ${1:label}", detail: "Branch with link", documentation: "Branch and store the return address in LR." },
  { base: "ABS", snippet: "ABS ${1:Rd}, ${2:Operand2}", detail: "Absolute value", documentation: "Branch-class absolute value operation." },
  { base: "MAX", snippet: "MAX ${1:Rd}, ${2:Rn}, ${3:Operand2}", detail: "Maximum", documentation: "Branch-class maximum operation." },
  { base: "MIN", snippet: "MIN ${1:Rd}, ${2:Rn}, ${3:Operand2}", detail: "Minimum", documentation: "Branch-class minimum operation." },
  { base: "MADD", snippet: "MADD ${1:Rd}, ${2:Rn}, ${3:Operand2}", detail: "Multiply-add", documentation: "Branch-class multiply-add operation." },
  { base: "PIXELNB", snippet: "PIXELNB ${1:X}, ${2:Y}, ${3:Color}", detail: "Non-blocking pixel write", documentation: "Branch-class non-blocking framebuffer pixel write." },
  { base: "WAITKNB", snippet: "WAITKNB ${1:Rd}, ${2:mask}", detail: "Non-blocking key poll", documentation: "Sample selected keys immediately and write the hit mask to `Rd`." },
  { base: "QADD", snippet: "QADD ${1:Rd}, ${2:Rn}, ${3:Operand2}", detail: "Saturating add", documentation: "Signed saturating add; the result clamps to the register range instead of wrapping." },
  { base: "QSUB", snippet: "QSUB ${1:Rd}, ${2:Rn}, ${3:Operand2}", detail: "Saturating subtract", documentation: "Signed saturating subtract." },
  { base: "SSAT", snippet: "SSAT ${1:Rd}, ${2:Rn}, ${3:bits}", detail: "Signed saturate", documentation: "Clamp `Rn` to a signed field of `bits` bits, e.g. `SSAT Rd, Rn, V8` for INT8." },
  { base: "USAT", snippet: "USAT ${1:Rd}, ${2:Rn}, ${3:bits}", detail: "Unsigned saturate", documentation: "Clamp `Rn` to an unsigned field of `bits` bits, e.g. `USAT Rd, Rn, V8` for UINT8." },
  { base: "QRDMULH", snippet: "QRDMULH ${1:Rd}, ${2:Rn}, ${3:Operand2}", detail: "Rounding doubling high multiply", documentation: "gemmlowp `SaturatingRoundingDoublingHighMul`: the fixed-point multiply step of a requantization." },
  { base: "RSHR", snippet: "RSHR ${1:Rd}, ${2:Rn}, ${3:amount}", detail: "Rounding shift right", documentation: "gemmlowp `RoundingDivideByPOT`: arithmetic shift right rounding half away from zero." },
  { base: "RELU", snippet: "RELU ${1:Rd}, ${2:Rn}, ${3:ceiling}", detail: "ReLU / ReLU-n", documentation: "Clamp `Rn` to `[0, ceiling]`. A ceiling of `V0` means no upper bound, giving plain ReLU." },
  { base: "SXTB", snippet: "SXTB ${1:Rd}, ${2:Operand2}", detail: "Sign-extend byte", documentation: "Sign-extend the low byte; loads zero-extend, so an INT8 weight needs this before signed arithmetic." },
  { base: "VLD", snippet: "VLD ${1:Qd}, [${2:source}]", detail: "Vector load", documentation: "Load eight INT8 lanes into a vector register, lane 0 from the lowest address." },
  { base: "VST", snippet: "VST ${1:Qd}, [${2:target}]", detail: "Vector store", documentation: "Store eight INT8 lanes from a vector register." },
  { base: "VDOT", snippet: "VDOT ${1:Ad}, ${2:Qn}, ${3:Qm}", detail: "Vector dot product", documentation: "Eight signed INT8 lane products accumulated into a 32-bit accumulator." },
  { base: "VSUM", snippet: "VSUM ${1:Ad}, ${2:Qn}", detail: "Vector lane sum", documentation: "Accumulate the signed lane sum; the activation term of an asymmetric quantization correction." },
  { base: "VMAXR", snippet: "VMAXR ${1:Rd}, ${2:Qn}", detail: "Vector lane maximum", documentation: "Signed maximum across the lanes, written to a general register." },
  { base: "VDUP", snippet: "VDUP ${1:Qd}, ${2:Operand2}", detail: "Broadcast byte", documentation: "Replicate the low byte of Operand2 into every lane." },
  { base: "VEXT", snippet: "VEXT ${1:Rd}, ${2:Qn}, ${3:lane}", detail: "Extract lane", documentation: "Sign-extend one lane into a general register." },
  { base: "VINS", snippet: "VINS ${1:Qd}, ${2:Rm}, ${3:lane}", detail: "Insert lane", documentation: "Write the low byte of a general register into one lane." },
  { base: "ACLR", snippet: "ACLR ${1:Ad}", detail: "Clear accumulator", documentation: "Zero a 32-bit accumulator." },
  { base: "ASET", snippet: "ASET ${1:Ad}, ${2:Operand2}", detail: "Seed accumulator", documentation: "Sign-extend Operand2 into a 32-bit accumulator; used to load a bias." },
  { base: "AGET", snippet: "AGET ${1:Rd}, ${2:An}", detail: "Read accumulator", documentation: "Copy the low half of an accumulator into a general register." },
  { base: "AGETS", snippet: "AGETS ${1:Rd}, ${2:An}", detail: "Read accumulator saturating", documentation: "Copy an accumulator into a general register, saturating to the register range." },
  { base: "AQMUL", snippet: "AQMUL ${1:Ad}, ${2:Operand2}", detail: "Accumulator Q0.15 multiply", documentation: "Multiply an accumulator by a Q0.15 fixed-point value with round-to-nearest, saturating to INT32." },
  { base: "ARSHR", snippet: "ARSHR ${1:Ad}, ${2:amount}", detail: "Accumulator rounding shift", documentation: "`RoundingDivideByPOT` on a 32-bit accumulator; the shift step of a requantization." },
  { base: "NPUCFG", snippet: "NPUCFG ${1:FIELD}, ${2:Operand2}", detail: "Configure tensor engine", documentation: "Write one tensor-engine configuration field, e.g. `NPUCFG IN_BASE, R0` or `NPUCFG MODE, V(NPU_MAXPOOL)`." },
  { base: "NPURUN", snippet: "NPURUN ${1:Rd}", detail: "Run tensor engine", documentation: "Run the configured layer to completion and write the result word (output base, argmax index, or an error code) to `Rd`." },
  { base: "LSL", snippet: "LSL ${1:Rd}, ${2:Rm}, ${3:amount}", detail: "Logical shift left", documentation: "Pseudo-instruction lowered to `MOV` with a shifted register operand." },
  { base: "LSR", snippet: "LSR ${1:Rd}, ${2:Rm}, ${3:amount}", detail: "Logical shift right", documentation: "Pseudo-instruction lowered to `MOV` with a shifted register operand." },
  { base: "ASR", snippet: "ASR ${1:Rd}, ${2:Rm}, ${3:amount}", detail: "Arithmetic shift right", documentation: "Pseudo-instruction lowered to `MOV` with a shifted register operand." },
  { base: "ROR", snippet: "ROR ${1:Rd}, ${2:Rm}, ${3:amount}", detail: "Rotate right", documentation: "Pseudo-instruction lowered to `MOV` with a shifted register operand." }
];

const REGISTER_DOCS: Record<string, string> = {
  SP: "Stack pointer alias for `R13`.",
  LR: "Link register alias for `R14`.",
  PC: "Program counter alias for `R15`.",
  LE: "LED register mapped to the board LEDs.",
  HEX: "7-segment display register.",
};

for (let index = 0; index <= 12; index += 1) {
  REGISTER_DOCS[`R${index}`] = `General-purpose register \`R${index}\`.`;
}
REGISTER_DOCS.R13 = "General-purpose register `R13`, the stack pointer by convention (`SP`).";
REGISTER_DOCS.R14 = "Link register (`LR`); the same encoding reaches `HEX` when the flag bit is set.";
REGISTER_DOCS.R15 = "Encoding 15: `PC` when the flag bit is clear, `LE` when it is set.";

for (let index = 0; index <= 7; index += 1) {
  REGISTER_DOCS[`Q${index}`] = `Vector register \`Q${index}\`: eight packed INT8 lanes, lane 0 in the low byte.`;
}
for (let index = 0; index <= 3; index += 1) {
  REGISTER_DOCS[`A${index}`] = `Accumulator \`A${index}\`: 32-bit signed, the destination of \`VDOT\` and \`VSUM\`.`;
}

const DIRECTIVE_DOCS = {
  SPACE: "Start of the data section. Supports `name = value` and `name: size` declarations.",
  MAIN: "Start of the executable code section.",
};

function decodeInstructionToken(
  token: string,
): { instruction: InstructionDoc; condition?: string } | undefined {
  const upper = token.toUpperCase();
  const instruction = INSTRUCTIONS.find((candidate) => candidate.base === upper);
  if (instruction) {
    return { instruction };
  }
  for (const [suffix, condition] of Object.entries(CONDITION_DOCS)) {
    if (upper.endsWith(suffix)) {
      const base = upper.slice(0, -suffix.length);
      const conditional = INSTRUCTIONS.find((candidate) => candidate.base === base);
      if (conditional) {
        return { instruction: conditional, condition };
      }
    }
  }
  return undefined;
}

function buildInstructionCompletionEntries(): CompletionEntry[] {
  const entries: CompletionEntry[] = [];

  for (const instruction of INSTRUCTIONS) {
    entries.push({
      label: instruction.base,
      insertText: instruction.snippet,
      detail: instruction.detail,
      documentation: instruction.documentation,
      category: "instruction",
    });

    for (const [suffix, condition] of Object.entries(CONDITION_DOCS)) {
      if (suffix === "AL") {
        continue;
      }
      entries.push({
        label: `${instruction.base}${suffix}`,
        insertText: instruction.snippet.replace(instruction.base, `${instruction.base}${suffix}`),
        detail: `${instruction.detail} (${suffix})`,
        documentation: `${instruction.documentation}\n\n${condition}`,
        category: "instruction",
      });
    }
  }

  return entries;
}

const STATIC_COMPLETIONS: CompletionEntry[] = [
  ...buildInstructionCompletionEntries(),
  {
    label: "space:",
    insertText: "space:",
    detail: "Data section",
    documentation: DIRECTIVE_DOCS.SPACE,
    category: "directive",
  },
  {
    label: "main:",
    insertText: "main:",
    detail: "Code section",
    documentation: DIRECTIVE_DOCS.MAIN,
    category: "directive",
  },
  ...Object.entries(REGISTER_DOCS).map(([register, documentation]) => ({
    label: register,
    insertText: register,
    detail: "Register",
    documentation,
    category: "register" as const,
  })),
];

export function getStaticCompletionEntries(): CompletionEntry[] {
  return STATIC_COMPLETIONS;
}

export function getSymbolCompletionEntries(names: string[]): CompletionEntry[] {
  return names.map((name) => ({
    label: name,
    insertText: name,
    detail: "File symbol",
    documentation: "Label or variable defined in the current file.",
    category: "symbol",
  }));
}

export function getHoverText(token: string): string | undefined {
  const normalized = token.trim();
  const upper = normalized.toUpperCase();

  const instructionToken = decodeInstructionToken(upper);
  if (instructionToken) {
    const { instruction, condition } = instructionToken;
    const parts = [`**${instruction.base}**`, instruction.documentation];
    if (condition) {
      parts.push(condition);
    }
    return parts.join("\n\n");
  }

  if (upper === "SPACE" || upper === "MAIN") {
    return `**${upper}:**\n\n${DIRECTIVE_DOCS[upper]}`;
  }

  if (upper in REGISTER_DOCS) {
    return `**${upper}**\n\n${REGISTER_DOCS[upper]}`;
  }

  if (/^VB[01]+$/i.test(normalized)) {
    return "**Binary Immediate**\n\n`VB...` encodes an immediate value in binary form.";
  }

  if (/^V-?\d+$/i.test(normalized)) {
    return "**Immediate**\n\n`V...` encodes a decimal immediate operand.";
  }

  if (/^F/i.test(normalized)) {
    return "**FP Literal**\n\n`F...` encodes a binary16 floating-point literal.";
  }

  return undefined;
}
