"""Loads the YAML configuration files in /config so rules can be changed without touching code."""
import os
from functools import lru_cache
import yaml

CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))


@lru_cache(maxsize=None)
def load_yaml(name):
    with open(os.path.join(CONFIG_DIR, name), encoding="utf-8") as f:
        return yaml.safe_load(f)


def reload_all():
    load_yaml.cache_clear()
