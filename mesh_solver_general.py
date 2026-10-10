#!/usr/bin/env python3
"""Mesh-current solver for circuits with 2 or 3 meshes (resistors and batteries).

    python3 mesh_solver_general.py          answer the questions for your circuit
    python3 mesh_solver_general.py --demo   solve the 100 V / 20 / 60 / 40 ohm / 50 V circuit

In Jupyter or Colab, paste the file into a cell and run it. The questions appear
in the input box under the cell. To see the demo there instead, replace the last
three lines of the file with  main(["--demo"]).

The web page (index.html) runs this same file in the browser through Pyodide.
It calls solve_web() near the bottom of the file and shows the result.

What it does
------------
1. Asks how many meshes there are and which way each mesh-current arrow turns.
2. Asks about every branch (a stretch of wire between two junctions that holds
   resistors and/or batteries): which mesh(es) it borders, which side of the
   mesh it is on, its resistance, and for each battery its voltage and where
   the + plate is.
3. Walks round every mesh in the direction of its own current and prints each
   term with the reason for its sign (battery rise or drop, and whether the
   neighbouring mesh current adds or subtracts in a shared resistor), then the
   KVL equation, so you can compare it line by line with your own working.
4. Solves for the mesh currents exactly (fractions and decimals), gives the real
   size and direction of the current in every branch, and checks the answer
   by putting it back into KVL and by comparing battery power with heat.

How to describe the drawing
---------------------------
* Think of every mesh as a rectangle with a top, bottom, left and right side.
* A branch on the outside of the circuit borders one mesh. A branch between two
  meshes is shared: you give its side for the first mesh and the program takes
  the opposite side for the second one.
* Plain wires with nothing on them are left out.
* A battery on an upright branch (left or right side of a mesh) has its +
  plate at the top or the bottom. On a sideways branch (top or bottom side) the
  + plate is at the left or the right.
* Use one set of units. Ohms and volts give amps; kilo-ohms and volts give
  milliamps. The output always prints A and W.

Answers for the demo circuit (two meshes, both arrows clockwise)
----------------------------------------------------------------
    branch  meshes  side of first mesh  resistance  batteries
    1       1       left                0           100 V, + at top
    2       1       top                 20          none
    3       1 2     right               60          none
    4       2       top                 40          none
    5       2       right               0           50 V, + at top
"""

import argparse
import json
import sys
from dataclasses import dataclass
from fractions import Fraction

MAX_MESHES = 3
OHM = "ohm"  # setup_output() switches this to the omega sign when the terminal can show it

OPPOSITE_SIDE = {"top": "bottom", "bottom": "top", "left": "right", "right": "left"}
OPPOSITE_DIR = {"up": "down", "down": "up", "left": "right", "right": "left"}
ROT_NAME = {"cw": "clockwise", "ccw": "counter-clockwise"}
ROT_FLIP = {"cw": "ccw", "ccw": "cw"}

# Direction you travel along each side of a rectangular mesh while walking round it.
WALK = {
    "cw": {"left": "up", "top": "right", "right": "down", "bottom": "left"},
    "ccw": {"left": "down", "bottom": "right", "right": "up", "top": "left"},
}
# The order in which those sides are met (only used to print the terms in walking order).
WALK_ORDER = {
    "cw": ["left", "top", "right", "bottom"],
    "ccw": ["left", "bottom", "right", "top"],
}
# Direction of travel from the - plate to the + plate, given where the + plate is.
PLUS_POINTS = {"top": "up", "bottom": "down", "left": "left", "right": "right"}

SIDE_WORDS = {"top": "top", "t": "top", "bottom": "bottom", "b": "bottom",
              "left": "left", "l": "left", "right": "right", "r": "right"}
ROTATION_WORDS = {"cw": "cw", "c": "cw", "clockwise": "cw",
                  "ccw": "ccw", "acw": "ccw", "a": "ccw", "anticlockwise": "ccw",
                  "anti-clockwise": "ccw", "counterclockwise": "ccw",
                  "counter-clockwise": "ccw"}

INTRO = """Mesh-current solver (2 or 3 meshes)
-----------------------------------
Picture every mesh as a rectangle with a top, bottom, left and right side.
A branch is a stretch of wire between two junctions that holds resistors and/or batteries.
  * A branch on the outside of the circuit borders one mesh.
  * A branch between two meshes is shared. Give its side for the first mesh and the
    program works out the opposite side for the second.
  * Plain wires with nothing on them can be left out.
Use one set of units (ohms and volts give amps). Press Ctrl+C to quit.
"""


# ---------------------------------------------------------------- circuit data

@dataclass
class Battery:
    volts: Fraction
    plus: str      # where the + plate is: top/bottom (upright branch) or left/right (sideways)


@dataclass
class Branch:
    resistance: Fraction   # total of the resistors in series on this branch
    batteries: list        # list of Battery
    sides: dict            # mesh index (0-based) -> side of that mesh the branch lies on
    number: int = 0        # the number the user gave it (0 = use its position in the list)

    @property
    def vertical(self):
        return any(s in ("left", "right") for s in self.sides.values())


@dataclass
class Term:
    """One step of the walk round a mesh: a voltage rise (+) or drop (-)."""
    sign: str        # "+" or "-"
    body: str        # text after the sign, e.g. "60 (I1 - I2)"
    const: Fraction  # constant part of the term (batteries)
    coeffs: dict     # mesh index -> multiplier of that mesh current (resistors)
    branch: int      # branch number as shown to the user
    element: str     # what is on the branch, e.g. "100 V battery (+ plate at top)"
    walking: str     # direction of travel through the branch
    why: str         # the reason for the sign
    kind: str        # "RISE" or "DROP"
    term: str        # the term as written in the equation, e.g. "-60 (I1 - I2)"

    @property
    def note(self):
        return (f"Branch {self.branch}: {self.element}, walking {self.walking}: "
                f"{self.why} -> {self.kind} -> {self.term}")


@dataclass
class Analysis:
    plan: list      # plan[k] = list of Term for mesh k, in walking order
    A: list
    E: list
    I: list         # solved mesh currents
    flows: list     # per branch: (direction of reference walk, signed current along it)
    kvl: list       # per mesh: numeric value of every term, using the solved currents
    delivered: list  # (branch index, Battery, watts); positive = battery delivers power
    heat: Fraction


def branch_no(branches, i):
    """The number shown for branch i (what the user typed, or its position)."""
    return branches[i].number or i + 1


# ------------------------------------------------------------------ formatting

def fmt(x):
    """20 stays 20; 4.7 stays 4.7."""
    x = Fraction(x)
    return str(x.numerator) if x.denominator == 1 else f"{float(x):g}"


def fmt_exact(x):
    """Results as 35/22 = 1.5909."""
    x = Fraction(x)
    if x.denominator == 1:
        return str(x.numerator)
    return f"{x.numerator}/{x.denominator} = {float(x):.4f}"


def join_terms(pairs):
    """[('+', '100'), ('-', '20 I1')] -> '100 - 20 I1'."""
    out = ""
    for n, (sign, body) in enumerate(pairs):
        if n == 0:
            out = body if sign == "+" else f"-{body}"
        else:
            out += f" {sign} {body}"
    return out or "0"


def equation_text(row, rhs):
    pairs = [("+" if c > 0 else "-", f"{fmt(abs(c))} I{m + 1}")
             for m, c in enumerate(row) if c != 0]
    return f"{join_terms(pairs)} = {fmt(rhs)}"


def contents_text(b):
    items = []
    if b.resistance != 0:
        items.append(f"{fmt(b.resistance)} {OHM}")
    for bat in b.batteries:
        items.append(f"{fmt(bat.volts)} V battery (+ at {bat.plus})")
    return " + ".join(items)


def location_text(b):
    return " and ".join(f"{side} side of mesh {m + 1}" for m, side in sorted(b.sides.items()))


# ----------------------------------------------------------------- the maths

def build_plan(rotations, branches):
    """Walk round every mesh and turn each element into a signed term."""
    plan = []
    for k, rot in enumerate(rotations):
        order = WALK_ORDER[rot]
        mine = sorted(((i, b) for i, b in enumerate(branches) if k in b.sides),
                      key=lambda ib: order.index(ib[1].sides[k]))
        if not mine:
            raise ValueError(f"mesh {k + 1} has no branches yet - add one that borders it")
        terms = []
        for i, b in mine:
            d = WALK[rot][b.sides[k]]          # the way you travel through this branch
            no = branch_no(branches, i)
            for bat in b.batteries:
                rise = PLUS_POINTS[bat.plus] == d
                v = fmt(bat.volts)
                first, last = ("-", "+") if rise else ("+", "-")
                terms.append(Term(
                    "+" if rise else "-", v, bat.volts if rise else -bat.volts, {},
                    no, f"{v} V battery (+ plate at {bat.plus})", d,
                    f"you go from the {first} plate to the {last} plate",
                    "RISE" if rise else "DROP", f"{'+' if rise else '-'}{v}"))
            if b.resistance != 0:
                r = b.resistance
                expr = f"I{k + 1}"
                coeffs = {k: -r}
                others = [j for j in sorted(b.sides) if j != k]
                for j in others:
                    same = WALK[rotations[j]][b.sides[j]] == d
                    s = 1 if same else -1       # +1: I_j runs the same way you walk
                    coeffs[j] = -s * r
                    expr += f" {'+' if same else '-'} I{j + 1}"
                if others:
                    j = others[0]
                    expr = f"({expr})"
                    how = "with you" if coeffs[j] < 0 else "against you"
                    element = f"{fmt(r)} {OHM} shared with mesh {j + 1}"
                    why = (f"I{k + 1} runs with you and I{j + 1} runs {how}, so the current "
                           f"along your walk is {expr}")
                else:
                    element = f"{fmt(r)} {OHM}"
                    why = f"only I{k + 1} flows here, along your walk"
                terms.append(Term("-", f"{fmt(r)} {expr}", Fraction(0), coeffs,
                                  no, element, d, why, "DROP", f"-{fmt(r)} {expr}"))
        plan.append(terms)
    return plan


def solve_linear(A, b):
    """Gauss-Jordan elimination with exact fractions."""
    n = len(A)
    M = [list(row) + [b[i]] for i, row in enumerate(A)]
    for col in range(n):
        pivot = next((r for r in range(col, n) if M[r][col] != 0), None)
        if pivot is None:
            raise ValueError("the equations have no single solution - check that every mesh "
                             "has a resistor and that no branch is missing")
        M[col], M[pivot] = M[pivot], M[col]
        pv = M[col][col]
        M[col] = [x / pv for x in M[col]]
        for r in range(n):
            if r != col and M[r][col] != 0:
                f = M[r][col]
                M[r] = [x - f * y for x, y in zip(M[r], M[col])]
    return [M[i][n] for i in range(n)]


def analyse(rotations, branches):
    plan = build_plan(rotations, branches)
    n = len(rotations)
    A = [[Fraction(0)] * n for _ in range(n)]
    E = [Fraction(0)] * n
    for k, terms in enumerate(plan):       # sum of terms = 0  ->  A I = E
        for t in terms:
            E[k] += t.const
            for m, c in t.coeffs.items():
                A[k][m] -= c
    I = solve_linear(A, E)

    # Current in each branch, measured along the walking direction of its lowest-numbered mesh.
    flows = []
    for b in branches:
        k0 = min(b.sides)
        d0 = WALK[rotations[k0]][b.sides[k0]]
        total = I[k0]
        for j in b.sides:
            if j != k0:
                total += I[j] if WALK[rotations[j]][b.sides[j]] == d0 else -I[j]
        flows.append((d0, total))

    kvl = [[t.const + sum(c * I[m] for m, c in t.coeffs.items()) for t in terms]
           for terms in plan]

    delivered = []
    for i, b in enumerate(branches):
        d0, total = flows[i]
        for bat in b.batteries:
            through_plus = total if PLUS_POINTS[bat.plus] == d0 else -total
            delivered.append((i, bat, bat.volts * through_plus))
    heat = sum((b.resistance * flows[i][1] ** 2 for i, b in enumerate(branches)), Fraction(0))
    return Analysis(plan, A, E, I, flows, kvl, delivered, heat)


# ------------------------------------------------------------------- the report

def describe(rotations, branches):
    """Everything the report shows, as plain data (strings, numbers, lists).

    Raises ValueError when the circuit cannot be solved. The command line prints
    this with format_report(); the web page draws it.
    """
    res = analyse(rotations, branches)
    d = {"rotations": list(rotations)}

    d["understood"] = {
        "meshes": [{"mesh": k + 1, "text": f"I{k + 1} turns {ROT_NAME[rot]}"}
                   for k, rot in enumerate(rotations)],
        "branches": [{"branch": branch_no(branches, i), "contents": contents_text(b),
                      "where": location_text(b)} for i, b in enumerate(branches)],
    }

    d["meshes"] = []
    for k, terms in enumerate(res.plan):
        d["meshes"].append({
            "mesh": k + 1,
            "rotation": ROT_NAME[rotations[k]],
            "terms": [{"branch": t.branch, "element": t.element, "walking": t.walking,
                       "why": t.why, "kind": t.kind, "term": t.term, "note": t.note}
                      for t in terms],
            "kvl": f"{join_terms([(t.sign, t.body) for t in terms])} = 0",
            "rearranged": equation_text(res.A[k], res.E[k]),
        })

    d["currents"] = []
    for k, val in enumerate(res.I):
        rot = rotations[k]
        if val == 0:
            verdict, real = "no current", ""
        elif val > 0:
            real = ROT_NAME[rot]
            verdict = f"flows {real}, the same as your arrow"
        else:
            real = ROT_NAME[ROT_FLIP[rot]]
            verdict = f"negative, so it really flows {real}, against your arrow"
        d["currents"].append({
            "name": f"I{k + 1}", "mesh": k + 1, "exact": fmt_exact(val),
            "fraction": f"{val.numerator}/{val.denominator}" if val.denominator != 1 else "",
            "decimal": f"{float(val):.4f}", "sign": (val > 0) - (val < 0),
            "real_direction": real, "verdict": verdict,
        })

    d["branch_currents"] = []
    for i, (b, (d0, total)) in enumerate(zip(branches, res.flows)):
        if total == 0:
            direction, text = "", "no current"
        else:
            direction = d0 if total > 0 else OPPOSITE_DIR[d0]
            text = f"{float(abs(total)):.4f} A going {direction}"
        d["branch_currents"].append({
            "branch": branch_no(branches, i), "contents": contents_text(b),
            "amps": f"{float(abs(total)):.4f}", "direction": direction, "text": text,
        })

    d["kvl_check"] = [{
        "mesh": k + 1,
        "values": [f"{float(v):+.4f}" for v in values],
        "sum": f"{float(sum(values, Fraction(0))):.4f}",
    } for k, values in enumerate(res.kvl)]

    source = sum((p for _, _, p in res.delivered), Fraction(0))
    d["power"] = {
        "batteries": [{
            "branch": branch_no(branches, i), "volts": fmt(bat.volts),
            "delivers": p >= 0,
            "verb": "delivers" if p >= 0 else "absorbs (is being charged)",
            "watts": f"{float(abs(p)):.4f}",
        } for i, bat, p in res.delivered],
        "source": f"{float(source):.4f}",
        "heat": f"{float(res.heat):.4f}",
        "balanced": source == res.heat,
    }
    return d


def format_report(d):
    """The text the command line prints."""
    out = ["\n=== What I understood ==="]
    for m in d["understood"]["meshes"]:
        out.append(f"  Mesh {m['mesh']}: {m['text']}")
    for b in d["understood"]["branches"]:
        out.append(f"  Branch {b['branch']}: {b['contents']}   [{b['where']}]")

    out.append("\n=== KVL equation of each mesh ===")
    out.append("Walk round each mesh in the direction of its own current.")
    out.append("A voltage rise counts +, a voltage drop counts -, and the total is 0.")
    for m in d["meshes"]:
        out.append(f"\nMesh {m['mesh']} ({m['rotation']}):")
        for t in m["terms"]:
            out.append(f"   {t['note']}")
        out.append(f"   KVL:         {m['kvl']}")
        out.append(f"   Rearranged:  {m['rearranged']}")

    out.append("\n=== Mesh currents ===")
    for c in d["currents"]:
        out.append(f"  {c['name']} = {c['exact']} A   ({c['verdict']})")

    out.append("\n=== Real current in every branch ===")
    for b in d["branch_currents"]:
        out.append(f"  Branch {b['branch']} ({b['contents']}): {b['text']}")

    out.append("\n=== Checks ===")
    out.append("KVL with the answers put back in (every line should add up to 0):")
    for c in d["kvl_check"]:
        out.append(f"  Mesh {c['mesh']}: {' '.join(c['values'])} = {c['sum']}")
    out.append("Power balance:")
    for p in d["power"]["batteries"]:
        out.append(f"  {p['volts']} V battery in branch {p['branch']} {p['verb']} {p['watts']} W")
    verdict = "balanced" if d["power"]["balanced"] else "NOT balanced"
    out.append(f"  Batteries supply {d['power']['source']} W net, resistors dissipate "
               f"{d['power']['heat']} W -> {verdict}")
    return "\n".join(out)


def report(rotations, branches):
    try:
        d = describe(rotations, branches)
    except ValueError as err:
        print(f"\nCannot solve: {err}")
        return False
    print(format_report(d))
    return True


# ----------------------------------------------------------------- user input

def ask(prompt, parse, default=None):
    hint = f" [{default}]" if default is not None else ""
    while True:
        raw = input(f"{prompt}{hint}: ").strip()
        if not raw and default is not None:
            raw = str(default)
        try:
            return parse(raw)
        except ValueError as err:
            print(f"   ! {err}")


def int_between(lo, hi):
    def parse(raw):
        try:
            value = int(raw)
        except ValueError:
            raise ValueError(f"enter a whole number from {lo} to {hi}")
        if not lo <= value <= hi:
            raise ValueError(f"enter a whole number from {lo} to {hi}")
        return value
    return parse


def number(allow_zero):
    def parse(raw):
        try:
            parts = [Fraction(p) for p in raw.replace(" ", "").split("+")]
        except (ValueError, ZeroDivisionError):
            raise ValueError("enter a number such as 47 or 4.7, or a sum such as 10+22")
        total = sum(parts, Fraction(0))
        if any(p < 0 for p in parts) or total < 0 or (total == 0 and not allow_zero):
            raise ValueError("enter a positive number" if not allow_zero
                             else "enter zero or a positive number")
        return total
    return parse


def choice(options, hint):
    def parse(raw):
        key = raw.strip().lower()
        if key not in options:
            raise ValueError(f"please type {hint}")
        return options[key]
    return parse


def mesh_list(n):
    def parse(raw):
        try:
            nums = [int(x) for x in raw.replace(",", " ").split()]
        except ValueError:
            nums = []
        if not 1 <= len(nums) <= 2 or len(set(nums)) != len(nums) \
                or any(not 1 <= x <= n for x in nums):
            raise ValueError(f"enter one mesh number, or two different ones, from 1 to {n}")
        return [x - 1 for x in nums]
    return parse


def ask_branch(number_, n):
    print(f"\nBranch {number_}")
    meshes = ask("  Which mesh(es) does it border? One number, or two if shared (e.g. 1 2)",
                 mesh_list(n))
    first = meshes[0]
    side = ask(f"  Which side of mesh {first + 1} is it on? (top/bottom/left/right)",
               choice(SIDE_WORDS, "top, bottom, left or right"))
    sides = {first: side}
    for m in meshes[1:]:
        sides[m] = OPPOSITE_SIDE[side]
        print(f"  -> so it is the {sides[m]} side of mesh {m + 1}")
    resistance = ask("  Total resistance on it (0 if none; type 10+22 for resistors in series)",
                     number(True), default="0")
    ends = ("top", "bottom") if side in ("left", "right") else ("left", "right")
    words = {ends[0]: ends[0], ends[0][0]: ends[0], ends[1]: ends[1], ends[1][0]: ends[1]}
    count = ask("  How many batteries are on it? (0, 1, 2 ...)", int_between(0, 4), default="0")
    batteries = []
    for q in range(1, count + 1):
        volts = ask(f"  Battery {q}: voltage", number(False))
        plus = ask(f"  Battery {q}: which end is the + plate? ({ends[0]}/{ends[1]})",
                   choice(words, f"{ends[0]} or {ends[1]}"))
        batteries.append(Battery(volts, plus))
    if resistance == 0 and not batteries:
        print("  (nothing on this branch, so it is ignored)")
        return None
    return Branch(resistance, batteries, sides, number_)


def ask_circuit():
    n = ask(f"How many meshes? (2 to {MAX_MESHES})", int_between(2, MAX_MESHES))
    print()
    rotations = [ask(f"Mesh {k}: which way does your I{k} arrow turn? (cw/ccw)",
                     choice(ROTATION_WORDS, "cw or ccw"), default="cw")
                 for k in range(1, n + 1)]
    print("\nNow list every branch that holds a resistor or a battery (count a shared branch once).")
    count = ask("How many such branches are there?", int_between(1, 20))
    branches = [ask_branch(i, n) for i in range(1, count + 1)]
    return rotations, [b for b in branches if b is not None]


def demo_circuit():
    rotations = ["cw", "cw"]
    branches = [
        Branch(Fraction(0), [Battery(Fraction(100), "top")], {0: "left"}),
        Branch(Fraction(20), [], {0: "top"}),
        Branch(Fraction(60), [], {0: "right", 1: "left"}),
        Branch(Fraction(40), [], {1: "top"}),
        Branch(Fraction(0), [Battery(Fraction(50), "top")], {1: "right"}),
    ]
    return rotations, branches


# ------------------------------------------------------------ web page entry

def circuit_from_payload(data):
    """Build a circuit from the dict the web page sends. Mesh numbers start at 1.

    {"rotations": ["cw", "cw"],
     "branches": [{"meshes": [1, 2], "side": "right", "resistance": "60",
                   "batteries": [{"volts": "50", "plus": "top"}]}, ...]}

    Raises ValueError with a message that says which branch needs fixing.
    """
    rotations = list(data["rotations"])
    n = len(rotations)
    if not 2 <= n <= MAX_MESHES or any(r not in ROT_NAME for r in rotations):
        raise ValueError(f"choose 2 to {MAX_MESHES} meshes, each clockwise or counter-clockwise")
    branches, warnings = [], []
    for number_, item in enumerate(data["branches"], 1):
        who = f"Branch {number_}"
        try:
            meshes = mesh_list(n)(" ".join(str(m) for m in item["meshes"]))
        except ValueError:
            raise ValueError(f"{who}: pick the mesh it borders, or two meshes if it is shared") from None
        first = meshes[0]
        side = SIDE_WORDS.get(str(item["side"]).lower())
        if side is None:
            raise ValueError(f"{who}: choose the side of mesh {first + 1} it is on")
        sides = {first: side}
        for m in meshes[1:]:
            sides[m] = OPPOSITE_SIDE[side]
        try:
            resistance = number(True)(str(item.get("resistance", "")).strip() or "0")
        except ValueError as err:
            raise ValueError(f"{who}, resistance: {err}") from None
        ends = ("top", "bottom") if side in ("left", "right") else ("left", "right")
        batteries = []
        for q, bat in enumerate(item.get("batteries", []), 1):
            raw_volts = str(bat.get("volts", "")).strip()
            if not raw_volts:
                raise ValueError(f"{who}, battery {q}: enter its voltage")
            try:
                volts = number(False)(raw_volts)
            except ValueError as err:
                raise ValueError(f"{who}, battery {q} voltage: {err}") from None
            plus = str(bat.get("plus", "")).lower()
            if plus not in ends:
                raise ValueError(f"{who}, battery {q}: the + plate is at the {ends[0]} or the {ends[1]}")
            batteries.append(Battery(volts, plus))
        if resistance == 0 and not batteries:
            warnings.append(f"Branch {number_} has no resistor or battery, so it is left out.")
            continue
        branches.append(Branch(resistance, batteries, sides, number_))
    if not branches:
        raise ValueError("add at least one branch that holds a resistor or a battery")
    return rotations, branches, warnings


def solve_web(payload):
    """JSON text in, JSON text out. This is what the web page calls."""
    global OHM
    OHM = "Ω"
    try:
        rotations, branches, warnings = circuit_from_payload(json.loads(payload))
        result = describe(rotations, branches)
        result.update(ok=True, warnings=warnings, text=format_report(result))
    except ValueError as err:
        result = {"ok": False, "error": str(err)}
    except (KeyError, TypeError, AttributeError):
        result = {"ok": False, "error": "the circuit description is incomplete"}
    return json.dumps(result)


# ------------------------------------------------------------- command line

def setup_output():
    global OHM
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    try:
        "Ω".encode(getattr(sys.stdout, "encoding", None) or "utf-8")
        OHM = "Ω"
    except (UnicodeEncodeError, LookupError):
        OHM = "ohm"


def in_notebook():
    return "ipykernel" in sys.modules


def main(argv=None):
    parser = argparse.ArgumentParser(description="Mesh-current solver for circuits with 2 or 3 meshes.")
    parser.add_argument("--demo", action="store_true",
                        help="solve the 100 V / 20 / 60 / 40 ohm / 50 V circuit without asking questions")
    args, unknown = parser.parse_known_args(argv)
    if unknown and not in_notebook():
        parser.error(f"unrecognized arguments: {' '.join(unknown)}")
    # Inside Jupyter, sys.argv holds the notebook's own "-f kernel.json", which is ignored here.
    setup_output()
    try:
        if args.demo:
            print("Demo circuit: 100 V battery and 20 ohm in mesh 1, 60 ohm shared, "
                  "40 ohm and 50 V battery in mesh 2, both arrows clockwise.")
            report(*demo_circuit())
            return 0
        print(INTRO)
        while True:
            report(*ask_circuit())
            try:
                again = input("\nCheck another circuit? (y/n) [n]: ").strip().lower()
            except EOFError:
                again = ""
            if not again.startswith("y"):
                return 0
            print()
    except (KeyboardInterrupt, EOFError):
        print("\nStopped.")
        return 1


if __name__ == "__main__":
    exit_code = main()
    if not in_notebook():      # sys.exit inside Jupyter would print a "SystemExit" traceback
        sys.exit(exit_code)
