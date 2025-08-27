# file: config_loader.py
import os, json
_DEFAULT = {
  "features": {
    "institutions": {
      "enabled": False,
      "source": "twse",
      "include_in_push": True
    }
  }
}
def _deep_merge(a: dict, b: dict) -> dict:
  out = dict(a)
  for k, v in b.items():
    if isinstance(v, dict) and isinstance(out.get(k), dict):
      out[k] = _deep_merge(out[k], v)
    else:
      out[k] = v
  return out
def load_config() -> dict:
  path = os.getenv("CONFIG_FILE", "config.json")
  data = {}
  if os.path.exists(path):
    try:
      with open(path, "r", encoding="utf-8") as f:
        data = json.load(f) or {}
    except Exception:
      data = {}
  cfg = _deep_merge(_DEFAULT, data)
  env_enable = os.getenv("FEATURES_INSTITUTIONS_ENABLED")
  if env_enable is not None:
    cfg["features"]["institutions"]["enabled"] = env_enable.strip() in ("1","true","True","yes","on")
  env_source = os.getenv("FEATURES_INSTITUTIONS_SOURCE")
  if env_source:
    cfg["features"]["institutions"]["source"] = env_source.strip()
  env_include = os.getenv("FEATURES_INSTITUTIONS_INCLUDE_IN_PUSH")
  if env_include is not None:
    cfg["features"]["institutions"]["include_in_push"] = env_include.strip() in ("1","true","True","yes","on")
  return cfg