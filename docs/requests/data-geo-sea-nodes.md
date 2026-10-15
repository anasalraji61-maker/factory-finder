# Request (data -> geo owner): extend sea lane graph

**STATUS: DONE (2026-10-15, geo agent).** All regions listed below plus Caribbean, Red Sea, Pacific/Oceania links and the Suez/Hormuz/Malacca/Bab-el-Mandeb/Panama/Gibraltar/Bosphorus chokepoints are modelled in `services/geo/src/ff_geo/domain/sea.py` (174 nodes). Added 21 sea hubs (159 total), 18 countries (with capital/port cities). Additive contract change: `GET /v1/distance?avoid=` (sea mode), `Distance.avoided/confidence/as_of`, `Hub.confidence/as_of`. Data is labelled `confidence: low` (lane graph) / `medium` (port coordinates), `as_of: 2026-10`; nothing is claimed as verified. Validation: `services/geo/tests/test_sea_network.py` (hub connectivity, 40-pair matrix vs published distances and great-circle ratio, edge/land sanity, chokepoint avoidance, API). Also fixed a pre-existing Panama Pacific -> Callao edge that crossed Ecuador/Peru and shortcuts that detoured NY-Rotterdam, Dakar-NY, Kingston-Miami. Known limits: avoiding Hormuz/Bosphorus makes Gulf/Black Sea ports unreachable (422 `sea_route_unavailable`); original request text follows.

---

`services/geo/src/ff_geo/domain/sea.py` has no waypoint nodes outside the Eurasia-North America belt, so sea hubs below were NOT added to `hubs.json` (distances would be wrong). Please add nodes/edges, then the hubs can be added:

- Japan Pacific coast (JPYOK, JPNGO, JPUKB, JPOSA), Kaohsiung approach, Bay of Bengal (INMAA, INCCU, BDCGP), Indonesia (IDJKT, IDSUB), Thailand (THLCH), Philippines (PHMNL)
- Africa: Cape/Durban (ZADUR, ZACPT), West Africa (NGAPP, Lagos approach), East Africa (KEMBA, TZDAR), Tunisia/Libya (TNRAD, LYMRA, LYTIP), Oman Duqm/Arabian Sea
- Black Sea / Bosphorus (TRSAM, ROCND, GEPTI, UAODS, BGVAR), Adriatic (ITTRS, ITVCE), Baltic north (SEGOT, RULED)
- South Atlantic / South America / Australia (BRSSZ, ARBUE, CLVAP, AUSYD, AUMEL), Pacific Mexico (MXZLO), Oakland/Prince Rupert, US Gulf (USMSY)
