# Mesh current solver

A small web page and Python program that solve circuits with two or three meshes by mesh analysis (Kirchhoff's voltage law).

You describe the circuit: which way each mesh-current arrow turns, and for each branch its resistance and the alignment of any batteries. The program then writes the voltage equation for each mesh, gives a reason for every sign, solves for the currents, and checks the answer.

The page runs `mesh_solver_general.py` in your browser through [Pyodide](https://pyodide.org). There is no server and nothing to install.

## Try it on your computer

Browsers do not let a page read files when you double-click `index.html`, so serve the folder instead:

```
python3 -m http.server
```

Then open <http://localhost:8000>.

## Run the Python program on its own

```
python3 mesh_solver_general.py          # asks questions about your circuit
python3 mesh_solver_general.py --demo   # solves the 100 V / 20 / 60 / 40 ohm / 50 V example
```

It works in Jupyter and Colab too. See the notes at the top of the file.

## Put it on GitHub Pages

1. Create a new public repository on GitHub.
2. Upload everything in this folder. Keep `index.html` at the top level.
3. Open the repository's **Settings**, then **Pages**. Under **Build and deployment**, choose **Deploy from a branch**, pick `main` and `/ (root)`, and save.
4. After a minute the site is at `https://<your-username>.github.io/<repository-name>/`.

## How it works

| File | Job |
| --- | --- |
| `mesh_solver_general.py` | All the circuit maths and every sign decision. Also runs in a terminal. |
| `index.html`, `style.css` | The page. |
| `app.js` | The form, the Pyodide loader, and the results display. It sends the circuit to `solve_web()` in the Python file as JSON and draws the reply. |
| `tests/test_nodal.py` | Compares the solver with an independent nodal analysis on thousands of random circuits. |

If you edit `mesh_solver_general.py`, the page changes with it. The Pyodide version is set once, in the `<script>` tag in `index.html`.

## Describing a circuit

* Treat every mesh as a rectangle with a top, bottom, left and right side. For a diagonal branch, pick the nearest side.
* A branch is a stretch of wire between two junctions that holds resistors or batteries. Leave out plain wires.
* A branch on the outside borders one mesh. A shared branch borders two: give its side for the lower-numbered mesh and the program works out the other.
* A battery on a left or right side has its + plate at the top or bottom. On a top or bottom side it is at the left or right.
* Use one set of units. Ohms and volts give amps.

## Limits

* Resistors and batteries only. No current sources.
* The page offers two or three meshes.
* The first visit needs an internet connection to download Pyodide (about 10 MB) and the fonts.

## Tests

```
python3 tests/test_nodal.py
```

## Licence

Add the licence you want to use.
