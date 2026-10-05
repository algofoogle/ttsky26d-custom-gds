# `normalise_magic_def.py`

`normalise_magic_def.py` post-processes a DEF file written by Magic into
a cleaner, more portable DEF representation. It is particularly useful
for DEF files that were originally read by Magic and then written back
out, where Magic has reconstructed routed NETS, introduced non-default
routing rules, changed bus-character conventions, or otherwise produced
output that differs substantially from the original logical DEF.

The script can also use specially formatted labels in the corresponding
Magic `.mag` file to generate:

-   DEF `BLOCKAGES` for placement and signal-routing obstructions;
    and/or
-   a LibreLane JSON configuration fragment containing
    `FP_OBSTRUCTIONS`, `ROUTING_OBSTRUCTIONS`, and `PDN_OBSTRUCTIONS`.

The script does not modify the input DEF or `.mag` file.

## Requirements

-   Python 3
-   No third-party Python packages are required.
-   For automatic obstruction coordinate scaling and routing-layer
    discovery, an installed PDK is recommended and is normally located
    using `$PDK_ROOT` and `$PDK`.

The script contains built-in routing-layer fallbacks for:

-   `sky130A`
-   `sky130B`
-   `gf180mcuD`
-   `ihp-sg13g2`
-   `ihp-sg13cmos5l`

## Basic use

``` sh
python3 normalise_magic_def.py input.def output.def
```

The input and output must be different files.

A typical Magic round-trip is:

``` tcl
def read source.def
extract all
def write magic-output.def
```

followed by:

``` sh
python3 normalise_magic_def.py magic-output.def normalised.def
```

The `extract all` step is important because Magic's DEF writer
reconstructs the `NETS` section from extracted connectivity. If the
generated DEF has no `NETS` section, the script reports an error.

## What normalisation does

By default, the script:

1.  Normalises every `NETS` entry to connectivity plus `+ USE SIGNAL`.
2.  Removes routed geometry and routing properties such as `ROUTED` and
    `TAPERRULE` from `NETS`.
3.  Removes the `NONDEFAULTRULES` section.
4.  Changes `BUSBITCHARS` to `"[]"`, after checking that identifier-like
    names using round-parenthesis bus notation are not present.
5.  Reconstructs `SPECIALNETS`.
6.  Changes the DEF `DESIGN` name to the output filename stem unless
    `--design` is supplied.
7.  Performs consistency checks on pins, nets, required sections, and
    remaining routing/NDR data.

Unless special-net behaviour is explicitly overridden, the output
contains:

``` def
SPECIALNETS 2 ;
   - VGND + USE GROUND ;
   - VPWR + USE POWER ;
END SPECIALNETS
```

## Source-like formatting

Source-like formatting is enabled by default. A normal invocation:

``` sh
python3 normalise_magic_def.py magic-output.def normalised.def
```

therefore canonicalises the DEF into a form intended to remain close to
the original TinyTapeout-style source DEF.

This formatting:

-   writes `VERSION 5.8`;
-   removes `NAMESCASESENSITIVE`;
-   removes `TECHNOLOGY`;
-   removes the `VIAS` section;
-   canonicalises the layout of `PINS`;
-   natural-sorts and canonicalises `NETS`;
-   canonicalises `SPECIALNETS`; and
-   removes unnecessary blank lines.

This formatting is intended to make a subsequent `diff` primarily show
meaningful changes rather than Magic formatting differences.

`--format-like-source` may still be specified explicitly. To disable the
default behaviour and retain the less opinionated normalisation format, use:

``` sh
--no-format-like-source
```

## DESIGN name

By default, `DESIGN` is changed to the stem of the output filename.

For example:

``` sh
python3 normalise_magic_def.py magic.def tt_um_example.def
```

produces:

``` def
DESIGN tt_um_example ;
```

Override this with:

``` sh
python3 normalise_magic_def.py magic.def output.def \
    --design tt_um_template
```

## Special nets

### Default

If no special-net options are given, the script adds:

-   `VGND` as `GROUND`
-   `VPWR` as `POWER`

### Explicit ground and power nets

`--ground` and `--power` may be repeated:

``` sh
python3 normalise_magic_def.py in.def out.def \
    --ground VGND \
    --power VPWR \
    --power VAPWR
```

### Copy from another DEF

Use:

``` sh
--specialnets-from source.def
```

to copy supported `SPECIALNETS` entries from another DEF.

This can be combined with `--ground` and `--power`.

### Disable defaults

Use:

``` sh
--no-default-specialnets
```

to suppress the default `VGND`/`VPWR` pair when no explicit special-net
source has been supplied.

Conflicting declarations, such as requesting the same net as both
`GROUND` and `POWER`, are errors.

# Obstruction annotations

Obstruction processing is optional. It is enabled when either:

``` sh
--def-blockages
```

or:

``` sh
--librelane-obstructions FILE.json
```

is specified.

The script then reads obstruction annotations from a Magic `.mag` file.

By default, the `.mag` filename is obtained by replacing the input DEF
suffix with `.mag`:

``` text
example.def  ->  example.mag
```

Override this with:

``` sh
--mag-source layout.mag
```

## Magic label representation

An obstruction is represented by a Magic label attached to `space`. The
rectangular extent of the label becomes the obstruction rectangle.

The label text must begin with:

``` text
obs:
```

followed by one or more semicolon-separated selectors.

For example:

``` text
obs:place;route(met4)
```

The script looks for these annotations in the `.mag` `<< labels >>`
section and uses the coordinates of the `label`, `rlabel`, or `flabel`
record.

Ordinary labels and labels not attached to `space` are ignored.

## Obstruction grammar

The grammar is:

``` text
obs:<selector>[;<selector>...]

selector :=
    place
    route
    route(<layer>[,<layer>...])
    power
    power(<layer>[,<layer>...])
    all
    all(<layer>[,<layer>...])
```

The selectors are additive: repeated or overlapping layer selections are
combined as sets.

### `place`

``` text
obs:place
```

creates a placement obstruction.

`place` does not take a layer list. For example, this is invalid:

``` text
obs:place(met4)
```

### `route`

``` text
obs:route
```

blocks ordinary routing on all default metal layers.

A layer list restricts the obstruction:

``` text
obs:route(met3,met4)
```

### `power`

``` text
obs:power
```

blocks PDN generation on all default metal layers in the LibreLane
output.

A layer list may be supplied:

``` text
obs:power(met4,met5)
```

`power` is intentionally distinct from `route`.

### `all`

`all` combines placement, routing, and power/PDN obstruction.

``` text
obs:all
```

means:

``` text
placement: yes
routing:   all default metal layers
PDN:       all default metal layers
```

A layer list applies to the routing and PDN portions, while placement
remains enabled:

``` text
obs:all(met4)
```

means:

``` text
placement: yes
routing:   met4
PDN:       met4
```

### Combining selectors

For example:

``` text
obs:all(met4);power(met5);route(met2,met3)
```

results in:

``` text
placement: yes
routing:   met2, met3, met4
PDN:       met4, met5
```

Another example:

``` text
obs:place;route(met4)
```

means:

``` text
placement: yes
routing:   met4
PDN:       none
```

Malformed `obs:` syntax is treated as an error rather than being
silently ignored.

# DEF blockages

Enable DEF blockage generation with:

``` sh
--def-blockages
```

For example:

``` sh
python3 normalise_magic_def.py example.def output.def \
    --def-blockages
```

The mapping is:

  Annotation       DEF output
  ---------------- ------------------------------
  `place`          `PLACEMENT` blockage
  `route(layer)`   `LAYER layer` blockage
  `power(layer)`   no DEF blockage
  `all(layer)`     placement + routing blockage

A routing selector with multiple layers creates one DEF blockage entry
per layer.

`power` is deliberately not converted into an ordinary DEF routing
blockage. DEF has no direct equivalent of a LibreLane obstruction that
applies specifically during PDN generation; converting it to a normal
routing blockage would make the obstruction stronger than requested.

If the input DEF already contains a `BLOCKAGES` section, obstruction
generation replaces it with the blockages derived from the `.mag`
annotations.

# LibreLane obstruction output

Use:

``` sh
--librelane-obstructions obstructions.json
```

to write a JSON configuration fragment.

The mapping is:

  Annotation   LibreLane variable
  ------------ ------------------------
  `place`      `FP_OBSTRUCTIONS`
  `route`      `ROUTING_OBSTRUCTIONS`
  `power`      `PDN_OBSTRUCTIONS`

For example:

``` sh
python3 normalise_magic_def.py example.def output.def \
    --librelane-obstructions obstructions.json
```

may produce:

``` json
{
    "FP_OBSTRUCTIONS": [
        "10 20 30 40"
    ],
    "ROUTING_OBSTRUCTIONS": [
        "met4 10 20 30 40"
    ],
    "PDN_OBSTRUCTIONS": [
        "met5 10 20 30 40"
    ]
}
```

The outer values are JSON arrays, but each obstruction is encoded using
LibreLane's space-separated string syntax rather than as a nested JSON
array. Placement entries contain `llx lly urx ury`; routing and PDN
entries contain `layer llx lly urx ury`.

This is a configuration fragment; the script does not merge it into an
existing LibreLane `config.json`.

DEF and LibreLane output may be generated simultaneously:

``` sh
python3 normalise_magic_def.py example.def output.def \
    --def-blockages \
    --librelane-obstructions obstructions.json
```

# PDK and metal-layer discovery

Bare selectors such as:

``` text
obs:route
obs:power
obs:all
```

need a definition of "all metal layers".

The script determines the PDK in this order:

1.  `--pdk PDK`
2.  `$PDK`
3.  the `tech` declaration in the `.mag` file

The PDK root is obtained from:

1.  `--pdk-root DIR`
2.  `$PDK_ROOT`

The script searches common PDK directory layouts below that root.

For routing-layer discovery, it prefers installed PDK information and
then falls back to its built-in table. In particular, it attempts to
obtain the P&R routing-layer set from the PDK's LibreLane/OpenLane
configuration and then from technology LEF routing layers.

If installed PDK discovery fails but the PDK is one of the supported
built-in variants, the built-in set is used.

The source of the chosen layer set is printed in the run summary.

## Built-in PDK fallbacks

The current fallback sets are:

``` text
sky130A:
    met1 met2 met3 met4 met5

sky130B:
    met1 met2 met3 met4 met5

gf180mcuD:
    Metal1 Metal2 Metal3 Metal4 Metal5

ihp-sg13g2:
    Metal1 Metal2 Metal3 Metal4 Metal5

ihp-sg13cmos5l:
    Metal1 Metal2 Metal3 Metal4 Metal5
```

For `ihp-sg13g2`, `TopMetal1` and `TopMetal2` are intentionally not part
of the built-in expansion of a bare `route`, `power`, or `all`. They can
still be named explicitly in an annotation if required.

## Explicit metal-layer override

Use:

``` sh
--metal-layers met1,met2,met3,met4
```

to define the expansion of bare `route`, `power`, and `all` selectors
explicitly.

For example:

``` sh
python3 normalise_magic_def.py in.def out.def \
    --def-blockages \
    --metal-layers met1,met2,met3,met4
```

An explicit annotation such as:

``` text
obs:route(met5)
```

continues to name `met5` explicitly; `--metal-layers` controls the
expansion of selectors whose layer list is omitted.

# Magic coordinate conversion

Magic `.mag` obstruction rectangles must be converted to physical
microns for LibreLane and then, for DEF output, to DEF database units.

The script normally determines the physical Magic coordinate scale from:

-   the `.mag` `magscale` declaration; and
-   the Magic technology file's `cifoutput scalefactor`.

It searches the selected PDK for the corresponding Magic technology
file.

Override the technology file with:

``` sh
--magic-tech /path/to/technology.tech
```

or bypass automatic scale discovery completely with:

``` sh
--mag-unit-um 0.005
```

where the value is the physical size, in microns, of one coordinate unit
stored in the `.mag` file.

If obstruction processing is requested and the physical Magic scale
cannot be established, the script stops with an error rather than
guessing.

For DEF output, the script reads:

``` def
UNITS DISTANCE MICRONS <dbu> ;
```

and requires converted obstruction coordinates to fall exactly on the
DEF database grid.

# Command-line reference

``` text
usage: normalise_magic_def.py [-h]
                              [--design DESIGN]
                              [--specialnets-from DEF]
                              [--ground NET]
                              [--power NET]
                              [--no-default-specialnets]
                              [--format-like-source | --no-format-like-source]
                              [-V] [--mag-source MAG_SOURCE]
                              [--def-blockages]
                              [--librelane-obstructions JSON]
                              [--pdk PDK]
                              [--pdk-root PDK_ROOT]
                              [--magic-tech MAGIC_TECH]
                              [--metal-layers METAL_LAYERS]
                              [--mag-unit-um MAG_UNIT_UM]
                              input output
```

### `input`

Magic-generated input DEF.

### `output`

Normalised output DEF. It must differ from `input`.

### `--design DESIGN`

Set the output `DESIGN` name. The default is the output filename stem.

### `--specialnets-from DEF`

Copy supported power/ground `SPECIALNETS` declarations from another DEF.

### `--ground NET`

Add a `GROUND` special net. May be repeated.

### `--power NET`

Add a `POWER` special net. May be repeated.

This option is unrelated to the `obs:power` obstruction selector.

### `--no-default-specialnets`

Do not automatically add `VGND` and `VPWR` when no explicit special-net
source is supplied.

### `--format-like-source`

Explicitly enable the source-like canonical formatting described above.
This is the default.

### `--no-format-like-source`

Disable the default source-like canonical formatting.

### `-V`, `--verbose`

Print a resolved option/configuration summary, including implicit defaults.
The summary uses the corresponding command-line option names and reports
resolved sources where useful, such as PDK, routing-layer, and Magic
coordinate-scale discovery.

### `--mag-source MAG_SOURCE`

Use this `.mag` file for `obs:` annotations instead of deriving the name
from the input DEF.

### `--def-blockages`

Generate a DEF `BLOCKAGES` section from applicable `obs:` annotations.

### `--librelane-obstructions JSON`

Write a LibreLane obstruction configuration fragment to the specified
JSON file.

### `--pdk PDK`

Explicitly select the PDK. Otherwise `$PDK`, then the `.mag` `tech`
declaration, is used.

### `--pdk-root PDK_ROOT`

Explicitly select the PDK installation root. Otherwise `$PDK_ROOT` is
used.

### `--magic-tech MAGIC_TECH`

Explicit Magic technology file used to determine physical coordinate
scaling.

### `--metal-layers METAL_LAYERS`

Comma-separated layer set used to expand bare `route`, `power`, and
`all` selectors.

### `--mag-unit-um MAG_UNIT_UM`

Explicit physical size in microns of one coordinate unit in the `.mag`
file.

# Complete examples

## Normalise a Magic DEF

``` sh
python3 normalise_magic_def.py \
    example1.def \
    normalised.def
```

## Minimise differences from a TinyTapeout-style source DEF

``` sh
python3 normalise_magic_def.py \
    example1.def \
    tt_um_template.def \
    --design tt_um_template \
    --format-like-source
```

## Generate DEF blockages from `example1.mag`

``` sh
python3 normalise_magic_def.py \
    example1.def \
    output.def \
    --def-blockages
```

## Generate a LibreLane obstruction fragment

``` sh
python3 normalise_magic_def.py \
    example1.def \
    output.def \
    --librelane-obstructions obstructions.json
```

## Generate both representations

``` sh
python3 normalise_magic_def.py \
    example1.def \
    output.def \
    --format-like-source \
    --def-blockages \
    --librelane-obstructions obstructions.json
```

## Use another Magic source

``` sh
python3 normalise_magic_def.py \
    magic-output.def \
    output.def \
    --mag-source tt_um_example.mag \
    --def-blockages
```

## Explicit PDK installation

``` sh
python3 normalise_magic_def.py \
    input.def \
    output.def \
    --def-blockages \
    --pdk sky130A \
    --pdk-root /foss/pdks
```

## Explicit coordinate and routing-layer configuration

``` sh
python3 normalise_magic_def.py \
    input.def \
    output.def \
    --def-blockages \
    --librelane-obstructions obstructions.json \
    --pdk sky130A \
    --metal-layers met1,met2,met3,met4,met5 \
    --mag-unit-um 0.005
```

# Diagnostics and exit status

The script prints a summary describing the transformations performed.

When obstruction processing is active, the summary also reports:

-   obstruction `.mag` source;
-   selected PDK;
-   default metal layers;
-   source of the layer list;
-   physical Magic coordinate unit;
-   number of `obs:` labels found;
-   number of DEF blockage entries generated; and
-   LibreLane fragment filename, when applicable.

Exit status:

-   `0`: completed with no sanity warnings
-   `1`: output was produced, but one or more sanity warnings were
    detected
-   `2`: fatal input, parsing, configuration, or consistency error

Fatal obstruction errors include malformed `obs:` syntax, zero-area
obstruction rectangles, unavailable required PDK/scale information, and
obstruction coordinates that cannot be represented exactly on the DEF
database grid.

# Notes and limitations

-   The script recognises `obs:` annotations only on Magic labels
    attached to `space`.
-   Obstruction annotations are read only when `--def-blockages` and/or
    `--librelane-obstructions` is requested.
-   `power`/PDN-only obstruction has no direct DEF equivalent and is
    therefore omitted from DEF `BLOCKAGES`.
-   Existing DEF `BLOCKAGES` are replaced when `--def-blockages` is
    used; they are not merged.
-   The LibreLane output is a JSON fragment and is not automatically
    merged into another configuration file.
-   The script currently expects the Magic obstruction labels to be
    present directly in the selected `.mag` file's `<< labels >>`
    section; it does not recursively collect annotations from subcells.
-   Explicit layer names in an `obs:` annotation are preserved as
    written. The PDK/default layer list is used for selectors with no
    parenthesised layer list.
