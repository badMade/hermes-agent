## 2025-05-12 - base_url_hostname caching
**Learning:** Repeated hostname lookups for identical endpoints are a bottleneck when evaluating API configurations, provider constraints, and routing checks for every API call/feature toggle detection.
**Action:** Use `@functools.lru_cache` on functions that do string parsing and are called frequently with the same arguments, like URL parsing helpers.
