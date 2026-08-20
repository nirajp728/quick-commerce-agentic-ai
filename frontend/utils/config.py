import os
import streamlit as st


def get_secret(key: str, default: str = "") -> str:
    """
    Reads from st.secrets (local dev, via secrets.toml) first, falling
    back to a real environment variable (ECS/production, where
    secrets.toml isn't present in the image).
    """
    try:
        return st.secrets.get(key, os.environ.get(key, default))
    except Exception:
        return os.environ.get(key, default)