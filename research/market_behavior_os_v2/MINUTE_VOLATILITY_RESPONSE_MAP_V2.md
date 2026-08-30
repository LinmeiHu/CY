# Continuous minute-volatility temporal-response map V2

MKT-MIN-VOL-RESP-002 is an exact semantic retry of the scientific design frozen
in MKT-MIN-VOL-RESP-001 spec `595f2ec5...`.

Pre-result input tests found one economically valid zero in the frozen market
minute-volatility median: 2020-02-03 for all eight governed groups. The
continuous-session minute path can be exactly flat even when the auction gap or
daily move is large. The preregistered log endpoint ratio is undefined when its
current or future endpoint is zero. MKT-MIN-VOL-RESP-001 therefore stopped
before constructing any forward response or reading the confirmation result.

The only semantic correction is the exact log-domain rule:

- construct `log(level[t+h] / level[t])` only when both frozen endpoints are
  finite and strictly positive;
- otherwise the response for that predictor/horizon is missing and excluded
  from its fixed coverage/association calculation;
- the log current-minute-level control is missing when the current level is
  nonpositive;
- never add epsilon, normalize, clip, replace, or relax a coverage gate.

The predictor, five controls, h=5 primary, h=1/3 neighbors, discovery and
untouched confirmation blocks, partial-rank definition, phase-zero non-overlap,
effect/sign/portability/coverage gates, availability, prohibitions, and claim
boundary remain unchanged. This correction is frozen before any response
estimate is computed.
