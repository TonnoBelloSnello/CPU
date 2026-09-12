from __future__ import annotations

from collections import deque
from collections.abc import Generator, Mapping
from dataclasses import dataclass
from typing import Final, NamedTuple

from ..encoder.steps.npu import (
    NPU_ACCS,
    NPU_ACLR,
    NPU_AGET,
    NPU_AGETS,
    NPU_AQMUL,
    NPU_ARSHR,
    NPU_ASET,
    NPU_BUILTIN_CONSTANTS,
    NPU_CONFIG_FIELDS,
    NPU_LANES,
    NPU_NPUCFG,
    NPU_PATCH_DEPTH,
    NPU_VDOT,
    NPU_VDUP,
    NPU_VEXT,
    NPU_VINS,
    NPU_VLD,
    NPU_VMAXR,
    NPU_VREGS,
    NPU_VST,
    NPU_VSUM,
)
from .rtl_config import (
    MMIO_WINDOW_BYTES,
    NPU_ACC_WIDTH,
    RAM_ADDR_WIDTH,
    VGA_FB_HEIGHT,
    VGA_FB_WIDTH,
)
from .snapshot import MemoryCell, PixelEvent, RegisterValue, Snapshot, StreamEvent

DEFAULT_ADDR_WIDTH: Final = RAM_ADDR_WIDTH
DEFAULT_DATA_WIDTH: Final = 8
DEFAULT_MAX_CYCLES: Final = 1_000_000
VGA_WIDTH: Final = VGA_FB_WIDTH
VGA_HEIGHT: Final = VGA_FB_HEIGHT
VGA_SIZE: Final = VGA_WIDTH * VGA_HEIGHT
MAX_LOG_LINES: Final = 2_000

REG_SP: Final = 13
REG_LR: Final = 14
REG_LE: Final = 15
REG_HEX: Final = 14

CLASS_DP: Final = 0
CLASS_EXT: Final = 1
CLASS_MEM: Final = 2
CLASS_BR: Final = 3

OP_TST: Final = 0x8
OP_TEQ: Final = 0x9
OP_CMP: Final = 0xA
OP_CMN: Final = 0xB

EXT_WAIT: Final = 0x0
EXT_MUL: Final = 0x1
EXT_SETMA: Final = 0x2
EXT_SETMB: Final = 0x3
EXT_SETMR: Final = 0x4
EXT_MMUL: Final = 0x5
EXT_PIXEL: Final = 0x6
EXT_FADD: Final = 0x7
EXT_FSUB: Final = 0x8
EXT_FMUL: Final = 0x9
EXT_FDIV: Final = 0xA
EXT_FCMP: Final = 0xB
EXT_FMOV: Final = 0xC
EXT_WAITK: Final = 0xD
EXT_TEXT: Final = 0xE
EXT_DIV: Final = 0xF

MEM_NPU: Final = 0x0
MEM_STORE_MULTI: Final = 0xA
MEM_LOAD_MULTI: Final = 0xB
MEM_STORE: Final = 0xC
MEM_LOAD: Final = 0xD
MEM_PUSH: Final = 0xE
MEM_POP: Final = 0xF

NPU_CFG_COUNT: Final = len(NPU_CONFIG_FIELDS)

NPUC_MODE: Final = NPU_CONFIG_FIELDS["mode"]
NPUC_FLAGS: Final = NPU_CONFIG_FIELDS["flags"]
NPUC_IN_BASE: Final = NPU_CONFIG_FIELDS["in_base"]
NPUC_IN_W: Final = NPU_CONFIG_FIELDS["in_w"]
NPUC_IN_H: Final = NPU_CONFIG_FIELDS["in_h"]
NPUC_IN_C: Final = NPU_CONFIG_FIELDS["in_c"]
NPUC_W_BASE: Final = NPU_CONFIG_FIELDS["w_base"]
NPUC_B_BASE: Final = NPU_CONFIG_FIELDS["b_base"]
NPUC_OUT_BASE: Final = NPU_CONFIG_FIELDS["out_base"]
NPUC_OUT_W: Final = NPU_CONFIG_FIELDS["out_w"]
NPUC_OUT_H: Final = NPU_CONFIG_FIELDS["out_h"]
NPUC_OUT_C: Final = NPU_CONFIG_FIELDS["out_c"]
NPUC_K_W: Final = NPU_CONFIG_FIELDS["k_w"]
NPUC_K_H: Final = NPU_CONFIG_FIELDS["k_h"]
NPUC_STRIDE: Final = NPU_CONFIG_FIELDS["stride"]
NPUC_PAD: Final = NPU_CONFIG_FIELDS["pad"]
NPUC_IN_ZP: Final = NPU_CONFIG_FIELDS["in_zp"]
NPUC_OUT_ZP: Final = NPU_CONFIG_FIELDS["out_zp"]
NPUC_MULT: Final = NPU_CONFIG_FIELDS["mult"]
NPUC_SHIFT: Final = NPU_CONFIG_FIELDS["shift"]
NPUC_ACT_MIN: Final = NPU_CONFIG_FIELDS["act_min"]
NPUC_ACT_MAX: Final = NPU_CONFIG_FIELDS["act_max"]
NPUC_ACC_BASE: Final = NPU_CONFIG_FIELDS["acc_base"]
NPUC_LUT_BASE: Final = NPU_CONFIG_FIELDS["lut_base"]

NPU_MODE_CONV: Final = NPU_BUILTIN_CONSTANTS["NPU_CONV"]
NPU_MODE_DEPTHWISE: Final = NPU_BUILTIN_CONSTANTS["NPU_DEPTHWISE"]
NPU_MODE_MAXPOOL: Final = NPU_BUILTIN_CONSTANTS["NPU_MAXPOOL"]
NPU_MODE_AVGPOOL: Final = NPU_BUILTIN_CONSTANTS["NPU_AVGPOOL"]
NPU_MODE_LUT: Final = NPU_BUILTIN_CONSTANTS["NPU_LUT"]
NPU_MODE_ARGMAX: Final = NPU_BUILTIN_CONSTANTS["NPU_ARGMAX"]

NPU_FLAG_ACC_IN: Final = NPU_BUILTIN_CONSTANTS["NPU_ACC_IN"]
NPU_FLAG_ACC_OUT: Final = NPU_BUILTIN_CONSTANTS["NPU_ACC_OUT"]
NPU_FLAG_NO_BIAS: Final = NPU_BUILTIN_CONSTANTS["NPU_NO_BIAS"]

NPU_ERR_OK: Final = NPU_BUILTIN_CONSTANTS["NPU_OK"]
NPU_ERR_SHAPE: Final = NPU_BUILTIN_CONSTANTS["NPU_ERR_SHAPE"]
NPU_ERR_PATCH: Final = NPU_BUILTIN_CONSTANTS["NPU_ERR_PATCH"]

BR_B: Final = 0x0
BR_BL: Final = 0x1
BR_ABS: Final = 0x2
BR_MAX: Final = 0x3
BR_MIN: Final = 0x4
BR_MADD: Final = 0x5
BR_PIXELNB: Final = 0x6
BR_WAITKNB: Final = 0x7
BR_QADD: Final = 0x8
BR_QSUB: Final = 0x9
BR_SSAT: Final = 0xA
BR_USAT: Final = 0xB
BR_QRDMULH: Final = 0xC
BR_RSHR: Final = 0xD
BR_RELU: Final = 0xE
BR_SXTB: Final = 0xF

MMIO_OFF_LED: Final = 0x00
MMIO_OFF_HEX: Final = 0x04
MMIO_OFF_KEYS: Final = 0x08
MMIO_OFF_CYCLES_LO: Final = 0x0C
MMIO_OFF_CYCLES_HI: Final = 0x10

_COMPARE_OPS: Final = frozenset((OP_TST, OP_TEQ, OP_CMP, OP_CMN))
_VALID_MEMORY_OPS: Final = frozenset(
    (MEM_NPU, MEM_STORE_MULTI, MEM_LOAD_MULTI, MEM_STORE, MEM_LOAD, MEM_PUSH, MEM_POP)
)
_VALID_BRANCH_OPS: Final = frozenset(
    (
        BR_B, BR_BL, BR_ABS, BR_MAX, BR_MIN, BR_MADD, BR_PIXELNB, BR_WAITKNB,
        BR_QADD, BR_QSUB, BR_SSAT, BR_USAT, BR_QRDMULH, BR_RSHR, BR_RELU, BR_SXTB,
    )
)

_GLYPHS: Final[tuple[int, ...]] = (  # ASCII 32..126, from text_glyph_rom.sv
    0x000000000, 0x108420080, 0x294000000, 0x00BF57E80, 0x11CC219C4, 0x26AE75640,
    0x114CAC9A0, 0x108000000, 0x0C8842083, 0x608210898, 0x114450000, 0x000023880,
    0x000000084, 0x000070000, 0x000000080, 0x044221108, 0x19294A4C0, 0x1184211C0,
    0x3042221C0, 0x304C10980, 0x08CA78840, 0x390C10980, 0x190E4A4C0, 0x3C2221080,
    0x19264A4C0, 0x1929384C0, 0x000400080, 0x000400084, 0x002260820, 0x000F03C00,
    0x010419100, 0x382220080, 0x1933ADE0F, 0x008A57E20, 0x01CA629C0, 0x00E8420E0,
    0x01C94A5C0, 0x01C8721C0, 0x01C872100, 0x00E85A4E0, 0x01297A520, 0x01C4211C0,
    0x01C210980, 0x012A62920, 0x0108421E0, 0x023BAD620, 0x012D5A520, 0x01D18C5C0,
    0x01C972100, 0x01D18C5C2, 0x018A62920, 0x00C820980, 0x03E421080, 0x01294A4C0,
    0x0129498C0, 0x0235AA940, 0x022A22A20, 0x022A21080, 0x01E1321E0, 0x188421086,
    0x410821042, 0x30842108C, 0x114A8C400, 0x00000001F, 0x208000000, 0x000C139E0,
    0x210E4A5C0, 0x0006420C0, 0x084E949C0, 0x0004720C0, 0x0C8F21080, 0x00074BC2E,
    0x210A6A520, 0x100C21080, 0x080E1084C, 0x210A62920, 0x308421080, 0x0015FD6A0,
    0x000A6A520, 0x00064A4C0, 0x000E4A5C8, 0x000E949C2, 0x000A62100, 0x000660980,
    0x008F21040, 0x00094ACA0, 0x0009498C0, 0x0015AB940, 0x000931920, 0x0009498DC,
    0x000E321C0, 0x088441082, 0x108421084, 0x208411088, 0x00006C800,
)


class EmulationError(RuntimeError):
    pass


class EmulationTimeoutError(EmulationError):
    pass


@dataclass(frozen=True, slots=True)
class Instruction:
    word: int
    condition: int
    instr_class: int
    immediate: bool
    opcode: int
    flag: bool
    rn: int
    rd: int
    operand2: int

    @classmethod
    def decode(cls, word: int) -> Instruction:
        word &= 0xFFFF_FFFF
        return cls(
            word=word,
            condition=(word >> 28) & 0xF,
            instr_class=(word >> 26) & 0x3,
            immediate=bool((word >> 25) & 1),
            opcode=(word >> 21) & 0xF,
            flag=bool((word >> 20) & 1),
            rn=(word >> 16) & 0xF,
            rd=(word >> 12) & 0xF,
            operand2=word & 0xFFF,
        )


def _validate_configuration(
    program_bytes: bytes,
    *,
    mem_start: int,
    mem_end: int,
    key_mask: int,
    max_cycles: int,
    addr_width: int,
    data_width: int,
) -> None:
    if not isinstance(program_bytes, bytes):
        raise EmulationError("program_bytes must be bytes")
    if not 16 <= addr_width <= 24:
        raise EmulationError("addr_width must be within 16..24")
    if data_width != 8:
        raise EmulationError("the instruction emulator currently requires data_width=8")
    if len(program_bytes) > (1 << addr_width):
        raise EmulationError("program image does not fit the configured address space")
    if isinstance(max_cycles, bool) or not isinstance(max_cycles, int) or max_cycles <= 0:
        raise EmulationError("max_cycles must be a positive integer")
    if mem_start < 0 or mem_end < mem_start or mem_end >= (1 << addr_width):
        raise EmulationError(f"memory range must be within 0..{(1 << addr_width) - 1}")
    if isinstance(key_mask, bool) or not isinstance(key_mask, int) or not 0 <= key_mask <= 0xF:
        raise EmulationError("key_mask must be within 0..15")


def _signed(value: int, width: int) -> int:
    sign_bit = 1 << (width - 1)
    return value - (1 << width) if value & sign_bit else value


def _saturate(value: int, width: int) -> int:
    low = -(1 << (width - 1))
    high = (1 << (width - 1)) - 1
    return low if value < low else min(value, high)


def _rounding_shift_right(value: int, amount: int) -> int:
    if amount == 0:
        return value
    mask = (1 << amount) - 1
    remainder = value & mask
    threshold = (mask >> 1) + (1 if value < 0 else 0)
    return (value >> amount) + (1 if remainder > threshold else 0)


def _qrdmulh(a: int, b: int, width: int) -> int:
    rounded = ((a * b) << 1) + (1 << (width - 1))
    return _saturate(rounded >> width, width)


def _saturate_signed_bits(value: int, bits: int, width: int) -> int:
    if bits == 0 or bits >= width:
        return value
    return _saturate(value, bits)


def _saturate_unsigned_bits(value: int, bits: int, width: int) -> int:
    if bits == 0 or value < 0:
        return 0
    if bits >= width:
        return value
    high = (1 << bits) - 1
    return min(value, high)


def _lane(vector: int, index: int) -> int:
    return _signed((vector >> (index * 8)) & 0xFF, 8)


class Fp16(NamedTuple):
    sign: int
    exponent: int
    fraction: int
    is_nan: bool
    is_inf: bool
    is_zero: bool


def _fp16_parts(bits: int) -> Fp16:
    bits &= 0xFFFF
    exponent = (bits >> 10) & 0x1F
    fraction = bits & 0x3FF
    return Fp16(
        sign=(bits >> 15) & 1,
        exponent=exponent,
        fraction=0 if exponent == 0 else fraction,
        is_nan=exponent == 0x1F and fraction != 0,
        is_inf=exponent == 0x1F and fraction == 0,
        is_zero=exponent == 0,
    )


def _pack_fp16(sign: int, exponent: int, fraction: int) -> int:
    return ((sign & 1) << 15) | ((exponent & 0x1F) << 10) | (fraction & 0x3FF)


def _round_pack_fp16(sign: int, exponent: int, sig_grs: int) -> int:
    sig_grs &= 0x3FFF
    if sig_grs == 0 or exponent <= 0:
        return _pack_fp16(sign, 0, 0)

    mantissa = (sig_grs >> 3) & 0x7FF
    guard = (sig_grs >> 2) & 1
    round_bit = (sig_grs >> 1) & 1
    sticky = sig_grs & 1
    if guard and (round_bit or sticky or (mantissa & 1)):
        mantissa += 1
    if mantissa & 0x800:
        mantissa >>= 1
        exponent += 1
    if exponent >= 31:
        return _pack_fp16(sign, 0x1F, 0)
    if exponent <= 0:
        return _pack_fp16(sign, 0, 0)
    return _pack_fp16(sign, exponent, mantissa)


def _shift_right_sticky_14(value: int, amount: int) -> int:
    value &= 0x3FFF
    if amount == 0:
        return value
    if amount >= 14:
        return int(value != 0)
    shifted = value >> amount
    if value & ((1 << amount) - 1):
        shifted |= 1
    return shifted


def _normalization_shift(value: int, exponent: int, *, top_bit: int, depth: int) -> int:
    highest = value.bit_length() - 1
    lead = depth if highest < top_bit - depth else top_bit - highest
    room = min(depth, max(exponent - 1, 0))
    return min(lead, room)


def _fp16_addsub(pa: Fp16, pb: Fp16, *, subtract: bool) -> int:
    sign_b = pb.sign ^ int(subtract)
    if pa.is_nan or pb.is_nan:
        return 0x7E00
    if pa.is_inf or pb.is_inf:
        if pa.is_inf and pb.is_inf and pa.sign != sign_b:
            return 0x7E00
        if pa.is_inf:
            return _pack_fp16(pa.sign, 0x1F, 0)
        return _pack_fp16(sign_b, 0x1F, 0)
    if pa.is_zero and pb.is_zero:
        return _pack_fp16(pa.sign & sign_b, 0, 0)
    if pa.is_zero:
        return _pack_fp16(sign_b, pb.exponent, pb.fraction)
    if pb.is_zero:
        return _pack_fp16(pa.sign, pa.exponent, pa.fraction)

    mant_a = 0x400 | pa.fraction
    mant_b = 0x400 | pb.fraction
    ext_a = mant_a << 3
    ext_b = mant_b << 3
    if pa.exponent > pb.exponent or (pa.exponent == pb.exponent and mant_a >= mant_b):
        exp_large, exp_small = pa.exponent, pb.exponent
        sign_large, sign_small = pa.sign, sign_b
        ext_large, ext_small = ext_a, ext_b
    else:
        exp_large, exp_small = pb.exponent, pa.exponent
        sign_large, sign_small = sign_b, pa.sign
        ext_large, ext_small = ext_b, ext_a
    ext_small = _shift_right_sticky_14(ext_small, exp_large - exp_small)

    if sign_large == sign_small:
        total = ext_large + ext_small
        if total & 0x4000:
            sig_grs = (total >> 1) & 0x3FFF
            sig_grs |= total & 1
            exp_large += 1
        else:
            sig_grs = total
        return _round_pack_fp16(sign_large, exp_large, sig_grs)

    if ext_large == ext_small:
        return _pack_fp16(0, 0, 0)
    difference = ext_large - ext_small
    shift = _normalization_shift(difference, exp_large, top_bit=13, depth=11)
    sig_grs = (difference << shift) & 0x3FFF
    exponent = exp_large - shift
    if not sig_grs & 0x2000:
        return _pack_fp16(sign_large, 0, 0)
    return _round_pack_fp16(sign_large, exponent, sig_grs)


def _fp16_multiply(pa: Fp16, pb: Fp16) -> int:
    sign = pa.sign ^ pb.sign
    if pa.is_nan or pb.is_nan:
        return 0x7E00
    if (pa.is_inf and pb.is_zero) or (pb.is_inf and pa.is_zero):
        return 0x7E00
    if pa.is_inf or pb.is_inf:
        return _pack_fp16(sign, 0x1F, 0)
    if pa.is_zero or pb.is_zero:
        return _pack_fp16(sign, 0, 0)

    product = (0x400 | pa.fraction) * (0x400 | pb.fraction)
    exponent = pa.exponent + pb.exponent - 15
    if product & (1 << 21):
        exponent += 1
        sig_grs = ((product >> 11) & 0x7FF) << 3
        sig_grs |= ((product >> 10) & 1) << 2
        sig_grs |= ((product >> 9) & 1) << 1
        sig_grs |= int(bool(product & 0x1FF))
    else:
        sig_grs = ((product >> 10) & 0x7FF) << 3
        sig_grs |= ((product >> 9) & 1) << 2
        sig_grs |= ((product >> 8) & 1) << 1
        sig_grs |= int(bool(product & 0xFF))
    return _round_pack_fp16(sign, exponent, sig_grs)


def _fp16_divide(pa: Fp16, pb: Fp16) -> int:
    sign = pa.sign ^ pb.sign
    if pa.is_nan or pb.is_nan or (pa.is_zero and pb.is_zero) or (pa.is_inf and pb.is_inf):
        return 0x7E00
    if pa.is_inf:
        return _pack_fp16(sign, 0x1F, 0)
    if pb.is_inf:
        return _pack_fp16(sign, 0, 0)
    if pb.is_zero:
        return _pack_fp16(sign, 0x1F, 0)
    if pa.is_zero:
        return _pack_fp16(sign, 0, 0)

    numerator = (0x400 | pa.fraction) << 16
    denominator = 0x400 | pb.fraction
    quotient, remainder = divmod(numerator, denominator)
    exponent = pa.exponent - pb.exponent + 15
    shift = _normalization_shift(quotient, exponent, top_bit=16, depth=3)
    quotient = (quotient << shift) & 0x3FFFF
    exponent -= shift
    sig_grs = ((quotient >> 6) & 0x7FF) << 3
    sig_grs |= ((quotient >> 5) & 1) << 2
    sig_grs |= ((quotient >> 4) & 1) << 1
    sig_grs |= int(bool((quotient & 0xF) or remainder))
    return _round_pack_fp16(sign, exponent, sig_grs)


def _fp16_binary(a_bits: int, b_bits: int, opcode: int) -> int:
    pa = _fp16_parts(a_bits)
    pb = _fp16_parts(b_bits)
    if opcode in (EXT_FADD, EXT_FSUB):
        return _fp16_addsub(pa, pb, subtract=opcode == EXT_FSUB)
    if opcode == EXT_FMUL:
        return _fp16_multiply(pa, pb)
    if opcode == EXT_FDIV:
        return _fp16_divide(pa, pb)
    raise EmulationError(f"unsupported floating-point opcode 0x{opcode:X}")


def _fp16_compare(a_bits: int, b_bits: int) -> tuple[bool, bool, bool, bool]:
    pa = _fp16_parts(a_bits)
    pb = _fp16_parts(b_bits)
    if pa.is_nan or pb.is_nan:
        return False, False, False, True
    if pa.is_zero and pb.is_zero:
        return True, False, False, False
    if pa.sign != pb.sign:
        return False, bool(pa.sign), not bool(pa.sign), False
    magnitude_a = (pa.exponent << 10) | pa.fraction
    magnitude_b = (pb.exponent << 10) | pb.fraction
    if magnitude_a == magnitude_b:
        return True, False, False, False
    if not pa.sign:
        return False, magnitude_a < magnitude_b, magnitude_a > magnitude_b, False
    return False, magnitude_a > magnitude_b, magnitude_a < magnitude_b, False


class CPUEmulator:
    def __init__(
        self,
        program_bytes: bytes,
        *,
        key_mask: int = 0,
        addr_width: int = DEFAULT_ADDR_WIDTH,
        data_width: int = DEFAULT_DATA_WIDTH,
        trace: bool = False,
    ) -> None:
        _validate_configuration(
            program_bytes,
            mem_start=0,
            mem_end=0,
            key_mask=key_mask,
            max_cycles=1,
            addr_width=addr_width,
            data_width=data_width,
        )
        self.addr_width = addr_width
        self.data_width = data_width
        self.mask = (1 << addr_width) - 1
        self.hex_width = (addr_width + 3) // 4
        self.transfer_bytes = (addr_width + data_width - 1) // data_width
        self.trace = trace

        self.memory = bytearray(1 << addr_width)
        self.memory[: len(program_bytes)] = program_bytes
        padded = program_bytes + bytes((-len(program_bytes)) % 4)
        self._instruction_words = tuple(
            int.from_bytes(padded[offset : offset + 4], "little")
            for offset in range(0, len(padded), 4)
        )
        self.framebuffer = bytearray(VGA_SIZE)
        self.mmio_base = (1 << addr_width) - MMIO_WINDOW_BYTES
        self.registers = [0] * 15
        self.registers[REG_SP] = self.mmio_base
        self.pc = 0
        self.led = 0
        self.hex = 0
        self.cpsr = 0
        self.halted = False
        self.cycles = 0
        self.instructions_retired = 0
        self.key_mask = key_mask

        self.vector_registers = [0] * NPU_VREGS
        self.accumulators = [0] * NPU_ACCS
        self.npu_cfg = [0] * NPU_CFG_COUNT

        self.mar_a = 0
        self.mar_b = 0
        self.mar_r = 0
        self.mat_rows_a = 0
        self.mat_cols_a = 0
        self.mat_cols_b = 0
        self._waiting_key_mask: int | None = None
        self._waiting_key_rd = 0
        self._waiting_key_flag = False
        self.log: deque[str] = deque(maxlen=MAX_LOG_LINES)

    @property
    def flags(self) -> tuple[bool, bool, bool, bool]:
        return (
            bool(self.cpsr >> 31 & 1),
            bool(self.cpsr >> 30 & 1),
            bool(self.cpsr >> 29 & 1),
            bool(self.cpsr >> 28 & 1),
        )

    def _trace(self, message: str) -> None:
        if self.trace:
            self.log.append(message)

    @property
    def blocked_on_keys(self) -> bool:
        return self._waiting_key_mask is not None and not (
            self.key_mask & self._waiting_key_mask
        )

    def _unsupported(self, kind: str, opcode: int) -> EmulationError:
        return EmulationError(
            f"unsupported {kind} opcode 0x{opcode:X} at PC=0x{(self.pc - 4) & self.mask:X}"
        )

    def _fetch_word(self, address: int) -> int:
        index = (address & self.mask) >> 2
        return self._instruction_words[index] if index < len(self._instruction_words) else 0

    def _condition_met(self, condition: int) -> bool:
        n, z, c, v = self.flags
        return (
            z, not z, c, not c,
            n, not n, v, not v,
            c and not z, not c or z, n == v, n != v,
            not z and n == v, z or n != v, True, False,
        )[condition]

    def _read_register(self, index: int) -> int:
        if index == REG_LE:
            return self.led
        if 0 <= index < len(self.registers):
            return self.registers[index]
        return 0

    def _read_rd(self, instr: Instruction) -> int:
        if instr.rd == REG_HEX and instr.flag:
            return self.hex
        return self._read_register(instr.rd)

    def _raw_operand2(self, instr: Instruction) -> int:
        index = instr.operand2 & 0xF
        if index == REG_HEX and instr.operand2 & 0x10:
            return self.hex
        return self._read_register(index)

    def _operand2(self, instr: Instruction) -> int:
        if instr.immediate:
            return instr.operand2
        value = self._raw_operand2(instr)
        amount = (instr.operand2 >> 7) & 0x1F
        shift_type = (instr.operand2 >> 5) & 0x3
        if shift_type == 0:
            return (value << amount) & self.mask
        if shift_type == 1:
            return value >> amount
        if shift_type == 2:
            return (_signed(value, self.addr_width) >> amount) & self.mask
        amount %= self.addr_width
        if amount == 0:
            return value
        return ((value >> amount) | (value << (self.addr_width - amount))) & self.mask

    def _write_destination(self, instr: Instruction, value: int) -> None:
        value &= self.mask
        if instr.rd == REG_HEX and instr.flag:
            self.hex = value
        elif instr.rd != REG_LE:
            self.registers[instr.rd] = value
        elif instr.flag:
            self.led = value
        else:
            self.pc = value

    def _set_flags(self, result: int, carry: bool, overflow: bool) -> None:
        self.cpsr = (
            (((result >> (self.addr_width - 1)) & 1) << 31)
            | ((result == 0) << 30)
            | (int(carry) << 29)
            | (int(overflow) << 28)
        )

    def _alu(self, opcode: int, a: int, b: int) -> tuple[int, bool, bool]:
        carry_in = bool((self.cpsr >> 29) & 1)
        carry = False
        overflow = False
        if opcode in (0x0, OP_TST):
            result = a & b
        elif opcode in (0x1, OP_TEQ):
            result = a ^ b
        elif opcode in (0x2, OP_CMP):
            result = (a - b) & self.mask
            carry = a >= b
            overflow = bool(((a ^ b) & (a ^ result)) >> (self.addr_width - 1) & 1)
        elif opcode == 0x3:
            result = (b - a) & self.mask
            carry = b >= a
            overflow = bool(((b ^ a) & (b ^ result)) >> (self.addr_width - 1) & 1)
        elif opcode in (0x4, OP_CMN):
            raw = a + b
            result = raw & self.mask
            carry = raw > self.mask
            overflow = bool((~(a ^ b) & (a ^ result)) >> (self.addr_width - 1) & 1)
        elif opcode == 0x5:
            raw = a + b + int(carry_in)
            result = raw & self.mask
            carry = raw > self.mask
            overflow = bool((~(a ^ b) & (a ^ result)) >> (self.addr_width - 1) & 1)
        elif opcode == 0x6:
            borrow = int(not carry_in)
            result = (a - b - borrow) & self.mask
            carry = a >= b + borrow
            overflow = bool(((a ^ b) & (a ^ result)) >> (self.addr_width - 1) & 1)
        elif opcode == 0x7:
            borrow = int(not carry_in)
            result = (b - a - borrow) & self.mask
            carry = b >= a + borrow
            overflow = bool(((b ^ a) & (b ^ result)) >> (self.addr_width - 1) & 1)
        elif opcode == 0xC:
            result = a | b
        elif opcode == 0xD:
            result = b
        elif opcode == 0xE:
            result = a & ~b
        elif opcode == 0xF:
            result = ~b
        else:
            raise EmulationError(f"unsupported data-processing opcode 0x{opcode:X}")
        return result & self.mask, carry, overflow

    def _execute_dp(self, instr: Instruction) -> None:
        a = self._read_register(instr.rn)
        b = self._operand2(instr)
        result, carry, overflow = self._alu(instr.opcode, a, b)
        if instr.opcode in _COMPARE_OPS:
            self._set_flags(result, carry, overflow)
            self._trace(
                f"Comparison: result={result:0{self.hex_width}x}, "
                f"N={self.flags[0]:d} Z={self.flags[1]:d} "
                f"C={self.flags[2]:d} V={self.flags[3]:d}"
            )
        else:
            self._write_destination(instr, result)
            self._trace(f"Storing result {result} (0x{result:0{self.hex_width}x})")

    def _memory_address(self, instr: Instruction) -> int:
        return (instr.operand2 if instr.immediate else self._raw_operand2(instr)) & self.mask

    def _mmio_register(self, slot: int) -> int:
        if slot == MMIO_OFF_LED:
            return self.led
        if slot == MMIO_OFF_HEX:
            return self.hex
        if slot == MMIO_OFF_KEYS:
            return self.key_mask & 0xF
        if slot == MMIO_OFF_CYCLES_LO:
            return self.cycles & self.mask
        if slot == MMIO_OFF_CYCLES_HI:
            return (self.cycles >> self.addr_width) & self.mask
        return 0

    def _read_byte(self, address: int) -> int:
        if address < self.mmio_base:
            return self.memory[address]
        offset = address - self.mmio_base
        byte_index = offset & 0x3
        if byte_index >= self.transfer_bytes:
            return 0
        return (self._mmio_register(offset & ~0x3) >> (byte_index * 8)) & 0xFF

    def _write_byte(self, address: int, value: int) -> None:
        if address < self.mmio_base:
            self.memory[address] = value & 0xFF
            return
        offset = address - self.mmio_base
        byte_index = offset & 0x3
        if byte_index >= self.transfer_bytes:
            return
        shift = byte_index * 8
        slot = offset & ~0x3
        if slot == MMIO_OFF_LED:
            self.led = self._merge_byte(self.led, value, shift)
        elif slot == MMIO_OFF_HEX:
            self.hex = self._merge_byte(self.hex, value, shift)

    def _merge_byte(self, current: int, value: int, shift: int) -> int:
        return ((current & ~(0xFF << shift)) | ((value & 0xFF) << shift)) & self.mask

    def _execute_memory(self, instr: Instruction) -> None:
        if instr.opcode not in _VALID_MEMORY_OPS:
            raise self._unsupported("memory", instr.opcode)
        if instr.opcode == MEM_NPU:
            self._execute_npu(instr)
            return
        if instr.opcode == MEM_PUSH:
            sp = (self.registers[REG_SP] - self.transfer_bytes) & self.mask
            self._store_multi(sp, self._read_rd(instr))
            self.registers[REG_SP] = sp
            return
        if instr.opcode == MEM_POP:
            sp = self.registers[REG_SP]
            self._write_destination(instr, self._load_multi(sp))
            self.registers[REG_SP] = (sp + self.transfer_bytes) & self.mask
            return

        address = self._memory_address(instr)
        if instr.opcode == MEM_STORE:
            self._write_byte(address, self._read_rd(instr))
        elif instr.opcode == MEM_LOAD:
            self._write_destination(instr, self._read_byte(address))
        elif instr.opcode == MEM_STORE_MULTI:
            self._store_multi(address, self._read_rd(instr))
        else:
            self._write_destination(instr, self._load_multi(address))

    def _store_multi(self, address: int, value: int) -> None:
        for index in range(self.transfer_bytes):
            self._write_byte((address + index) & self.mask, value >> (index * 8))

    def _load_multi(self, address: int) -> int:
        value = 0
        for index in range(self.transfer_bytes):
            value |= self._read_byte((address + index) & self.mask) << (index * 8)
        return value

    def _pixel(self, x: int, y: int, color: int) -> PixelEvent | None:
        if x >= VGA_WIDTH or y >= VGA_HEIGHT:
            return None
        address = y * VGA_WIDTH + x
        color &= 0xFF
        self.framebuffer[address] = color
        return {"type": "pixel", "x": x, "y": y, "color": color, "addr": address}

    def _execute_matrix(self, instr: Instruction) -> None:
        if not self.mat_rows_a or not self.mat_cols_a or not self.mat_cols_b:
            raise EmulationError("MMUL encountered before valid non-zero matrix descriptors")
        for row in range(self.mat_rows_a):
            for column in range(self.mat_cols_b):
                accumulator = 0
                for inner in range(self.mat_cols_a):
                    a_addr = (self.mar_a + row * self.mat_cols_a + inner) & self.mask
                    b_addr = (self.mar_b + inner * self.mat_cols_b + column) & self.mask
                    product = self.memory[a_addr] * self.memory[b_addr]
                    accumulator = (accumulator + product) & 0xFFFF_FFFF
                target = (self.mar_r + row * self.mat_cols_b + column) & self.mask
                self.memory[target] = accumulator & 0xFF
        self._write_destination(instr, self.mar_r)

    @staticmethod
    def _glyph_bits(character: int) -> int:
        normalized = character if 32 <= character <= 126 else ord("?")
        return _GLYPHS[normalized - 32]

    def _execute_text(self, instr: Instruction) -> tuple[PixelEvent, ...]:
        base_x = self._read_register(instr.rd)
        base_y = self._read_register(instr.rn)
        pointer = self._operand2(instr)
        color = self.registers[12] & 0xFF
        events: list[PixelEvent] = []
        for char_index in range(16):
            character = self.memory[(pointer + char_index) & self.mask]
            if character == 0:
                break
            glyph = self._glyph_bits(character)
            char_x = (base_x + char_index * 6) & self.mask
            for row in range(7):
                row_bits = (glyph >> ((6 - row) * 5)) & 0x1F
                y = (base_y + row) & self.mask
                for column in range(5):
                    if row_bits & (1 << (4 - column)):
                        event = self._pixel((char_x + column) & self.mask, y, color)
                        if event is not None:
                            events.append(event)
        return tuple(events)

    def _fp_operand(self, instr: Instruction) -> int:
        if instr.immediate:
            address = instr.operand2 & self.mask
            return self.memory[address] | (self.memory[(address + 1) & self.mask] << 8)
        return self._raw_operand2(instr) & 0xFFFF

    def _execute_extended(self, instr: Instruction) -> tuple[PixelEvent, ...]:
        operand = self._operand2(instr)
        if instr.opcode == EXT_WAIT:
            self.cycles += max(instr.operand2, 1)
        elif instr.opcode == EXT_MUL:
            self._write_destination(instr, self._read_register(instr.rn) * operand)
        elif instr.opcode == EXT_DIV:
            dividend = self._read_register(instr.rn)
            self._write_destination(instr, 0 if operand == 0 else dividend // operand)
        elif instr.opcode == EXT_SETMA:
            self.mar_a = instr.operand2 & self.mask
            self.mat_rows_a = instr.rn
            self.mat_cols_a = instr.rd
        elif instr.opcode == EXT_SETMB:
            self.mar_b = instr.operand2 & self.mask
            self.mat_cols_b = instr.rd
        elif instr.opcode == EXT_SETMR:
            self.mar_r = instr.operand2 & self.mask
        elif instr.opcode == EXT_MMUL:
            self._execute_matrix(instr)
        elif instr.opcode == EXT_PIXEL:
            event = self._pixel(
                self._read_register(instr.rd),
                self._read_register(instr.rn),
                operand,
            )
            return () if event is None else (event,)
        elif EXT_FADD <= instr.opcode <= EXT_FMOV:
            fp_b = self._fp_operand(instr)
            if instr.opcode == EXT_FCMP:
                equal, less, greater, unordered = _fp16_compare(
                    self._read_register(instr.rn) & 0xFFFF, fp_b
                )
                self.cpsr = (
                    (int(less and not unordered) << 31)
                    | (int(equal and not unordered) << 30)
                    | (int((greater or equal) and not unordered) << 29)
                    | (int(unordered) << 28)
                )
            elif instr.opcode == EXT_FMOV:
                self._write_destination(instr, fp_b)
            else:
                result = _fp16_binary(
                    self._read_register(instr.rn) & 0xFFFF,
                    fp_b,
                    instr.opcode,
                )
                self._write_destination(instr, result)
        elif instr.opcode == EXT_WAITK:
            selected = operand & 0xF or 0xF
            hit = self.key_mask & selected
            if hit:
                self._write_destination(instr, hit)
            else:
                self._waiting_key_mask = selected
                self._waiting_key_rd = instr.rd
                self._waiting_key_flag = instr.flag
        elif instr.opcode == EXT_TEXT:
            return self._execute_text(instr)
        else:
            raise self._unsupported("extended", instr.opcode)
        return ()

    def _execute_branch(self, instr: Instruction) -> tuple[PixelEvent, ...]:
        if instr.opcode not in _VALID_BRANCH_OPS:
            raise self._unsupported("branch", instr.opcode)
        if instr.opcode in (BR_B, BR_BL):
            if instr.opcode == BR_BL:
                self.registers[REG_LR] = self.pc
            target = (instr.rn << 16) | (instr.rd << 12) | instr.operand2
            self.pc = target & self.mask
        elif instr.opcode == BR_ABS:
            value = self._operand2(instr)
            negative = value & (1 << (self.addr_width - 1))
            magnitude = -_signed(value, self.addr_width) & self.mask if negative else value
            self._write_destination(instr, magnitude)
        elif instr.opcode in (BR_MAX, BR_MIN):
            a = self._read_register(instr.rn)
            b = self._operand2(instr)
            choose_a = _signed(a, self.addr_width) >= _signed(b, self.addr_width)
            if instr.opcode == BR_MIN:
                choose_a = not choose_a if a != b else True
            self._write_destination(instr, a if choose_a else b)
        elif instr.opcode == BR_MADD:
            result = self._read_rd(instr) + self._read_register(instr.rn) * self._operand2(instr)
            self._write_destination(instr, result)
        elif instr.opcode in (
            BR_QADD, BR_QSUB, BR_SSAT, BR_USAT, BR_QRDMULH, BR_RSHR, BR_RELU, BR_SXTB
        ):
            self._execute_quant(instr)
        elif instr.opcode == BR_PIXELNB:
            event = self._pixel(
                self._read_register(instr.rd),
                self._read_register(instr.rn),
                self._operand2(instr),
            )
            return () if event is None else (event,)
        else:
            selected = self._operand2(instr) & 0xF or 0xF
            self._write_destination(instr, self.key_mask & selected)
        return ()

    def _execute_quant(self, instr: Instruction) -> None:
        width = self.addr_width
        a = _signed(self._read_register(instr.rn), width)
        b_raw = self._operand2(instr)
        b = _signed(b_raw, width)

        if instr.opcode == BR_QADD:
            result = _saturate(a + b, width)
        elif instr.opcode == BR_QSUB:
            result = _saturate(a - b, width)
        elif instr.opcode == BR_SSAT:
            result = _saturate_signed_bits(a, b_raw & 0x1F, width)
        elif instr.opcode == BR_USAT:
            result = _saturate_unsigned_bits(a, b_raw & 0x1F, width)
        elif instr.opcode == BR_QRDMULH:
            result = _qrdmulh(a, b, width)
        elif instr.opcode == BR_RSHR:
            result = _rounding_shift_right(a, b_raw & 0x1F)
        elif instr.opcode == BR_RELU:
            floored = max(a, 0)
            result = min(floored, b) if b != 0 else floored
        else:
            result = _signed(b_raw & 0xFF, 8)

        self._write_destination(instr, result & self.mask)

    def _npu_read(self, address: int) -> int:
        return self._read_byte(address & self.mask)

    def _npu_read_i32(self, address: int) -> int:
        value = 0
        for offset in range(4):
            value |= self._npu_read(address + offset) << (offset * 8)
        return _signed(value, 32)

    def _npu_write_i32(self, address: int, value: int) -> None:
        unsigned = value & 0xFFFF_FFFF
        for offset in range(4):
            self._write_byte((address + offset) & self.mask, (unsigned >> (offset * 8)) & 0xFF)

    def _npu_requantize(self, accumulator: int) -> int:
        cfg = self.npu_cfg
        multiplier = cfg[NPUC_MULT] & 0xFFFF
        shift = cfg[NPUC_SHIFT] & 0x1F
        out_zp = _signed(cfg[NPUC_OUT_ZP] & 0xFFFF, 16)
        act_min = _signed(cfg[NPUC_ACT_MIN] & 0xFF, 8)
        act_max = _signed(cfg[NPUC_ACT_MAX] & 0xFF, 8)

        value = accumulator if multiplier == 0 else (accumulator * multiplier + 16384) >> 15
        value = _rounding_shift_right(value, shift)
        value += out_zp
        if act_min == act_max:
            act_min, act_max = -128, 127
        return min(max(value, act_min), act_max)

    def _npu_store(self, out_index: int, accumulator: int) -> None:
        cfg = self.npu_cfg
        if cfg[NPUC_FLAGS] & NPU_FLAG_ACC_OUT:
            self._npu_write_i32(cfg[NPUC_ACC_BASE] + out_index * 4, accumulator)
        else:
            value = self._npu_requantize(accumulator)
            self._write_byte((cfg[NPUC_OUT_BASE] + out_index) & self.mask, value & 0xFF)

    def _npu_seed(self, out_index: int, channel: int) -> int:
        cfg = self.npu_cfg
        flags = cfg[NPUC_FLAGS]
        if flags & NPU_FLAG_ACC_IN:
            return self._npu_read_i32(cfg[NPUC_ACC_BASE] + out_index * 4)
        if flags & NPU_FLAG_NO_BIAS:
            return 0
        return self._npu_read_i32(cfg[NPUC_B_BASE] + channel * 4)

    def _npu_window(self, out_y: int, out_x: int, channel: int) -> tuple[list[int], int]:
        cfg = self.npu_cfg
        mode = cfg[NPUC_MODE] & 0xF
        is_conv = mode == NPU_MODE_CONV
        is_pool = mode in (NPU_MODE_MAXPOOL, NPU_MODE_AVGPOOL)
        in_w, in_h, in_c = cfg[NPUC_IN_W], cfg[NPUC_IN_H], cfg[NPUC_IN_C]
        stride_x, stride_y = cfg[NPUC_STRIDE] & 0xFF, (cfg[NPUC_STRIDE] >> 8) & 0xFF
        pad_x, pad_y = cfg[NPUC_PAD] & 0xFF, (cfg[NPUC_PAD] >> 8) & 0xFF
        in_zp = _signed(cfg[NPUC_IN_ZP] & 0xFF, 8)

        values: list[int] = []
        in_bounds_count = 0
        channels = range(in_c) if is_conv else (channel,)
        for kernel_y in range(cfg[NPUC_K_H]):
            source_y = out_y * stride_y + kernel_y - pad_y
            for kernel_x in range(cfg[NPUC_K_W]):
                source_x = out_x * stride_x + kernel_x - pad_x
                inside = 0 <= source_y < in_h and 0 <= source_x < in_w
                for source_c in channels:
                    if not inside:
                        if not is_pool:
                            values.append(0)
                        continue
                    offset = (source_y * in_w + source_x) * in_c + source_c
                    sample = _signed(self._npu_read(cfg[NPUC_IN_BASE] + offset), 8)
                    values.append(sample if is_pool else sample - in_zp)
                    in_bounds_count += 1
        return values, in_bounds_count

    def _npu_elementwise(self, mode: int) -> int:
        cfg = self.npu_cfg
        count = cfg[NPUC_OUT_W] * cfg[NPUC_OUT_H] * cfg[NPUC_OUT_C]
        if mode == NPU_MODE_LUT:
            for index in range(count):
                sample = self._npu_read(cfg[NPUC_IN_BASE] + index)
                self._write_byte(
                    (cfg[NPUC_OUT_BASE] + index) & self.mask,
                    self._npu_read(cfg[NPUC_LUT_BASE] + sample),
                )
            return cfg[NPUC_OUT_BASE] & self.mask

        best_index = 0
        best_value = None
        for index in range(count):
            sample = _signed(self._npu_read(cfg[NPUC_IN_BASE] + index), 8)
            if best_value is None or sample > best_value:
                best_value = sample
                best_index = index
        return best_index & self.mask

    def _execute_npu_engine(self) -> int:
        cfg = self.npu_cfg
        mode = cfg[NPUC_MODE] & 0xF
        out_w, out_h, out_c = cfg[NPUC_OUT_W], cfg[NPUC_OUT_H], cfg[NPUC_OUT_C]
        if out_w == 0 or out_h == 0 or out_c == 0:
            return NPU_ERR_SHAPE
        if mode in (NPU_MODE_LUT, NPU_MODE_ARGMAX):
            return self._npu_elementwise(mode)

        k_w, k_h, in_c = cfg[NPUC_K_W], cfg[NPUC_K_H], cfg[NPUC_IN_C]
        is_conv = mode == NPU_MODE_CONV
        if k_w == 0 or k_h == 0 or (is_conv and in_c == 0):
            return NPU_ERR_SHAPE
        window_length = k_h * k_w * in_c if is_conv else k_h * k_w
        if window_length > NPU_PATCH_DEPTH:
            return NPU_ERR_PATCH

        is_pool = mode in (NPU_MODE_MAXPOOL, NPU_MODE_AVGPOOL)
        has_weights = mode in (NPU_MODE_CONV, NPU_MODE_DEPTHWISE)
        weight_base = cfg[NPUC_W_BASE]
        out_index = 0
        for out_y in range(out_h):
            for out_x in range(out_w):
                window = None
                for channel in range(out_c):
                    if window is None or not is_conv:
                        window, valid = self._npu_window(out_y, out_x, channel)

                    if is_pool:
                        present = window[:valid]
                        if not present:
                            accumulator = 0
                        elif mode == NPU_MODE_MAXPOOL:
                            accumulator = max(present)
                        else:
                            accumulator = sum(present)
                    else:
                        accumulator = self._npu_seed(out_index, channel)
                        if has_weights:
                            if is_conv:
                                row = weight_base + channel * window_length
                                stride = 1
                            else:
                                row = weight_base + channel
                                stride = in_c
                            for element in range(window_length):
                                weight = _signed(
                                    self._npu_read(row + element * stride), 8
                                )
                                accumulator += window[element] * weight
                        accumulator = _signed(accumulator & 0xFFFF_FFFF, 32)

                    self._npu_store(out_index, accumulator)
                    out_index += 1
        return cfg[NPUC_OUT_BASE] & self.mask

    def _execute_npu(self, instr: Instruction) -> None:
        sub_opcode = instr.rn
        accumulator_mask = (1 << NPU_ACC_WIDTH) - 1

        if sub_opcode == NPU_VLD:
            address = self._memory_address(instr)
            value = 0
            for lane in range(NPU_LANES):
                value |= self._read_byte((address + lane) & self.mask) << (lane * 8)
            self.vector_registers[instr.rd % NPU_VREGS] = value
        elif sub_opcode == NPU_VST:
            address = self._memory_address(instr)
            value = self.vector_registers[instr.rd % NPU_VREGS]
            for lane in range(NPU_LANES):
                self._write_byte((address + lane) & self.mask, (value >> (lane * 8)) & 0xFF)
        elif sub_opcode == NPU_VDOT:
            left = self.vector_registers[instr.operand2 & 0x7]
            right = self.vector_registers[(instr.operand2 >> 3) & 0x7]
            total = sum(_lane(left, i) * _lane(right, i) for i in range(NPU_LANES))
            index = instr.rd % NPU_ACCS
            self.accumulators[index] = _signed(
                (self.accumulators[index] + total) & accumulator_mask, NPU_ACC_WIDTH
            )
        elif sub_opcode == NPU_VSUM:
            source = self.vector_registers[instr.operand2 & 0x7]
            total = sum(_lane(source, i) for i in range(NPU_LANES))
            index = instr.rd % NPU_ACCS
            self.accumulators[index] = _signed(
                (self.accumulators[index] + total) & accumulator_mask, NPU_ACC_WIDTH
            )
        elif sub_opcode == NPU_VMAXR:
            source = self.vector_registers[instr.operand2 & 0x7]
            best = max(_lane(source, i) for i in range(NPU_LANES))
            self._write_destination(instr, best & self.mask)
        elif sub_opcode == NPU_VDUP:
            byte = self._operand2(instr) & 0xFF
            self.vector_registers[instr.rd % NPU_VREGS] = int.from_bytes(
                bytes([byte]) * NPU_LANES, "little"
            )
        elif sub_opcode == NPU_VEXT:
            source = self.vector_registers[instr.operand2 & 0x7]
            lane = (instr.operand2 >> 4) & 0x7
            self._write_destination(instr, _lane(source, lane) & self.mask)
        elif sub_opcode == NPU_VINS:
            target = instr.rd % NPU_VREGS
            lane = (instr.operand2 >> 4) & 0x7
            byte = self._read_register(instr.operand2 & 0xF) & 0xFF
            current = self.vector_registers[target]
            self.vector_registers[target] = (
                current & ~(0xFF << (lane * 8))
            ) | (byte << (lane * 8))
        elif sub_opcode == NPU_ACLR:
            self.accumulators[instr.rd % NPU_ACCS] = 0
        elif sub_opcode == NPU_ASET:
            self.accumulators[instr.rd % NPU_ACCS] = _signed(
                self._operand2(instr), self.addr_width
            )
        elif sub_opcode == NPU_AGET:
            value = self.accumulators[instr.operand2 % NPU_ACCS]
            self._write_destination(instr, value & self.mask)
        elif sub_opcode == NPU_AGETS:
            value = self.accumulators[instr.operand2 % NPU_ACCS]
            self._write_destination(instr, _saturate(value, self.addr_width) & self.mask)
        elif sub_opcode == NPU_AQMUL:
            index = instr.rd % NPU_ACCS
            multiplier = _signed(self._operand2(instr) & 0xFFFF, 16)
            scaled = (self.accumulators[index] * multiplier + 16384) >> 15
            self.accumulators[index] = _saturate(scaled, NPU_ACC_WIDTH)
        elif sub_opcode == NPU_ARSHR:
            index = instr.rd % NPU_ACCS
            amount = self._operand2(instr) & 0x1F
            self.accumulators[index] = _rounding_shift_right(
                self.accumulators[index], amount
            )
        elif sub_opcode == NPU_NPUCFG:
            index = (int(instr.flag) << 4) | instr.rd
            if index < NPU_CFG_COUNT:
                self.npu_cfg[index] = self._operand2(instr) & self.mask
        else:
            self._write_destination(instr, self._execute_npu_engine() & self.mask)

    def step(self) -> tuple[PixelEvent, ...]:
        if self.halted:
            return ()

        if self._waiting_key_mask is not None:
            hit = self.key_mask & self._waiting_key_mask
            self.cycles += 1
            if hit:
                resume = Instruction(
                    word=0,
                    condition=0,
                    instr_class=0,
                    immediate=False,
                    opcode=0,
                    flag=self._waiting_key_flag,
                    rn=0,
                    rd=self._waiting_key_rd,
                    operand2=0,
                )
                self._write_destination(resume, hit)
                self._waiting_key_mask = None
            return ()

        instruction_address = self.pc
        word = self._fetch_word(instruction_address)
        self.pc = (self.pc + 4) & self.mask
        self.cycles += 1

        if word == 0:
            self.halted = True
            self.pc = (self.pc + 4) & self.mask
            self._trace("Halt: Encountered null instruction (0x00000000), stopping execution")
            return ()

        instr = Instruction.decode(word)
        if not self._condition_met(instr.condition):
            self.instructions_retired += 1
            return ()

        if instr.instr_class == CLASS_DP:
            self._execute_dp(instr)
            events: tuple[PixelEvent, ...] = ()
        elif instr.instr_class == CLASS_EXT:
            events = self._execute_extended(instr)
        elif instr.instr_class == CLASS_MEM:
            self._execute_memory(instr)
            events = ()
        elif instr.instr_class == CLASS_BR:
            events = self._execute_branch(instr)
        else:
            raise EmulationError(
                f"unsupported instruction class {instr.instr_class} at PC=0x{instruction_address:X}"
            )
        self.instructions_retired += 1
        return events

    def snapshot(
        self,
        *,
        mem_start: int,
        mem_end: int,
        labels: Mapping[str, int] | None = None,
    ) -> Snapshot:
        if mem_start < 0 or mem_end < mem_start or mem_end > self.mask:
            raise EmulationError(f"memory range must be within 0..{self.mask}")
        registers: dict[str, RegisterValue] = {
            f"R{index}": {"dec": value, "hex": f"{value:0{self.hex_width}X}"}
            for index, value in enumerate(self.registers)
        }
        for name, value in (("PC", self.pc), ("LE", self.led), ("HEX", self.hex)):
            registers[name] = {"dec": value, "hex": f"{value:0{self.hex_width}X}"}
        registers["CPSR"] = {"dec": None, "hex": f"{self.cpsr:08X}"}
        for index, value in enumerate(self.vector_registers):
            registers[f"Q{index}"] = {"dec": value, "hex": f"{value:016X}"}
        for index, value in enumerate(self.accumulators):
            registers[f"A{index}"] = {
                "dec": value,
                "hex": f"{value & 0xFFFF_FFFF:08X}",
            }

        memory: list[MemoryCell] = [
            {"addr": address, "dec": self.memory[address], "hex": f"{self.memory[address]:02X}"}
            for address in range(mem_start, mem_end + 1)
        ]
        framebuffer: list[MemoryCell] = [
            {"addr": address, "dec": value, "hex": f"{value:02X}"}
            for address, value in enumerate(self.framebuffer)
            if value
        ]
        return {
            "registers": registers,
            "memory": memory,
            "framebuffer": framebuffer,
            "vga_width": VGA_WIDTH,
            "vga_height": VGA_HEIGHT,
            "labels": dict(labels or {}),
            "log": "\n".join(self.log),
            "mem_start": mem_start,
            "mem_end": mem_end,
        }


def run_emulator_snapshot(
    program_bytes: bytes,
    *,
    labels: Mapping[str, int] | None = None,
    mem_start: int = 0,
    mem_end: int = 255,
    key_mask: int = 0,
    max_cycles: int = DEFAULT_MAX_CYCLES,
    addr_width: int = DEFAULT_ADDR_WIDTH,
    data_width: int = DEFAULT_DATA_WIDTH,
    trace: bool = False,
) -> Snapshot:
    _validate_configuration(
        program_bytes,
        mem_start=mem_start,
        mem_end=mem_end,
        key_mask=key_mask,
        max_cycles=max_cycles,
        addr_width=addr_width,
        data_width=data_width,
    )
    emulator = CPUEmulator(
        program_bytes,
        key_mask=key_mask,
        addr_width=addr_width,
        data_width=data_width,
        trace=trace,
    )
    while not emulator.halted and emulator.cycles < max_cycles:
        emulator.step()
        if emulator.blocked_on_keys:
            emulator.cycles = max_cycles
    if not emulator.halted:
        raise EmulationTimeoutError(f"Simulation exceeded max_cycles={max_cycles} without halting")
    return emulator.snapshot(mem_start=mem_start, mem_end=mem_end, labels=labels)


def stream_emulator_events(
    program_bytes: bytes,
    *,
    labels: Mapping[str, int] | None = None,
    mem_start: int = 0,
    mem_end: int = 255,
    key_mask: int = 0,
    max_cycles: int = DEFAULT_MAX_CYCLES,
    addr_width: int = DEFAULT_ADDR_WIDTH,
    data_width: int = DEFAULT_DATA_WIDTH,
    trace: bool = False,
    heartbeat_instructions: int = 50_000,
) -> Generator[StreamEvent]:
    _validate_configuration(
        program_bytes,
        mem_start=mem_start,
        mem_end=mem_end,
        key_mask=key_mask,
        max_cycles=max_cycles,
        addr_width=addr_width,
        data_width=data_width,
    )
    if heartbeat_instructions <= 0:
        raise EmulationError("heartbeat_instructions must be positive")
    emulator = CPUEmulator(
        program_bytes,
        key_mask=key_mask,
        addr_width=addr_width,
        data_width=data_width,
        trace=trace,
    )
    label_dict = dict(labels or {})
    yield {
        "type": "start",
        "labels": label_dict,
        "vga_width": VGA_WIDTH,
        "vga_height": VGA_HEIGHT,
    }

    live_framebuffer: dict[int, int] = {}
    next_heartbeat = heartbeat_instructions
    streamed_logs = 0
    while not emulator.halted and emulator.cycles < max_cycles:
        for event in emulator.step():
            address = event["addr"]
            color = event["color"]
            if live_framebuffer.get(address) != color:
                live_framebuffer[address] = color
                yield event
        if trace:
            while streamed_logs < len(emulator.log):
                current = tuple(emulator.log)
                if streamed_logs >= len(current):
                    break
                yield {"type": "log", "line": current[streamed_logs]}
                streamed_logs += 1
        if emulator.instructions_retired >= next_heartbeat:
            next_heartbeat += heartbeat_instructions
            yield {"type": "heartbeat"}
        if emulator.blocked_on_keys:
            emulator.cycles = max_cycles

    if not emulator.halted:
        raise EmulationTimeoutError(f"Simulation exceeded max_cycles={max_cycles} without halting")
    snapshot = emulator.snapshot(mem_start=mem_start, mem_end=mem_end, labels=label_dict)
    yield {
        "type": "snapshot",
        "registers": snapshot["registers"],
        "memory": snapshot["memory"],
        "framebuffer": snapshot["framebuffer"],
        "vga_width": snapshot["vga_width"],
        "vga_height": snapshot["vga_height"],
        "labels": snapshot["labels"],
        "mem_start": snapshot["mem_start"],
        "mem_end": snapshot["mem_end"],
    }
    yield {"type": "done"}


__all__ = [
    "CPUEmulator",
    "EmulationError",
    "EmulationTimeoutError",
    "Instruction",
    "run_emulator_snapshot",
    "stream_emulator_events",
]
