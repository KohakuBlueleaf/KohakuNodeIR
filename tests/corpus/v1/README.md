# KIR v1 reference results

Every `.kir` file from KohakuNodeIR v1 (commit `1abda17`, `examples/` and
`tests/fixtures/` without the error fixtures), each next to a `.json` holding
what v1's interpreter did with it: status, captured stdout and the final
variable store.

`recorder/record_v1.py` produced them, run against a checkout of `1abda17`:

```
python recorder/record_v1.py <v1-checkout> <this-directory>
```

Functions the examples call but v1 never shipped are replaced by deterministic
stubs whose output spells out the call (`name(in0=..., in1=...)`), so recorded
values witness how data flowed. Each node call counts against a budget of
100 000 calls; programs past it are recorded as `nonterminating`.

Status counts: 46 `ok`, 13 `error`, 2 `nonterminating`, 2 `parse_error`.
Only `ok` files are a reference for v2: v2's reference interpreter, running the
L3 of the same source with the same functions, must reproduce `stdout` and
the final value of every source-level name in `vars` exactly.
