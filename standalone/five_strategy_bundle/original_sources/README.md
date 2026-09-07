# Audited source evidence

These files preserve exact audited producer bytes and their hashes. They are provenance evidence, not runtime modules: the installed package is built only from `src/`, and production never imports or executes this directory. The compact runtime extracts under `src/five_strategy_bundle/strategies/` accept all physical data paths from configuration.

- OGR V13: `a156657128053cdeda68e53d5f433de34976353bcc79f25cfab9410bb779dc26`
- OGR V27: `86dd15e8a49da1f6481d3552f02ffbbcdb874eaf6b8b0754220d36b4dee9face`
- OGR V28: `865aa4e0058b69168002ac3ce61014d41fbf502a9541565ecdeec3f075147cce`
- OGR V28R1: `b74bdc04a7b898cbac7bb042601b33d7ae52643af6cff758e22b314ea24a7dc8`
- OGR V28R2: `540863fde51f23efc1fc413385868d58ac0a48575b9ebc0cf9eab64acbca30af`
- ATRDR Bull: `69a83159aa2bd1aa2426268c3036a9759148c19d0f03d15eedf5e7ad95edbfba`
- ATRDR Slow Bear: `4c4992e333c9f7931ca84454e1f71742cf49bcfa8ff333ba8876cc202f351870`
- ATRDR 2026YTD V2: `30fe1f2f738df0285d387e7e0b55b382f77f7ca026649bec3d5e8aa9616428bb`

The exact SMV6 source is intentionally inside the installed package as `strategies/smv6_frozen.py`, because the local callback runtime executes those registered bytes after checking SHA256.
