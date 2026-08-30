# Five-day Market Intraday Non-slope Process Map V2 availability correction

MKT-MIN-PATH-001 is invalid before construction because its population contract
incorrectly called the trajectory available at 15:00 Asia/Shanghai. The frozen
MKT-MIN-001 source contract and bound artifact both establish:

- latest included minute: the completed 15:00 bar on Day -1;
- derived session/trajectory `available_at`: Day -1 15:30 Asia/Shanghai;
- first possible action: a later causally valid observation/session; no action is
  created by this representation experiment.

MKT-MIN-PATH-002 inherits every descriptor, operator, neighbor, gate,
compression rule, input hash, prohibition, and claim boundary from the exact
MKT-MIN-PATH-001 scientific design. Only the derived-artifact availability
semantic and output identity are corrected. No representation was constructed
under the invalid 15:00 declaration, so there is no result to retain or compare.
