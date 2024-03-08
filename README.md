<h1 align="center">CACE</h1>
<h2 align="center">Circuit Automatic Characterization Engine</h2>
<p align="center">
    <a href="https://opensource.org/licenses/Apache-2.0"><img src="https://img.shields.io/badge/License-Apache%202.0-blue.svg" alt="License: Apache 2.0"/></a>
    <a href="https://www.python.org"><img src="https://img.shields.io/badge/Python-3.8-3776AB.svg?style=flat&logo=python&logoColor=white" alt="Python 3.8 or higher" /></a>
    <a href="https://github.com/psf/black"><img src="https://img.shields.io/badge/code%20style-black-000000.svg" alt="Code Style: black"/></a>
</p>
<p align="center">
    <a href="https://invite.skywater.tools"><img src="https://img.shields.io/badge/Community-Open%20Source%20Silicon%20Slack-ff69b4?logo=slack" alt="Invite to the Open Source Silicon Slack"/></a>
</p>

CACE is a set of python scripts that take an input file in the
CACE 4.0 format and uses the information found there in combination with CACE-compatible testbenches and analysis scripts to characterize a circuit and to produce a datasheet showing the circuit performance.

## Installation

### Dependencies

To install the dependencies for CACE, run:

	$ pip3 install -r requirements.txt

To install the dependencies to build CACE, run:

	$ pip3 install -r requirements_dev.txt

To install the dependencies to build the documentation for CACE, run:

	$ pip3 install -r requirements_docs.txt

### CACE

For now, CACE can be manually installed using pip.

First the Python package needs to be build:

```
$ make build
```

To install the package, run:

```
$ make install
```

## Usage

If installed properly as Python package, CACE can be started from the command line using:

```
$ cace
```

Or to start the GUI:

```
$ cace-gui
```

CACE GUI syntax:

	/path/to/cace_gui.py [path/to/project.txt]

	where optional file project.txt (normally <name_of_project>.txt
	where <name_of_project> is the name of the circuit to be
	characterized) is a circuit characterization description in the
	file format described below.  If a file is not specified, then
	the GUI window will come up without content.  Click on the button
	with text "(no selection)" to find and select a characterization
	file to load.  The project file may also be in JSON format.

	Normally, cace_gui.py is called from a project top level directory,
	while the project.txt file is usually in a subdirectory called
	cace/.  The project.txt file may be the output file from a CACE
	run, which will add results to all of the parameter entries.

	There may be multiple characterization files in a single project
	(repository), as a project may contain multiple subcircuits that
	may need independent characterization or be able to be used as
	standalone circuits, or a project may simply be a collection of
	circuits (library) without a specific single top level. 

CACE command line syntax:

	/path/to/cace.py <filename_in> <filename_out> [options]

	where <filename_in> is a format 4.0 ASCII CACE file
	and <filename_out> is the name of the file to write.

	Options may be one of:

	  -source=schematic|layout|rcx|all|best
	  -param=<parameter_name>
	  -force
	  -json
	  -keep
	  -debug
	  -sequential
	  -summary

	When run from the top level, this program parses the CACE
	characterization file, runs simulations, and outputs a
	modified file annotated with characterization results.

	With option "-source", restrict characterization to the
	specific netlist source, which is either schematic capture,
	layout extracted, or full R-C parasitic extracted.  If not
	specified, then characterization is run on the full R-C
	parasitic extracted layout netlist if available, and the
	schematic captured netlist if not (option "best").

	Option "-param=<parameter_name>" runs simulations on only
	the named electrical or physical parameter.

	Option "-force" forces new regeneration of all netlists.

	Option "-json" generates an output file in JSON format.

	Option "-keep" retains files generated for characterization.

	Option "-noplot" will not generate any graphs.

	Option "-debug" generates additional diagnostic output.

	Option "-sequential" runs simulations sequentially.

	Option "-nosim" does not re-run simulations if the output file exists.
	   (Warning---does not check if simulations are out of date).

	Option "-summary" prints a summary of results at the end.

## Examples

The following repositories contain example circuit designs, each having a "cace/" subdirectory with a specification input file in the format described below, and a set of testbench schematics which are used by CACE to measure all specified electrical and physical parameters, generate results, and analyze them to determine circuit performance over corners.

(NOTE:  Example repositories, like CACE itself, are currently a work in progress.)

All repositories are rooted at: [https://github.com/RTimothyEdwards/](https://github.com/RTimothyEdwards/).

Example circuit repositories:

	sky130_ef_ip__instramp		Instrumentation amplifier
	sky130_ef_ip__rdac3v_8bit	8-bit resistor ladder DAC
	sky130_ef_ip__samplehold	sample-and-hold circuit
	sky130_ef_ip__driveramp		Rail-to-rail driver amplifier
	sky130_ef_ip__ccomp3v		Rail-to-rail continuous comparator
	sky130_ef_ip__rc_osc_500k	R-C oscillator, 500kHz nominal output
	sky130_ef_ip__xtal_osc_16M	Crystal oscillator, 4 to 15MHz
	sky130_ef_ip__xtal_osc_32k	Crystal oscillator, 32kHz

Each of these repositories contains a circuit designed with the SkyWater sky130 process open PDK, and contains schematics, layout, and CACE characterization.

NOTE:  These repositories are a work in progress, and may not exist yet or may not have a characterization setup for CACE.

## Documentation

To build the documentation, change your directory to docs and run:

	$ make html

Note: The documentation is not yet hosted anywhere.