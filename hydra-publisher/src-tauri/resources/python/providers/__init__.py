from .subito import SubitoProvider

# Registry: maps platform id (used by Rust) → provider instance
PROVIDERS = {
    "subito": SubitoProvider(),
}
