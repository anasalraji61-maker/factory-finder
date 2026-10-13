# Request (data -> geo owner): extend sea lane graph

`services/geo/src/ff_geo/domain/sea.py` has no waypoint nodes outside the Eurasia-North America belt, so sea hubs below were NOT added to `hubs.json` (distances would be wrong). Please add nodes/edges, then the hubs can be added:

- Japan Pacific coast (JPYOK, JPNGO, JPUKB, JPOSA), Kaohsiung approach, Bay of Bengal (INMAA, INCCU, BDCGP), Indonesia (IDJKT, IDSUB), Thailand (THLCH), Philippines (PHMNL)
- Africa: Cape/Durban (ZADUR, ZACPT), West Africa (NGAPP, Lagos approach), East Africa (KEMBA, TZDAR), Tunisia/Libya (TNRAD, LYMRA, LYTIP), Oman Duqm/Arabian Sea
- Black Sea / Bosphorus (TRSAM, ROCND, GEPTI, UAODS, BGVAR), Adriatic (ITTRS, ITVCE), Baltic north (SEGOT, RULED)
- South Atlantic / South America / Australia (BRSSZ, ARBUE, CLVAP, AUSYD, AUMEL), Pacific Mexico (MXZLO), Oakland/Prince Rupert, US Gulf (USMSY)
