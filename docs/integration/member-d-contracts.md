# Member D contract notes

The UI preserves the decimal string and unit verbatim from Member B and displays
the two together in the claim trace. Member B can emit values written on a
0-to-100 percent scale with unit token `percent`, as well as values in `ratio`
units. Never infer the scale from magnitude alone. Keep `percentage_point`
distinct. Human annotations preserve the value and unit as printed.

Current implementation treats the B JSON shape as authoritative. A and B still
need to confirm a normalized UI convention and agree on the API contract before
the evaluation code compares hand-transcribed numeric values to raw slots.

The controlled benchmark uses the nine distinct entries in the detailed Week 3
table. The project should confirm that choice before the research freeze.
