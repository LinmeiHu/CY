# MKT-MIN-PATH-002 preregistration

Status: `FROZEN_BEFORE_CONSTRUCTION_RESULT`.

Control spec SHA-256:
`161b4bb79795e525940eb6d69d581db22ec1500a025b39b6bd586066ac6bf70c`.

Inherited scientific design SHA-256:
`bf7e05dcba95c647129638f36cd22684c012edf7aca9b0bcbb5e9355bac62327`.

MKT-MIN-PATH-001 stopped before construction because it declared the derived
trajectory available at 15:00. The bound MKT-MIN-001 source contract and
artifact both use Day -1 15:30 Asia/Shanghai availability after the completed
15:00 minute bar. MKT-MIN-PATH-002 corrects only that semantic and its output
identity.

All twelve descriptors, three operators, definition/aggregation neighbors,
gates, compression priority, hashes, prohibitions, no-rescue rule, and claim
boundaries remain identical. No result exists under the invalid predecessor.
The corrected experiment creates no action; the first possible action is later
than 15:30 under a separately valid execution contract.
