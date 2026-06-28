"""Comprehensive eltwise op support prober.

For every op it tries each (dtype x layout x memory-config) combo, records
whether the config is ACCEPTED (no error) and whether the result matches the
ttnn golden reference (PCC pass/fail). Writes a CSV incrementally so partial
results survive interruption.

Run:  python tests/ttnn/unit_tests/operations/eltwise/eltwise_support_probe.py
Env:  PROBE_DTYPES, PROBE_LAYOUTS, PROBE_MEMS to subset axes (comma separated).
"""
import os
import csv
import zlib
import math
import torch
import ttnn

# fixed seed so runs are deterministic (no borderline PCC flips between runs).
# each config is reseeded from this base + a hash of (op,dtype,layout,mem) so a
# single-op probe matches the same row in a full run. Override with PROBE_SEED.
_BASE_SEED = int(os.environ.get("PROBE_SEED", "0"))
torch.manual_seed(_BASE_SEED)

# ----------------------------------------------------------------------------- axes
ALL_DTYPES = {
    "bfloat16": ttnn.bfloat16,
    "bfloat8_b": ttnn.bfloat8_b,
    "bfloat4_b": ttnn.bfloat4_b,
    "float32": ttnn.float32,
    "int32": ttnn.int32,
    "uint32": ttnn.uint32,
    "uint16": ttnn.uint16,
    "uint8": ttnn.uint8,
}
ALL_LAYOUTS = {"tile": ttnn.TILE_LAYOUT, "rm": ttnn.ROW_MAJOR_LAYOUT}
# mem axis is kept as string tokens; sharded configs are resolved per-shape at runtime
# so they work on any hardware (see make_mem).
ALL_MEMS = {k: k for k in ("dram", "l1", "height", "width", "block")}

# minimum tensor: a single 32x32 tile -> keeps the full sweep fast and lets every
# sharding strategy map onto a single core regardless of the device's grid size.
SHAPE = (1, 1, 32, 32)
# ops that can't run on a single 32x32 tile: GLU splits the last dim in half and each
# half must be a full tile (>=32) in TILE layout, so the last dim must be >=64.
PER_OP_SHAPE = {
    "glu": (1, 1, 32, 64),
    "geglu": (1, 1, 32, 64),
    "reglu": (1, 1, 32, 64),
    "swiglu": (1, 1, 32, 64),
}
_SHARD_STRATEGY = {
    "height": ttnn.ShardStrategy.HEIGHT,
    "width": ttnn.ShardStrategy.WIDTH,
    "block": ttnn.ShardStrategy.BLOCK,
}


def make_mem(token, shape, device):
    """Resolve a mem token to a memory_config. Sharded tokens build a 1-core shard
    sized to the tensor (one tile here), valid on any hardware."""
    if token == "dram":
        return ttnn.DRAM_MEMORY_CONFIG
    if token == "l1":
        return ttnn.L1_MEMORY_CONFIG
    # a sharded tensor flattens to 2D: physical height = product of all leading dims,
    # physical width = last dim. Using shape[-2] alone breaks for >1 leading dim
    # (e.g. a (2,1,32,32) gradient has physical height 64, not 32).
    H = 1
    for d in shape[:-1]:
        H *= d
    W = shape[-1]
    return ttnn.create_sharded_memory_config(
        shape=(H, W),
        core_grid=ttnn.CoreGrid(y=1, x=1),
        strategy=_SHARD_STRATEGY[token],
        orientation=ttnn.ShardOrientation.ROW_MAJOR,
    )


def _is_sharded(mem):
    return isinstance(mem, str) and mem in _SHARD_STRATEGY


def _subset(env, full):
    v = os.environ.get(env)
    if not v:
        return full
    return {k: full[k] for k in v.split(",") if k in full}


DTYPES = _subset("PROBE_DTYPES", ALL_DTYPES)
LAYOUTS = _subset("PROBE_LAYOUTS", ALL_LAYOUTS)
MEMS = _subset("PROBE_MEMS", ALL_MEMS)

# ----------------------------------------------------------------------------- op list
OPS = """
abs acos acosh add addalpha addcdiv addcmul angle asin asinh assign atan atan2 atanh
bias_gelu bitwise_and bitwise_not bitwise_or bitwise_xor
cbrt ceil celu clamp clip complex_tensor conj cos cosh
deg2rad digamma divide
elu eq eqz erf erfc erfinv exp exp2 expm1
fill floor fmod frac
ge geglu gelu gez glu gt gtz
hardmish hardshrink hardsigmoid hardswish hardtanh heaviside hypot
i0 i1 identity imag isclose isfinite isinf isnan isneginf isposinf
ldexp le leaky_relu lerp lez lgamma log log_sigmoid log1p log10 log2
logaddexp logaddexp2 logical_and logical_not logical_or logical_xor logit ltz
mac max maximum mean min minimum mish mul multigammaln multiply
ne neg nextafter nez
polar pow prod prelu
rad2deg rdiv real reciprocal reglu relu relu6 relu_max relu_min remainder round
rpow rsqrt rsub
selu sign signbit sigmoid sigmoid_accurate silu sin sinh softplus softshrink softsign
sqrt square squared_difference std std_hw sub subalpha subtract swiglu swish
tan tanh tanhshrink threshold tril triu trunc
var var_hw where xielu xlogy
abs_bw acos_bw acosh_bw add_bw addalpha_bw addcdiv_bw addcmul_bw asin_bw asinh_bw atan_bw
atan2_bw atanh_bw bias_gelu_bw ceil_bw cos_bw cosh_bw deg2rad_bw digamma_bw
erf_bw erfc_bw erfinv_bw exp_bw exp2_bw expm1_bw fill_bw fill_zero_bw floor_bw fmod_bw frac_bw
gelu_bw hardshrink_bw hardsigmoid_bw hardswish_bw hypot_bw i0_bw ldexp_bw lerp_bw lgamma_bw
log_bw log_sigmoid_bw log1p_bw log10_bw log2_bw logaddexp_bw logaddexp2_bw logit_bw
max_bw min_bw mul_bw multigammaln_bw neg_bw pow_bw rad2deg_bw reciprocal_bw relu_bw relu6_bw
remainder_bw round_bw rsqrt_bw rsub_bw selu_bw sigmoid_bw sign_bw silu_bw sin_bw sinh_bw
softshrink_bw softsign_bw sqrt_bw square_bw squared_difference_bw sub_bw subalpha_bw
tan_bw tanh_bw tanhshrink_bw trunc_bw where_bw xlogy_bw
add_ bias_gelu_ div_ divide_ eq_ ge_ gt_ ldexp_ le_ logaddexp_ logaddexp2_ logical_and_
logical_not_ logical_or_ logical_xor_ mul_ multiply_ ne_ rsub_ squared_difference_ sub_ subtract_
lt lt_ div div_no_nan floor_div gcd lcm outer polyval polygamma snake_beta
bitwise_left_shift bitwise_right_shift logical_left_shift logical_right_shift
normalize_global normalize_hw alt_complex_rotate90 is_imag is_real bitcast unary_chain
quantize dequantize requantize
div_bw div_no_nan_bw celu_bw elu_bw hardtanh_bw leaky_relu_bw threshold_bw softplus_bw
rpow_bw rdiv_bw logiteps_bw polygamma_bw prod_bw assign_bw
angle_bw conj_bw imag_bw real_bw polar_bw concat_bw repeat_bw
""".split()

# ----------------------------------------------------------------------------- per-op spec
# kind: u=unary, b=binary, t=ternary. params: extra scalar args appended after tensors.
BINARY = {
    "add", "addalpha", "atan2", "bias_gelu", "bitwise_and", "bitwise_or", "bitwise_xor",
    "div", "divide", "eq", "fmod", "ge", "gt", "hypot", "isclose", "ldexp", "le",
    "logaddexp", "logaddexp2", "logical_and", "logical_or", "logical_xor", "lt", "maximum",
    "minimum", "mul", "multiply", "ne", "nextafter", "pow", "remainder",
    "squared_difference", "sub", "subalpha", "subtract", "xlogy", "rsub",
    "div_no_nan", "floor_div", "gcd", "lcm", "outer",
    "bitwise_left_shift", "bitwise_right_shift", "logical_left_shift", "logical_right_shift",
}
TERNARY = {"addcdiv", "addcmul", "lerp", "mac", "where", "snake_beta"}
REDUCTION = {"max", "min", "mean", "prod", "sum", "var", "std", "std_hw", "var_hw"}
# complex consumers take one ComplexTensor; complex_tensor builds one from (real, imag)
COMPLEX_CONSUMERS = {"angle", "real", "imag", "conj", "polar", "is_imag", "is_real"}
GLU = {"glu", "geglu", "reglu", "swiglu"}
# quantization ops with (scale, zero_point[, out_scale, out_zp]) signatures
QUANT = {"quantize", "dequantize", "requantize"}
# backward ops whose call signature differs from the generic (grad + base-arity) rule.
# tensors = # of input tensors after grad; scalars = trailing scalar args.
BW_OVERRIDE = {
    "pow_bw": {"tensors": 1, "scalars": [2.0]},          # grad, input, exponent
    "logit_bw": {"tensors": 1, "scalars": []},           # grad, input
    "fill_bw": {"tensors": 1, "scalars": []},            # grad, input
    "max_bw": {"tensors": 2, "scalars": []},             # grad, input, other
    "min_bw": {"tensors": 2, "scalars": []},             # grad, input, other
    "addcdiv_bw": {"tensors": 3, "scalars": [0.5]},      # grad, input, t1, t2, value
    "addcmul_bw": {"tensors": 3, "scalars": [0.5]},      # grad, input, t1, t2, value
    "celu_bw": {"tensors": 1, "scalars": [], "kw": {"alpha": 1.0}},
    "elu_bw": {"tensors": 1, "scalars": [], "kw": {"alpha": 1.0}},
    "hardtanh_bw": {"tensors": 1, "scalars": [], "kw": {"min": -1.0, "max": 1.0}},
    "leaky_relu_bw": {"tensors": 1, "scalars": [], "kw": {"negative_slope": 0.1}},
    "threshold_bw": {"tensors": 1, "scalars": [0.5, 0.0]},  # grad, input, min, max (positional)
    "softplus_bw": {"tensors": 1, "scalars": [], "kw": {"beta": 1.0, "threshold": 20.0}},
    "rpow_bw": {"tensors": 1, "scalars": [2.0]},         # grad, input, exponent (positional)
    "rdiv_bw": {"tensors": 1, "scalars": [2.0]},         # grad, input, scalar (positional)
    "logiteps_bw": {"tensors": 1, "scalars": [], "kw": {"eps": 1e-6}},
    "polygamma_bw": {"tensors": 1, "scalars": [1]},      # grad, input, n (positional)
    "prod_bw": {"tensors": 1, "scalars": []},            # grad, input
    "assign_bw": {"tensors": 1, "scalars": []},          # grad, input
    "div_no_nan_bw": {"tensors": 1, "scalars": [2.0]},   # grad, input, scalar (no TT overload)
}
# unary ops that take POSITIONAL scalar params
UPARAMS = {
    "clamp": (-0.5, 0.5), "clip": (-0.5, 0.5),
    "leaky_relu": (0.1,), "heaviside": (0.5,),
    "relu_max": (0.5,), "relu_min": (0.5,), "fill": (1.0,),
    "threshold": (0.5, 0.0), "rpow": (2.0,), "round": (), "polygamma": (1,),
    "rdiv": (2.0,), "prelu": (0.25,),
    "polyval": ([1.0, 2.0, 3.0],),
}
# unary ops that need KEYWORD-only scalar params
UKW = {
    "elu": {"alpha": 1.0}, "celu": {"alpha": 1.0},
    "hardshrink": {"lambd": 0.5}, "softshrink": {"lambd": 0.5},
    "logit": {"eps": 1e-6},
}
# binary ops needing a trailing scalar
BPARAMS = {"addalpha": (1.0,), "subalpha": (1.0,), "isclose": ()}


def quantize_ref(t, dtype):
    """Round the torch reference to the device dtype so PCC measures kernel error,
    not input-quantisation noise (matches the convention in ttnn unit tests)."""
    if dtype == ttnn.bfloat16:
        return t.to(torch.bfloat16).to(torch.float32)
    return t  # float32/int kept as-is; bfloat8_b has no torch repr (tolerance handles)


# ops whose valid input domain differs from the generic (0.1, 0.85)
DOMAIN = {
    "acosh": (1.1, 5.0),       # acosh defined for x >= 1
    "multigammaln": (1.6, 5.0),  # requires x > (p-1)/2
    "cosh": (-3.0, 3.0),
    "lgamma": (0.5, 5.0),
    "digamma": (0.5, 5.0),
    "prod": (0.95, 1.05),  # product over a full tile underflows to 0 outside ~1.0
}


def build(name, dtype, layout, mem, device, shape=None, force_interleaved=False):
    if shape is None:
        shape = PER_OP_SHAPE.get(name, SHAPE)
    if dtype in _INT_DTYPES:
        t = torch.randint(1, 50, shape, dtype=torch.int32)
    else:
        lo, hi = DOMAIN.get(name, (0.1, 0.85))  # safe default for log/sqrt/acos/atanh
        t = torch.empty(shape).uniform_(lo, hi)
    # A broadcast operand (e.g. a (1,1,1,1) scalar) can't be sharded to its own shape:
    # the shard would be sub-tile (1x1 / 1x32 / 32x1) and rejected in TILE layout. Real
    # broadcasting keeps such operands interleaved while the primary stays sharded.
    if force_interleaved and _is_sharded(mem):
        mem_cfg = ttnn.L1_MEMORY_CONFIG
    else:
        mem_cfg = make_mem(mem, shape, device) if isinstance(mem, str) else mem
    tt = ttnn.from_torch(t, dtype=dtype, layout=layout, device=device, memory_config=mem_cfg)
    return quantize_ref(t, dtype), tt


# forward ops with no registered ttnn golden -> supply the torch reference manually
MANUAL_GOLDEN = {
    "i1": lambda a: torch.special.i1(a),
    "bitwise_not": lambda a: torch.bitwise_not(a.to(torch.int64)),
    "where": lambda c, t, f: torch.where(c != 0, t, f),
    # snake_beta(x, alpha, beta) = x + sin(alpha*x)^2 / beta (no registered golden)
    "snake_beta": lambda x, a, b: x + torch.sin(a * x) ** 2 / b,
}
# backward ops with no usable registered golden: (grad, *inputs) -> grad wrt first input
MANUAL_BW_GOLDEN = {
    "where": lambda g, c, t, f: torch.where(c != 0, g, torch.zeros_like(g)),
}
# reductions/cumulative with no registered golden (probed at dim=-1)
MANUAL_REDUCE = {
    "prod": lambda a: torch.prod(a, dim=-1, keepdim=True),
    "std_hw": lambda a: torch.std(a, dim=(-2, -1), keepdim=True, unbiased=False),
    "var_hw": lambda a: torch.var(a, dim=(-2, -1), keepdim=True, unbiased=False),
}


def _real_view(x):
    """Flatten a (possibly complex) tensor to a real view so PCC can compare it."""
    if torch.is_tensor(x) and torch.is_complex(x):
        return torch.view_as_real(x.resolve_conj())  # conj() returns a lazy view
    return x


def _complex_to_torch(out):
    """ttnn ComplexTensor -> torch complex; plain ttnn tensor -> torch tensor."""
    if not torch.is_tensor(out) and hasattr(out, "real") and hasattr(out, "imag"):
        return torch.complex(to_t(out.real).float(), to_t(out.imag).float())
    return to_t(out)


def to_t(x):
    return ttnn.to_torch(x)


_INT_DTYPES = (ttnn.int32, ttnn.uint32, ttnn.uint16, ttnn.uint8)


def call_golden(gf, args, device, dtype=None, kw=None):
    if gf is None:
        return None
    kw = kw or {}

    def _try(a):
        try:
            return gf(*a, **kw)
        except TypeError:
            try:
                return gf(*a, device=device, **kw)
            except Exception:
                return None
        except Exception:
            return None

    r = _try(args)
    # Fallback for int dtypes of float ops: torch goldens reject int input, so run
    # the golden on int->float-casted inputs, then truncate back to int to match the
    # device's integer output, and compare.
    if r is None and dtype in _INT_DTYPES:
        fargs = [x.float() if (torch.is_tensor(x) and not x.is_floating_point()) else x for x in args]
        r = _try(fargs)
        if torch.is_tensor(r) and r.is_floating_point():
            r = r.to(torch.int32)
    return r


def _corr(g, o):
    """Pearson correlation of two flat tensors, or None when undefined (zero variance)."""
    try:
        gc, oc = g - g.mean(), o - o.mean()
        denom = gc.norm() * oc.norm()
        if denom == 0:
            return None
        return max(-1.0, min(1.0, float((gc @ oc) / denom)))
    except Exception:
        return None


# ULP is only meaningful for float dtypes. bfloat8_b shares bfloat16's resolution
# (block-shared exponent), so it is measured in bf16; bf4_b is too coarse to map to a
# torch dtype, and integers have no ULP -> these report blank.
_ULP_TORCH = {ttnn.bfloat16: torch.bfloat16, ttnn.bfloat8_b: torch.bfloat16, ttnn.float32: torch.float32}


def _ulp_size(x):
    """Length of one ULP per element of x, measured at x's own dtype (Goldberg)."""
    abs_x = torch.abs(x)
    nxt = torch.nextafter(abs_x, torch.tensor(math.inf, dtype=x.dtype))
    u = nxt - abs_x
    dmax = torch.finfo(x.dtype).max
    max_eps = dmax - torch.nextafter(torch.tensor(dmax, dtype=x.dtype), torch.tensor(-math.inf, dtype=x.dtype))
    return torch.where(abs_x == dmax, max_eps, u)


def max_ulp(golden, got, dtype):
    """Max per-element error in ULP (|got-golden| / ULP(golden)) at the device's
    float resolution, or None when ULP is undefined for this dtype."""
    td = _ULP_TORCH.get(dtype)
    if td is None:
        return None
    try:
        g = golden.detach().to(td).flatten()
        o = got.detach().to(td).flatten()
        if g.shape != o.shape:
            return None
        mask = torch.isfinite(g) & torch.isfinite(o)
        if mask.sum() == 0:
            return None
        g, o = g[mask], o[mask]
        delta = (o - g).abs() / _ulp_size(g)
        delta = delta[torch.isfinite(delta)]
        if delta.numel() == 0:
            return None
        return float(delta.max())
    except Exception:
        return None


def pcc_ok(golden, got, dtype):
    """Return (verdict, pcc, ulp): Pearson correlation and max ULP error (or None)."""
    ulp = max_ulp(golden, got, dtype)
    try:
        g = golden.to(torch.float32).flatten()
        o = got.to(torch.float32).flatten()
        if g.shape != o.shape:
            return "shape?", None, ulp
        if dtype in _INT_DTYPES:
            verdict = "pass" if torch.equal(golden.to(torch.int64), got.to(torch.int64)) else "fail"
            return verdict, _corr(g, o), ulp
        mask = torch.isfinite(g) & torch.isfinite(o)
        if mask.sum() == 0:
            return "nan", None, ulp
        g, o = g[mask], o[mask]
        if g.numel() < 2 or torch.allclose(g, o, atol=1e-2, rtol=1e-2):
            return "pass", _corr(g, o), ulp
        gc, oc = g - g.mean(), o - o.mean()
        denom = gc.norm() * oc.norm()
        if denom == 0:
            return ("pass" if torch.allclose(g, o, atol=1e-2) else "fail"), None, ulp
        pcc = float((gc @ oc) / denom)
        thr = {ttnn.bfloat8_b: 0.97, ttnn.bfloat4_b: 0.90}.get(dtype, 0.99)
        return ("pass" if pcc >= thr else f"fail({pcc:.3f})"), pcc, ulp
    except Exception as e:
        return f"pcc_err:{str(e)[:30]}", None, ulp


# broadcast patterns applied to the non-primary operand(s) of binary/ternary ops.
# "none" keeps the full shape (the existing tensor-tensor case); the others shrink a
# dim to 1 so the device must broadcast it back up to the primary's shape.
BCASTS = ("none", "scalar", "row", "col")


def _bcast_shape(base, bcast):
    """Shape of a broadcastable operand for a given pattern, relative to the op shape."""
    s = PER_OP_SHAPE.get(base, SHAPE)
    if bcast == "scalar":
        return (1, 1, 1, 1)
    if bcast == "row":  # collapse the height dim -> one row broadcast across rows
        return (1, 1, 1, s[-1])
    if bcast == "col":  # collapse the width dim -> one column broadcast across cols
        return (1, 1, s[-2], 1)
    return None  # "none": use the operand's default (full) shape


def build_args(base, dtype, layout, mem, device, bcast="none"):
    """Construct (tt_args, tt_kwargs, torch_args) mirroring the base op's arity.

    The first operand always uses the full op shape; for binary/ternary ops the
    remaining operands use the broadcast shape selected by `bcast`."""
    a_t, a = build(base, dtype, layout, mem, device)
    bsh = _bcast_shape(base, bcast)
    fi = bcast != "none"  # broadcast operands go interleaved (can't shard a sub-tile)
    if base in TERNARY:
        b_t, b = build(base, dtype, layout, mem, device, shape=bsh, force_interleaved=fi)
        c_t, c = build(base, dtype, layout, mem, device, shape=bsh, force_interleaved=fi)
        return [a, b, c], {}, [a_t, b_t, c_t]
    if base in BINARY:
        b_t, b = build(base, dtype, layout, mem, device, shape=bsh, force_interleaved=fi)
        p = BPARAMS.get(base, ())
        return [a, b, *p], {}, [a_t, b_t, *p]
    if base in UKW:
        kw = UKW[base]
        return [a], dict(kw), [a_t, *kw.values()]
    if base in UPARAMS:
        p = UPARAMS[base]
        return [a, *p], {}, [a_t, *p]
    return [a], {}, [a_t]


def finalize(out, golden, dtype):
    if isinstance(out, (list, tuple)):
        out = out[0]
    got = to_t(out)
    if golden is None:
        return "OK", "no-golden", None, None
    if isinstance(golden, (list, tuple)):
        golden = golden[0]
    verdict, pcc, ulp = pcc_ok(golden, got, dtype)
    return "OK", verdict, pcc, ulp


def _grad_clone(x):
    if torch.is_tensor(x) and x.is_floating_point():
        return x.clone().detach().requires_grad_(True)
    return x


def _trunc_int(v):
    if torch.is_tensor(v) and v.is_floating_point():
        return v.to(torch.int32)
    if isinstance(v, (list, tuple)):
        return [_trunc_int(e) for e in v]
    return v


def call_bw_golden(gf, grad, inputs, scalars, device, dtype, kw=None):
    """Backward golden with an int fallback. Autograd goldens need float inputs with
    requires_grad, which int tensors can't have. For int dtypes that return no golden,
    re-run on float-casted inputs (grad cast to float, inputs float+requires_grad), then
    truncate the resulting gradient back to int to match the device's int output."""
    base_in = [_grad_clone(x) for x in inputs]
    kw = kw or {}
    golden = call_golden(gf, (grad, *base_in, *scalars), device, kw=kw)
    # some goldens take the keyword params positionally -> retry with values appended
    if golden is None and kw:
        golden = call_golden(gf, (grad, *base_in, *scalars, *kw.values()), device)
    if golden is not None or dtype not in _INT_DTYPES:
        return golden
    g_f = grad.float() if (torch.is_tensor(grad) and not grad.is_floating_point()) else grad
    in_f = [
        (x.float().clone().detach().requires_grad_(True) if (torch.is_tensor(x) and not x.is_floating_point()) else _grad_clone(x))
        for x in inputs
    ]
    r = call_golden(gf, (g_f, *in_f, *scalars), device, kw=kw)
    if r is None and kw:
        r = call_golden(gf, (g_f, *in_f, *scalars, *kw.values()), device)
    return _trunc_int(r) if r is not None else None


def run_op(name, fn, gf, dtype, layout, mem, device, bcast="none"):
    # resolve mode: forward / backward (_bw) / in-place (trailing _)
    mode, base = "fwd", name
    if name.endswith("_bw"):
        mode, base = "bw", name[:-3]
    elif name.endswith("_"):
        mode, base = "ip", name[:-1]

    # assign: unary copy op that requires memory_config; golden is identity
    if base == "assign" and mode == "fwd":
        a_t, a = build(base, dtype, layout, mem, device)
        out = fn(a, memory_config=make_mem(mem, SHAPE, device) if isinstance(mem, str) else mem)
        return finalize(out, a_t, dtype)

    # bitcast: reinterpret bits to the same dtype -> identity
    if base == "bitcast" and mode == "fwd":
        a_t, a = build(base, dtype, layout, mem, device)
        out = fn(a, dtype)
        return finalize(out, a_t, dtype)

    # quantization: (scale, zero_point) or (in_scale, in_zp, out_scale, out_zp).
    # ttnn has no registered golden, so the affine quant math is supplied here.
    if base in QUANT and mode == "fwd":
        a_t, a = build(base, dtype, layout, mem, device)
        sc = (0.1, 0, 0.2, 0) if base == "requantize" else (0.1, 0)
        out = fn(a, *sc)
        af = a_t.float()
        if base == "quantize":          # float -> int: round(x/scale) + zp
            golden = torch.round(af / sc[0]) + sc[1]
        elif base == "dequantize":      # int -> float: (x - zp) * scale
            golden = (af - sc[1]) * sc[0]
        else:                           # requantize: int -> int (deq by in_*, then q by out_*)
            golden = torch.round((af - sc[1]) * sc[0] / sc[2]) + sc[3]
        return finalize(out, golden, dtype)

    # outer product: needs two row vectors (1,1,1,W) -> (1,1,W,W), not a full tile
    if base == "outer" and mode == "fwd":
        ashape = (1, 1, 1, SHAPE[-1])
        a_t, a = build("outer", dtype, layout, mem, device, shape=ashape)
        b_t, b = build("outer", dtype, layout, mem, device, shape=ashape)
        out = fn(a, b)
        golden = call_golden(gf, (a_t, b_t), device, dtype)
        return finalize(out, golden, dtype)

    # unary_chain: apply a chain of unary ops (probed with a single RELU)
    if base == "unary_chain" and mode == "fwd":
        a_t, a = build(base, dtype, layout, mem, device)
        out = fn(a, [ttnn.UnaryWithParam(ttnn.UnaryOpType.RELU)])
        return finalize(out, torch.relu(a_t), dtype)

    # concat_bw(grad, a, b, dim=0): grad is the concatenation of the two inputs along dim
    if name == "concat_bw":
        a_t, a = build("concat", dtype, layout, mem, device)
        b_t, b = build("concat", dtype, layout, mem, device)
        g_t, g = build("concat", dtype, layout, mem, device, shape=(2, *SHAPE[1:]))
        out = fn(g, a, b, 0)

        def _cgolden(gt, at, bt):
            try:
                r = gf(gt, at, bt, 0) if gf else None
                return r[0] if isinstance(r, (list, tuple)) else r
            except Exception:
                return None

        golden = _cgolden(g_t, _grad_clone(a_t), _grad_clone(b_t))
        # the autograd golden can't run on int tensors; the concat gradient is purely
        # structural (a slice of grad), so run it in float and truncate back to int.
        if golden is None and dtype in _INT_DTYPES:
            af = a_t.float().clone().detach().requires_grad_(True)
            bf = b_t.float().clone().detach().requires_grad_(True)
            r = _cgolden(g_t.float(), af, bf)
            golden = _trunc_int(r) if r is not None else None
        return finalize(out, golden, dtype)

    # repeat_bw(grad, input, repeats): backward of repeat. Repeat dim0 x2 -> the input
    # gradient is the sum of the two repeated copies of grad.
    if name == "repeat_bw":
        a_t, a = build("repeat", dtype, layout, mem, device)
        g_t, g = build("repeat", dtype, layout, mem, device, shape=(2, *SHAPE[1:]))
        out = fn(g, a, ttnn.Shape([2, 1, 1, 1]))
        return finalize(out, g_t.sum(dim=0, keepdim=True), dtype)

    # complex backward: fn(grad, complex_input, memory_config=...). grad is real for
    # angle/real/imag, complex for conj/polar. The torch golden returns the gradient
    # w.r.t the complex input as [real | imag] concatenated on the last dim, so the
    # device ComplexTensor output is compared in the same cat([real, imag], -1) form.
    if mode == "bw" and base in COMPLEX_CONSUMERS:
        mem_cfg = make_mem(mem, SHAPE, device) if isinstance(mem, str) else mem
        re_ref, re = build(base, dtype, layout, mem, device)
        im_ref, im = build(base, dtype, layout, mem, device)
        c = ttnn.complex_tensor(re, im)
        if base in ("conj", "polar"):  # grad is a ComplexTensor
            gr_ref, gr = build(base, dtype, layout, mem, device)
            gi_ref, gi = build(base, dtype, layout, mem, device)
            grad = ttnn.complex_tensor(gr, gi)
            grad_ref = torch.complex(gr_ref.float(), gi_ref.float())
        else:  # angle/real/imag: grad is a real tensor
            grad_ref, grad = build(base, dtype, layout, mem, device)
        out = fn(grad, c, memory_config=mem_cfg)
        o0 = out[0] if isinstance(out, (list, tuple)) else out
        got = torch.cat([to_t(o0.real).float(), to_t(o0.imag).float()], dim=-1)
        cin = torch.complex(re_ref.float(), im_ref.float()).detach().requires_grad_(True)
        try:
            golden = gf(grad_ref, cin) if gf else None
            if isinstance(golden, (list, tuple)):
                golden = golden[0]
            if torch.is_tensor(golden) and torch.is_complex(golden):
                golden = torch.cat([golden.real, golden.imag], dim=-1)
        except Exception:
            golden = None
        if golden is None:
            return "OK", "no-golden", None, None
        verdict, pcc, ulp = pcc_ok(golden, got, dtype)
        return "OK", verdict, pcc, ulp

    # complex producer: complex_tensor(real, imag) -> ComplexTensor; golden = re/im roundtrip
    if base == "complex_tensor":
        re_ref, re = build(base, dtype, layout, mem, device)
        im_ref, im = build(base, dtype, layout, mem, device)
        out = ttnn.complex_tensor(re, im)
        got = _complex_to_torch(out)
        golden = torch.complex(re_ref.float(), im_ref.float())
        verdict, pcc, ulp = pcc_ok(_real_view(golden), _real_view(got), dtype)
        return "OK", verdict, pcc, ulp

    # complex consumers: take one ComplexTensor built from (real, imag)
    if base in COMPLEX_CONSUMERS:
        re_ref, re = build(base, dtype, layout, mem, device)
        im_ref, im = build(base, dtype, layout, mem, device)
        c = ttnn.complex_tensor(re, im)
        out = fn(c)
        cin = torch.complex(re_ref.float(), im_ref.float())
        if base == "polar":  # golden is torch.polar(abs, angle) (two positional args)
            golden = torch.polar(re_ref.float(), im_ref.float())
        elif base == "is_real":  # ttnn golden calls a nonexistent torch.is_real
            golden = (cin.imag == 0).float()
        elif base == "is_imag":
            golden = (cin.real == 0).float()
        else:
            golden = call_golden(gf, (cin,), device)
        if golden is None:
            return "OK", "no-golden", None, None
        verdict, pcc, ulp = pcc_ok(_real_view(golden), _real_view(_complex_to_torch(out)), dtype)
        return "OK", verdict, pcc, ulp

    # backward ops with an op-specific signature (extra tensors / trailing scalars).
    # checked before the reduction smoke path so max_bw/min_bw use their real signature.
    if mode == "bw" and name in BW_OVERRIDE:
        spec = BW_OVERRIDE[name]
        g_t, g = build(base, dtype, layout, mem, device)
        tt_in, torch_in = [], []
        bsh = _bcast_shape(base, bcast)
        fi = bcast != "none"  # broadcast operands go interleaved (can't shard a sub-tile)
        for i in range(spec["tensors"]):
            # first tensor (the primary input) keeps full shape; broadcast the rest
            t_t, t = build(
                base, dtype, layout, mem, device,
                shape=(bsh if i >= 1 else None), force_interleaved=(fi and i >= 1),
            )
            tt_in.append(t)
            torch_in.append(_grad_clone(t_t))
        sc = spec["scalars"]
        kw = spec.get("kw", {})
        out = fn(g, *tt_in, *sc, **kw)
        golden = call_bw_golden(gf, g_t, torch_in, sc, device, dtype, kw)
        # prod_bw (all dims) has no registered golden. The kernel computes
        # grad_input_i = grad[0] * prod(input) / input_i (it fills with grad's first value).
        if golden is None and name == "prod_bw":
            x = torch_in[0].detach().double()
            golden = (g_t.flatten()[0].double() * torch.prod(x) / x).to(torch.float32)
        return finalize(out, golden, dtype)

    # GLU family: fn(input, dim); golden(input, dim). dim=-1 (last dim must be even)
    if base in GLU:
        a_ref, a = build(base, dtype, layout, mem, device)
        out = fn(a, -1)
        golden = call_golden(gf, (a_ref, -1), device, dtype)
        return finalize(out, golden, dtype)

    # reductions: probe at dim=-1
    if base in REDUCTION:
        a_ref, a = build(base, dtype, layout, mem, device)
        # A reduced output (e.g. prod -> [...,1]) can't be re-sharded onto the same
        # single-core grid as the input, so route reduced results to interleaved L1.
        out_kw = {"memory_config": ttnn.L1_MEMORY_CONFIG} if _is_sharded(mem) else {}
        if base in ("std_hw", "var_hw"):
            out = fn(a, **out_kw)
        else:
            out = fn(a, dim=-1, keepdim=True, **out_kw)
        if base in MANUAL_REDUCE:
            try:
                golden = MANUAL_REDUCE[base](a_ref)
            except Exception:
                golden = None
        else:
            try:
                golden = gf(a_ref, dim=-1, keepdim=True) if gf else None
            except Exception:
                golden = None
        return finalize(out, golden, dtype)

    tt_args, tt_kw, torch_args = build_args(base, dtype, layout, mem, device, bcast)
    if mode == "bw":
        g_t, g = build(base, dtype, layout, mem, device)
        out = fn(g, *tt_args, **tt_kw)
        if base in MANUAL_BW_GOLDEN:
            try:
                golden = MANUAL_BW_GOLDEN[base](g_t, *torch_args)
            except Exception:
                golden = None
        else:
            # backward goldens run torch autograd internally -> inputs need requires_grad
            golden = call_bw_golden(gf, g_t, torch_args, (), device, dtype)
    else:  # forward or in-place (same call signature as base)
        out = fn(*tt_args, **tt_kw)
        if base in MANUAL_GOLDEN:
            try:
                golden = MANUAL_GOLDEN[base](*torch_args)
            except Exception:
                golden = None
        else:
            golden = call_golden(gf, tuple(torch_args), device, dtype)
    return finalize(out, golden, dtype)


_HERE = os.path.dirname(__file__)
CSV_PATH = os.path.join(_HERE, "eltwise_support_matrix.csv")  # stable "latest" path
HISTORY_DIR = os.path.join(_HERE, "history")  # per-day dated CSVs live here
HEADER = ["op", "dtype", "layout", "mem", "bcast", "accepted", "pcc_or_reason", "input_range", "pcc", "ulp"]


def bcast_list(name):
    """Broadcast patterns to probe for an op. Only binary/ternary ops broadcast a
    non-primary operand; everything else (and `outer`, which takes 1-D vectors) is
    'none' only."""
    base = name
    if name.endswith("_bw"):
        base = name[:-3]
    elif name.endswith("_"):
        base = name[:-1]
    if base == "outer":
        return ["none"]
    if base in BINARY or base in TERNARY:
        return list(BCASTS)
    return ["none"]


def dated_csv_path(day=None):
    """Path for a per-day CSV, e.g. history/eltwise_support_matrix_2026-06-28.csv."""
    import datetime

    day = day or datetime.date.today().isoformat()
    return os.path.join(HISTORY_DIR, f"eltwise_support_matrix_{day}.csv")


def input_range(name, dtype):
    """The value range fed to the tensors for this (op, dtype), mirroring build()."""
    base = name
    if name.endswith("_bw"):
        base = name[:-3]
    elif name.endswith("_"):
        base = name[:-1]
    if dtype in _INT_DTYPES:
        return "[1..49]"  # torch.randint(1, 50) -> integers 1..49 inclusive
    lo, hi = DOMAIN.get(base, (0.1, 0.85))
    return f"[{lo}..{hi}]"


def _fmt_pcc(pcc):
    return "" if pcc is None else f"{pcc:.6f}"


def _fmt_ulp(u):
    return "" if u is None else f"{u:.3f}"


def probe_one(name, w, f, device):
    fn = getattr(ttnn, name, None)
    if fn is None or not callable(fn):
        w.writerow([name, "-", "-", "-", "none", "NO_OP", "not in ttnn", "", "", ""])
        f.flush()
        return
    try:
        gf = ttnn.get_golden_function(fn)
    except Exception:
        gf = None
    bcasts = bcast_list(name)
    for ln, layout in LAYOUTS.items():
        for mn, mem in MEMS.items():
            for dn, dtype in DTYPES.items():
                for bc in bcasts:
                    # reseed per-config so inputs are identical whether this op is probed
                    # alone (--op) or as part of a full run, independent of iteration order.
                    # the non-broadcast ("none") key omits the bcast token so existing
                    # tensor-tensor rows reproduce byte-for-byte with earlier runs.
                    key = f"{name}/{dn}/{ln}/{mn}" + ("" if bc == "none" else f"/{bc}")
                    torch.manual_seed(zlib.crc32(key.encode()) ^ _BASE_SEED)
                    pcc = ulp = None
                    try:
                        acc, detail, pcc, ulp = run_op(name, fn, gf, dtype, layout, mem, device, bc)
                    except Exception as e:
                        # collapse to a single CSV-safe line; drop the volatile backtrace
                        # (pointer addresses change every process run -> non-deterministic).
                        acc = "FAIL"
                        msg = str(e).split("backtrace")[0]
                        detail = " | ".join(s.strip() for s in msg.strip().splitlines() if s.strip()).rstrip(" |")
                    w.writerow(
                        [name, dn, ln, mn, bc, acc, detail, input_range(name, dtype), _fmt_pcc(pcc), _fmt_ulp(ulp)]
                    )
                    f.flush()


def main():
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--op", default=None, help="probe a single op and append")
    ap.add_argument("--list-ops", action="store_true")
    ap.add_argument(
        "--dated",
        action="store_true",
        help="write a per-day CSV under history/ (eltwise_support_matrix_YYYY-MM-DD.csv) "
        "and also refresh the stable eltwise_support_matrix.csv",
    )
    ap.add_argument("--out", default=None, help="explicit output CSV path (overrides default)")
    args = ap.parse_args()

    if args.list_ops:
        print(" ".join(OPS))
        return

    # resolve output path: --out wins, then --dated (per-day file), else stable default
    if args.out:
        out_path = args.out
    elif args.dated:
        os.makedirs(HISTORY_DIR, exist_ok=True)
        out_path = dated_csv_path()
    else:
        out_path = CSV_PATH

    mode = "a" if args.op else "w"
    device = ttnn.open_device(device_id=0)
    f = open(out_path, mode, newline="")
    w = csv.writer(f)
    if mode == "w":
        w.writerow(HEADER)
    try:
        targets = [args.op] if args.op else OPS
        for name in targets:
            probe_one(name, w, f, device)
            print(f"  done {name}", flush=True)
    finally:
        f.close()
        ttnn.close_device(device)

    # keep a stable "latest" copy so a dashboard can always read one fixed path
    if args.dated and mode == "w" and out_path != CSV_PATH:
        import shutil

        shutil.copyfile(out_path, CSV_PATH)
    print(f"wrote {out_path}", flush=True)


if __name__ == "__main__":
    main()
