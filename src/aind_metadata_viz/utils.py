from enum import Enum


class MetaState(str, Enum):
    VALID = "valid"
    PRESENT = "present"
    MISSING = "missing"
    EXCLUDED = "excluded"