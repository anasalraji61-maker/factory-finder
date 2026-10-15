# logistics -> contracts: per-line `as_of` and `range`

`contracts/schemas/common.schema.json#/$defs/CostLine` has `source` but no timestamp or per-line range (CLAUDE.md rule 8:
every cost line carries currency, source and timestamp; estimates carry a range). Interim: logistics appends
`; priced <ts>; FX <provider> <ts>` to `source`. Please add (additive, optional): `as_of: date-time` and
`range: MoneyRange` (min/max in the line currency; logistics already computes the per-line spread). Logistics will
populate them once the schema exists.
