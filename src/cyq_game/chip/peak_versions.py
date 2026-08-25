"""Version identifiers owned by the dependency-free chip layer."""

# V2 persists the complete price-ordered candidate set and gives the ensemble
# its own matched temporal identity.  V1 only persisted a re-ranked scalar
# dominant peak, so it cannot be upgraded safely in place.
PEAK_DEFINITION_VERSION = "canonical-chip-peak-v2"
PEAK_TRACK_VERSION = "temporal-chip-peak-v2"
