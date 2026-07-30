# Lido

Lido is a compiler that reads [CDDL](https://www.rfc-editor.org/rfc/rfc8610)
(Concise Data Definition Language) schemas and generates lightweight,
encoding-independent Data Transfer Objects (DTOs) in multiple target
languages (initially C++, Java, and Rust), together with a per-language
runtime support library that can serialize and deserialize those DTOs to and
from CBOR or JSON.

## Status

**Pre-alpha, Phase 0.** The workspace exists; the compiler does not yet.
Nothing here is usable, and nothing is published. See `doc/plan.md` for the
phase and slice sequencing.

## Documentation

- `doc/specs.md` — requirements (document of record)
- `doc/design.md` — architecture (document of record)
- `doc/code-style.md` — style of *generated* code (document of record)
- `doc/decisions.md` — append-only decision log (document of record)
- `doc/plan.md` — phase and slice sequencing
- `doc/development.md` — how the work gets done

User documentation arrives in slice 10.6.

## License

MIT — see [LICENSE](LICENSE).
