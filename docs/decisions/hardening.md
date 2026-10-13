2026-10-13 | gateway refresh tokens are server-tracked (hashed jti + family), single-use with reuse detection; logout revokes family | closes stateless-refresh finding
2026-10-13 | pre-rotation (jti-less) refresh tokens are rejected, forcing one re-login | simplest safe migration
2026-10-13 | gateway CORS default is empty (native app needs none); dev opts in via env | least privilege
2026-10-13 | rfq offer identity = X-User-Id + gateway-verified X-Supplier-Id; body supplier_ref ignored, supplier_name kept as label, `supplier_verified` added | stops supplier impersonation without breaking response shape
2026-10-13 | WebSocket ?token= kept and documented, no change | mobile clients cannot set headers on WS
