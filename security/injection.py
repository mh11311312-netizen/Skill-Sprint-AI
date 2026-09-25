"""Prompt-injection and adversarial-content scanner.
Uploaded documents are DATA. Any text that tries to give instructions to the AI or the system is flagged,
and the flagged clause is quarantined (never sent to the GenAI model, never turned into a requirement)."""
import re

PATTERNS = [
    ("Instruction override", r"\bignore (all |any )?(the )?(previous|prior|above|earlier) (instructions|rules|prompts?)"),
    ("Role hijack", r"\byou are now\b|\bdeveloper mode\b|\bact as (the )?(system|admin)"),
    ("System prompt leak", r"\bsystem prompt\b|\bhidden instructions\b"),
    ("Fake system message", r"^\s*(system|assistant)\s*(instruction)?\s*:|\bSYSTEM INSTRUCTION\b"),
    ("Secret exfiltration", r"\b(api key|connection string|password list|secret key)\b.*\b(output|print|show|reveal|send)\b|\b(output|print|show|reveal|send)\b.*\b(api key|connection string|secret key)\b"),
    ("Fake authority", r"\bas the (system )?administrator\b|\bI (hereby )?authori[sz]e\b"),
    ("Validation bypass", r"\bskip (the )?(python )?validation\b|\bbypass (the )?validation\b|\bmark (every|all|this)\b.*\b(verified|approved)\b"),
    ("Plan manipulation", r"\b(remove|delete) (the )?.{0,60}requirement from\b|\badd a mandatory module\b"),
    ("Unauthorised override claim", r"\bthis (document )?overrides\b|\bsupersedes every earlier version\b"),
]
COMPILED = [(name, re.compile(p, re.I | re.M)) for name, p in PATTERNS]


def scan_text(text):
    """Returns the list of attack types found in a piece of text."""
    return [name for name, rx in COMPILED if rx.search(text or "")]
