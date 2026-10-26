# Lido — Requirements Specification

Status: Draft v0.1
Format: [EARS](https://alistairmavin.com/ears/) (Easy Approach to Requirements Syntax)

> Project name: **lido** (matches the repository name; used as-is for the
> crate name, package names, and CLI binary name).

## 1. Purpose

Lido is a compiler that reads [CDDL](https://www.rfc-editor.org/rfc/rfc8610)
(Concise Data Definition Language) schemas and generates lightweight,
encoding-independent Data Transfer Objects (DTOs) in multiple target
languages (initially C++, Java, and Rust), together with a per-language
runtime support library that can serialize and deserialize those DTOs to and
from CBOR or JSON.

The generated DTOs themselves contain no encoding logic. All CBOR/JSON
read/write behavior lives in the runtime library, driven by schema-derived
metadata that Lido emits alongside the DTOs.

## 2. Scope

### 2.1 In scope (v1)

- A CDDL parser and validator covering the **core CDDL subset** defined in
  §3.
- An internal, language-agnostic intermediate representation (IR) of the
  schema.
- Code generator backends for **C++**, **Java**, and **Rust**, producing
  idiomatic, minimal DTO types.
- A first-party runtime support library for each of the three initial
  target languages, implementing CBOR and JSON encode/decode against the
  generated DTOs.
- A standalone command-line interface for invoking the compiler.
- A documented backend extension mechanism so additional target languages
  can be added without modifying the CDDL parser, validator, or IR.

Lido's own implementation language is Rust; see §13 for the requirement
and rationale.

### 2.2 Out of scope (v1)

- Full RFC 8610 grammar (generics, socket/plug extensions `~`, occurrence
  ranges other than `?`, `*`, and bounded `n*m`, complex group-choice
  algebra, and all control operators **except** `.default`, which is
  admitted by §3 — so `.cbor`, `.bits`, `.regexp`, `.size`, `.within`
  and the rest are excluded).
- Build-system plugins (Maven/Gradle plugin, Cargo `build.rs` integration,
  CMake module). v1 ships a CLI only; build-system integration is a
  candidate for a later revision and consuming projects invoke the CLI as a
  pre-build step in the interim.
- Automated schema-evolution tooling: comparing two schema revisions,
  detecting/flagging incompatible changes, computing schema diffs, or
  migrating already-encoded data between incompatible schema versions.
  (The narrower, specific guarantee that additive field changes stay
  wire-compatible in both directions is in scope — see §9.6.)
- Encodings other than CBOR and JSON.
- RTOS targets (e.g. FreeRTOS) as a supported platform. No v1 deliverable
  is validated against an RTOS. However, the C++ and Rust runtime
  libraries SHALL be designed so that adding FreeRTOS support later does
  not require a breaking redesign of their core API — see §9.5.
- Target languages other than C++, Java, and Rust (the extension mechanism
  is in scope; concrete additional backends are not).

## 3. CDDL core subset (v1)

Lido's parser and validator SHALL accept the following CDDL constructs and
SHALL treat all other constructs as unsupported (see REQ-CDDL-050):

- Type definitions (`name = ...`) and named type references.
- **Struct types**: maps with a fixed set of known keys
  (`{ field: type, ... }`). Keys MAY be text strings (`{ name: tstr }`) or
  unsigned integers (`{ 1: tstr }`, COSE-style compact encoding); see
  §3.1.
- **Table types**: maps with an arbitrary number of uniformly typed
  entries (`{ * tstr => int }`), where the key type is `tstr` or `uint`
  and every value shares one type.
- Arrays / homogeneous and fixed-shape heterogeneous lists (`[ type, ... ]`).
- Primitive types: `bool`, `int`, `uint`, `float16/32/64`, `tstr`, `bstr`,
  `null`.
- Optional fields (`?`) and defaulted fields expressed with the
  `.default` control operator (`? retries: uint .default 3`). `.default`
  is the sole control operator admitted in v1 (§2.2).
- Simple occurrence indicators `?` (0 or 1) and `*` (0 or more) on array
  elements and table entries.
- Choice types (`A / B / C`) over named types, for mapping to tagged
  unions / sum types / enums.
- Enumerations of literal values, of either text strings
  (`"red" / "green" / "blue"`) or unsigned integers (`10 / 20 / 30`). A
  single enumeration draws its literals from one of those two kinds and
  not both; negative and floating-point literals are outside the v1
  subset.
- Nested and forward type references within the same schema document.
- Comments and whitespace per RFC 8610 §2.
- Basic numeric ranges (`x..y`) on integer and float types.

### 3.1 Map key encoding

Integer keys are admitted because they materially reduce CBOR payload
size on constrained links — a primary motivation for CBOR on the
embedded targets contemplated in §9.5. They interact with JSON, which
has no integer-keyed object form, so:

- **REQ-KEY-010** The system SHALL support struct and table types keyed
  by text strings or by unsigned integers, and SHALL record the key and
  its CBOR type in the wire metadata for each field.
- **REQ-KEY-020** The system SHALL NOT permit a single map type to mix
  text-string and integer keys.
- **REQ-KEY-030** WHEN encoding an integer-keyed map to JSON, the
  runtime library SHALL emit the decimal representation of the integer
  key as a JSON object member name (e.g. CBOR key `1` becomes `"1"`),
  and WHEN decoding JSON into an integer-keyed map SHALL parse member
  names back to integers.
- **REQ-KEY-040** IF a JSON object member name in an integer-keyed map
  is not a valid decimal representation of an integer within the key
  type's range, THEN the runtime library SHALL raise a decode error.
- **REQ-KEY-050** The system SHALL derive a field's wire key solely from
  the schema (the declared text or integer key), never from the field's
  declaration order or its generated identifier name, so that
  reordering or renaming in the target language cannot change the wire
  format.

## 4. Definitions

| Term | Meaning |
|---|---|
| CDDL | Concise Data Definition Language (RFC 8610), the schema input format. |
| DTO | Data Transfer Object: a plain data type with fields and no behavior. |
| IR | Lido's internal, language-agnostic representation of a parsed schema. |
| Backend | A code generator module that turns the IR into a specific target language's DTOs. |
| Runtime library | The per-language library that generated DTOs depend on for CBOR/JSON encode/decode. |
| Target language | A language Lido can generate DTOs for (C++, Java, Rust in v1). |
| Wire metadata | Schema-derived information (map keys, array positions, type tags) needed to encode/decode a DTO, independent of the target language's field-naming conventions. |
| Compilation unit | The complete set of CDDL input files supplied to a single CLI invocation, resolved together as one namespace of type definitions. |
| Struct type | A map type with a fixed, schema-declared set of keys, generated as a DTO with one field per key. |
| Table type | A map type with an arbitrary number of uniformly typed key/value entries, generated as a map/dictionary container. |

## 5. Architecture requirements

To keep the multi-language effort tractable, Lido's internal structure
SHALL separate language-independent work from per-language work, so that
adding CDDL features benefits all backends at once and adding a language
does not require re-implementing schema parsing or validation.

- **REQ-ARCH-010** The system SHALL implement CDDL parsing, validation, and
  IR construction exactly once, shared by all backends.
- **REQ-ARCH-020** The system SHALL define a stable IR schema (data model)
  that is the sole input to every code generation backend.
- **REQ-ARCH-030** The system SHALL implement each target language's code
  generator as an independent backend module that consumes only the IR and
  produces source files for that language, with wire metadata embedded in
  those files per REQ-GEN-030.
- **REQ-ARCH-040** The system SHALL NOT allow a backend module to modify or
  depend on another backend module's implementation.
- **REQ-ARCH-050** The system SHALL implement each target language's
  runtime library as an independent module, native and idiomatic to that
  language, conforming to a shared, documented conceptual contract (see
  §9) rather than shared source code.
- **REQ-ARCH-060** The system SHALL maintain a single, language-independent
  suite of CDDL test fixtures and expected wire-format vectors (CBOR and
  JSON bytes/text for representative values) that every backend and
  runtime library is validated against, so conformance is defined once and
  checked identically across languages. Byte-exact comparison against
  these vectors is well-defined because encoding is canonical
  (REQ-RT-160/170); the suite SHALL additionally include
  non-deterministically encoded inputs to exercise REQ-RT-180, and
  malformed inputs to exercise §9.4.
- **REQ-ARCH-070** WHERE a new target language backend is added, the
  system SHALL require only: (a) a new backend module implementing the
  backend interface (REQ-EXT-010), and (b) a new runtime library
  implementing the shared runtime contract (REQ-EXT-020).

## 6. CDDL parsing and validation requirements

- **REQ-CDDL-010** The system SHALL parse input files conforming to the
  CDDL core subset defined in §3 into the IR.
- **REQ-CDDL-020** The system SHALL resolve named type references within a
  schema document, including forward references.
- **REQ-CDDL-030** The system SHALL support schemas split across multiple
  input files with cross-file type references within a single compilation
  unit.
- **REQ-CDDL-040** IF a schema references an undefined type name, THEN the
  system SHALL report a validation error identifying the referencing
  location and the unresolved name, and SHALL NOT generate output for that
  compilation unit.
- **REQ-CDDL-050** IF a schema uses a CDDL construct outside the core
  subset defined in §3, THEN the system SHALL report it as an unsupported-
  construct error identifying the file, line, and column, and SHALL NOT
  silently ignore or approximate it.
- **REQ-CDDL-060** IF a schema contains a syntax error, THEN the system
  SHALL report the file, line, and column of the error and a description
  of what was expected.
- **REQ-CDDL-070** WHEN a schema defines a choice type (`A / B / C`) over
  named types, the system SHALL represent it in the IR as a discriminated
  union with one variant per alternative.
- **REQ-CDDL-080** WHEN a schema defines an enumeration of literal values,
  the system SHALL represent it in the IR as a named enumeration type.
- **REQ-CDDL-090** The system SHALL detect cyclic type references during
  validation and SHALL classify each cycle, independent of any target
  language, as either *breakable* — the cycle passes through at least one
  optional field, array/list element, or table value, all of which admit
  an indirection in every target language — or *unbreakable*, where every
  edge in the cycle is a required, directly-embedded struct field.
- **REQ-CDDL-095** IF a type cycle is unbreakable (REQ-CDDL-090), THEN the
  system SHALL report a validation error naming the participating types,
  because such a type has no finite representation in any target language.
- **REQ-CDDL-097** WHEN a type cycle is breakable, the system SHALL mark
  the breaking edge in the IR, and each backend SHALL generate the
  target language's idiomatic indirection at that edge (e.g. `Box<T>` in
  Rust, a smart pointer in C++, an ordinary reference in Java).

## 7. Intermediate representation requirements

- **REQ-IR-010** The IR SHALL represent, for every defined type: its name,
  its kind (struct/map, array/list, choice/union, enum, primitive alias),
  and its fields or variants.
- **REQ-IR-020** The IR SHALL represent, for every field: its name, its
  type reference, its optionality, its default value (if any), and its
  wire metadata (map key or array position).
- **REQ-IR-030** The IR SHALL be independent of any target language's
  naming conventions, keywords, or type system limitations.
- **REQ-IR-040** The system SHALL serialize the IR to a stable,
  documented, language-neutral file format (e.g. JSON) usable as a
  debugging artifact and as input to third-party or experimental backends.
- **REQ-IR-050** The serialized IR SHALL carry an explicit schema-version
  identifier, and the system SHALL reject a serialized IR whose version
  it does not support rather than misinterpreting it.

## 8. Code generation requirements (common to all backends)

> The concrete API style that satisfies "language-idiomatic" below (e.g.
> fluent builders for C++/Java, idiomatic Rust struct conventions) is
> defined in `doc/code-style.md`, not restated here — this section
> constrains behavior, not surface API shape.

- **REQ-GEN-010** WHEN generating DTOs for a target language, the system
  SHALL produce one type per IR-defined type, using field names adapted to
  the target language's idiomatic naming convention while preserving the
  original CDDL name as wire metadata.
- **REQ-GEN-020** The system SHALL generate DTO types containing only data
  fields and language-idiomatic accessors/constructors required for the
  DTO to be usable (e.g. constructors, equality, and value accessors), and
  SHALL NOT generate CBOR- or JSON-specific logic inside the DTO type
  itself.
- **REQ-GEN-030** The system SHALL emit each DTO's wire metadata (map
  keys, array positions, variant discriminants) as part of the generated
  source for that DTO — compiled in as literal constants in generated
  encode/decode code — rather than as a separate metadata artifact
  loaded or reflected over at runtime. This keeps encoding independent of
  runtime type information, which REQ-RT-140 and §9.5 require for
  constrained targets.
- **REQ-GEN-040** WHEN a CDDL field is optional, the system SHALL generate
  it using the target language's idiomatic optional representation per
  §8.1: `std::optional<T>` in C++, `java.util.Optional<T>` in Java, and
  `Option<T>` in Rust.
- **REQ-GEN-050** WHEN a CDDL type is an array/list, the system SHALL
  generate it using the target language's idiomatic sequence container.
- **REQ-GEN-060** WHEN a CDDL type is a choice/union, the system SHALL
  generate it using the target language's idiomatic sum-type or tagged-
  union representation.
- **REQ-GEN-070** WHEN generating output for a given schema and target
  language, the system SHALL produce byte-for-byte identical output across
  repeated runs with unchanged input (deterministic generation).
- **REQ-GEN-080** The system SHALL embed the Lido version and source
  schema file name(s) as a comment header in every generated source file.
  Source file names SHALL be recorded as paths relative to the
  compilation unit's root, never as absolute paths, so that generated
  output is reproducible across machines and CI checkouts (REQ-GEN-070).
- **REQ-GEN-090** IF a CDDL identifier collides with a reserved keyword
  of the target language, or is otherwise not a legal identifier there,
  THEN the system SHALL apply a deterministic, documented mangling rule
  (e.g. appending a trailing underscore) rather than reporting an error.
  The field's wire key is unaffected (REQ-KEY-050), so mangling is
  invisible in encoded data, and a single schema therefore remains valid
  across every backend as REQ-GEN-120 requires.
- **REQ-GEN-095** IF mangling under REQ-GEN-090 would produce a name that
  collides with another generated name in the same scope, THEN the
  system SHALL report a generation error identifying both names, rather
  than emitting source that does not compile.
- **REQ-GEN-100** WHERE a namespace/package/module name is supplied via
  CLI configuration, the generated code for that backend SHALL be placed
  under that namespace/package/module.
- **REQ-GEN-110** The system SHALL map CDDL types to target language
  types according to the normative table in §8.1.
- **REQ-GEN-120** Each of the three v1 backends (C++, Java, Rust) SHALL
  support the entire CDDL core subset defined in §3. There is no
  partial-support mechanism in v1 (REQ-EXT-040 is deferred); a backend
  that cannot generate correct code for every construct in §3 is not a
  supported backend.

### 8.1 CDDL to target language type mapping (normative)

| CDDL | C++17 | Java 17 | Rust |
|---|---|---|---|
| `bool` | `bool` | `boolean` | `bool` |
| `uint` | `std::uint64_t` | `long` (unsigned semantics) | `u64` |
| `int` | `std::int64_t` | `long` | `i64` |
| `float16` | `float` | `float` | `f32` |
| `float32` | `float` | `float` | `f32` |
| `float64` | `double` | `double` | `f64` |
| `tstr` | `std::string` | `String` | `String` |
| `bstr` | `std::vector<std::uint8_t>` | `byte[]` | `Vec<u8>` |
| `null` (alone) | `std::monostate` | `Void` (always null) | `()` |
| array of `T` | `std::vector<T>` | `List<T>` (immutable) | `Vec<T>` |
| table `{* K => V}` | `std::map<K, V>` | `Map<K, V>` (immutable) | `BTreeMap<K, V>` |
| optional `T` | `std::optional<T>` | `Optional<T>` | `Option<T>` |
| choice | `std::variant<...>` | `sealed interface` | `enum` |
| enum of literals | `enum class` | `enum` | fieldless `enum` |

- **REQ-GEN-130** The system SHALL NOT narrow a field's generated integer
  type based on its declared numeric range in v1: a ranged field uses the
  same mapping as its unranged base type (§8.1), and the range is enforced
  at runtime per REQ-RT-240/250. Backend-optional narrowing was considered
  and rejected because the generated field type is user-visible API, so
  narrowing applied by some backends and not others would give the same
  schema materially different APIs per language; revisiting it requires a
  normative narrowing table applied uniformly by every backend.
- **REQ-GEN-140** `float16` has no native representation in the three v1
  target languages; the system SHALL map it to a 32-bit float in
  generated code while preserving `float16` in the wire metadata, so
  that CBOR encoding emits the half-precision form. Because a 32-bit
  field can hold values not exactly representable in half precision,
  encoding such a value is an error rather than a silent narrowing —
  see REQ-RT-255.
- **REQ-GEN-150** Ordered map/`BTreeMap`/`std::map` containers are
  specified for table types so that iteration order is deterministic,
  as required for canonical encoding by REQ-RT-160.
- **REQ-GEN-160** WHERE a target language's default equality for a mapped
  type is identity-based rather than value-based — notably Java's
  `byte[]`, whose array equality would otherwise defeat a `record`'s
  generated `equals`/`hashCode` — the system SHALL generate explicit
  value-based `equals`/`hashCode` (or the language's equivalent), so that
  REQ-GEN-020's equality guarantee holds for every generated DTO.
- **REQ-GEN-170** WHEN a field is optional and also carries a `.default`
  value, the system SHALL generate it as a non-optional field of the
  underlying type, initialized to the default, rather than as a nested
  optional, since REQ-RT-080 guarantees the field is always populated
  after decoding.

### 8.2 Developer experience of generated code

These requirements exist because generated code is read, debugged, and
maintained by people who did not write it and may not have seen the
schema.

- **REQ-GEN-180** WHEN a CDDL comment immediately precedes a type or
  field definition, the system SHALL emit its text as a documentation
  comment on the corresponding generated type or field, in the target
  language's documentation-comment syntax (`///` in Rust, `/** */`
  Javadoc in Java, `///` in C++), so that schema intent is visible in
  IDE hover and generated API documentation.
- **REQ-GEN-185** The system SHALL mark every generated file as
  machine-generated with an `@generated` marker in its header comment,
  and SHALL emit code formatted according to the target language's
  conventional formatter defaults, so that generated files are
  recognizable to review tooling and do not appear unformatted beside
  hand-written code.
- **REQ-GEN-190** The system SHALL emit, in generated code, an assertion
  of the runtime-library API version the code was generated against,
  such that compiling or linking generated code against an incompatible
  runtime library version fails with a diagnostic naming the version
  mismatch, rather than failing obscurely or silently changing wire
  behavior.
- **REQ-GEN-195** The Lido version stamp required by REQ-GEN-080 SHALL
  be written to a single generated manifest file per target language,
  and SHALL NOT be repeated in every generated source file, so that
  upgrading Lido does not produce a diff touching every file in
  projects that commit generated code to version control.
- **REQ-GEN-200** WHERE ecosystem-interop generation is requested
  (REQ-CLI-058), the system SHALL additionally emit that language's
  native serialization bindings (e.g. `serde` derives in Rust, Jackson
  annotations in Java) on generated DTOs. Such bindings SHALL be
  additive: they SHALL NOT alter the DTO's fields, its Lido codec, or
  any wire-format guarantee, and the generated documentation SHALL
  state that encoding via those bindings bypasses Lido's canonical
  encoding (§9.1) and constraint validation (§9.3).

## 9. Runtime library requirements (shared contract)

Each per-language runtime library is a separate, idiomatic implementation,
but all SHALL satisfy the same conceptual contract. Where requirements
below say encoding or decoding is "driven by that DTO's wire metadata",
that metadata is the compiled-in constants of the DTO's generated
encode/decode code (REQ-GEN-030), not a runtime-loaded table or
reflection over the DTO type; the runtime library supplies the encoding
machinery, and the generated code supplies the per-type schema knowledge.

- **REQ-RT-010** The runtime library SHALL provide a function/method to
  encode any generated DTO instance to CBOR bytes, driven by that DTO's
  wire metadata.
- **REQ-RT-020** The runtime library SHALL provide a function/method to
  decode CBOR bytes into a generated DTO instance, driven by that DTO's
  wire metadata.
- **REQ-RT-030** The runtime library SHALL provide a function/method to
  encode any generated DTO instance to JSON text, driven by that DTO's
  wire metadata.
- **REQ-RT-040** The runtime library SHALL provide a function/method to
  decode JSON text into a generated DTO instance, driven by that DTO's
  wire metadata.
- **REQ-RT-050** For a given DTO instance, the system SHALL ensure the
  CBOR encoding and the JSON encoding represent the same logical data,
  using the standard CBOR–JSON mapping (RFC 8949 §6.1) for values
  representable in both, and the normative rules of §9.2 for values
  that are not.
- **REQ-RT-060** IF CBOR input contains a value that cannot be represented
  in the target DTO's schema (e.g. wrong type, missing required field,
  unknown enum/choice discriminant), THEN the runtime library SHALL raise
  a decode error identifying the offending field, rather than silently
  coercing or dropping data. This does not include additional,
  unrecognized map fields, which are handled per REQ-COMPAT-020.
- **REQ-RT-065** A decode or encode error raised under REQ-RT-060/070 or
  elsewhere in §9 SHALL identify the offending value by its **path from
  the root of the DTO** (e.g. `order.items[3].price`), not by field name
  alone, and SHALL state what was expected and what was found. Decode
  errors SHALL additionally report the byte offset (CBOR) or line/column
  (JSON) at which the problem occurred. A bare field name is not
  actionable in a nested payload, which is where decode failures are
  most likely and hardest to diagnose.
- **REQ-RT-070** IF JSON input contains a value that cannot be represented
  in the target DTO's schema, THEN the runtime library SHALL raise a
  decode error identifying the offending field. This does not include
  additional, unrecognized map fields, which are handled per
  REQ-COMPAT-020.
- **REQ-RT-080** WHEN a DTO field is absent in CBOR/JSON input and the
  field is optional or has a schema default, the runtime library SHALL
  populate it with the absent-value representation or default rather than
  raising an error.
- **REQ-RT-090** The runtime library SHALL NOT require the DTO's consumer
  to hand-write any per-type encode/decode code.
- **REQ-RT-095** The functions required by REQ-RT-010–040 SHALL be
  callable in a single expression that takes a DTO (or bytes/text) and
  returns bytes/text (or a DTO), without the caller constructing,
  configuring, or wiring together encoder, decoder, or writer objects.
  Those lower-level types SHALL remain public for callers who need to
  configure decode limits or reuse a codec, but SHALL NOT be on the
  path of the common case.
- **REQ-RT-097** The functions required by REQ-RT-010–040 SHALL be free
  functions or static entry points in the runtime library, not methods
  generated onto the DTO type, consistent with REQ-GEN-020's
  prohibition on encoding logic inside DTOs.
- **REQ-RT-098** In addition to the allocating forms required by
  REQ-RT-010/030, the runtime library SHALL provide encode entry points
  that write into a caller-supplied, reusable output buffer without
  allocating a new one per call. The allocating form remains the
  documented default; this variant serves hot paths that encode
  repeatedly, and is the same mechanism REQ-RT-150 requires for
  caller-supplied buffers on constrained targets.
- **REQ-RT-100** The runtime library SHALL depend only on its target
  language's standard library plus a small number of third-party
  primitive CBOR/JSON libraries per language — typically one per encoding
  format, subject to REQ-DEP-020 and REQ-DEP-030 (e.g. it may sit atop an
  existing low-level CBOR/JSON reader/writer rather than implementing
  byte-level encoding from scratch) — and SHALL NOT require a full
  separate serialization framework.

### 9.1 Deterministic encoding

Byte-exact conformance vectors shared across three independent runtime
implementations (REQ-ARCH-060) are only well-defined if encoding is
canonical. Deterministic output additionally allows payloads to be
hashed or signed.

- **REQ-RT-160** The runtime library SHALL emit CBOR conforming to the
  core deterministic encoding requirements of RFC 8949 §4.2: definite
  lengths for all maps, arrays, and strings; integers, and CBOR head
  fields generally, in their shortest form; map keys sorted in
  bytewise lexicographic order of their encoded form; and floats
  encoded in the shortest form that round-trips the value exactly.
- **REQ-RT-165** The key ordering required by REQ-RT-160 SHALL be
  computed over each key's *encoded* bytes, including the CBOR head
  byte, and NOT over the key's logical value. Because the head byte
  encodes length, shorter text keys therefore sort before longer ones
  regardless of alphabetical order (`"age"` → `0x63…` precedes
  `"name"` → `0x64…` precedes `"email"` → `0x65…`), and unsigned
  integer keys sort in numeric order. This is called out explicitly
  because a naive alphabetical or declaration-order sort produces
  non-conforming output that still round-trips correctly and so is
  easily missed in review.
- **REQ-RT-170** The runtime library SHALL produce byte-identical CBOR
  output for equal DTO instances, both across repeated runs and across
  target languages.
- **REQ-RT-172** WHEN encoding a NaN to CBOR, the runtime library SHALL
  emit the half-precision quiet NaN `0xf97e00`, regardless of the
  source value's sign or payload, and WHEN decoding SHALL accept any
  NaN encoding. RFC 8949 §4.2 does not fix a canonical NaN, and
  REQ-RT-160's "shortest form that round-trips" cannot, because NaN
  payloads are not preserved across widths; without this rule three
  runtimes could emit three NaN encodings for equal DTO instances,
  contrary to REQ-RT-170. The infinities need no rule of their own: they
  have a unique shortest form (`0xf97c00`, `0xf9fc00`).
- **REQ-RT-175** The runtime library SHALL emit JSON containing no
  insignificant whitespace — no space, tab, or line break between
  tokens — and WHEN decoding SHALL accept JSON containing arbitrary
  insignificant whitespace as permitted by RFC 8259 §2. Without a fixed
  emitted form the JSON half of the conformance suite (REQ-ARCH-060)
  cannot be compared byte-exactly, and two runtime libraries could emit
  visibly different documents while both being "correct".
- **REQ-RT-177** The runtime library SHALL emit the members of a JSON
  object in the canonical order REQ-RT-160/165 define for CBOR map keys —
  bytewise over each key's *CBOR-encoded* form — so that a single
  generation-time field order serves both encodings. Together with
  REQ-RT-175 this gives JSON the property REQ-RT-170 gives CBOR: equal
  DTO instances produce byte-identical JSON across repeated runs and
  across target languages. Two consequences are called out because both
  are easy to implement wrongly and hard to see in review: JSON member
  order is length-first rather than alphabetical
  (`{"age":…,"name":…,"email":…}`); and for integer-keyed maps the order
  is numeric, which is *not* the lexicographic order of the decimal
  member names REQ-KEY-030 produces — `"9"` precedes `"10"`.
- **REQ-RT-178** WHEN encoding a `float16`, `float32`, or `float64`
  value to JSON, the runtime library SHALL write it as a JSON number
  using the shortest decimal digit sequence that reads back as exactly
  the same value, laid out as ECMAScript `Number::toString` lays out a
  double (as adopted by RFC 8785 §3.2.2.3): no fraction or exponent for
  an integral value with magnitude below 10^21 (so `1.0` is written
  `1`), no leading zeros, a lowercase `e` with an explicit sign for an
  exponent (`1e+21`, `5e-7`), and decimal notation for magnitudes from
  10^-6 up to 10^21. "Reads back as exactly the same value" is
  evaluated at the field's *held* width: `float16` and `float32` fields
  (both held as 32-bit floats, §8.1) use the shortest digits that round-
  trip as a 32-bit float (`3.4028235e+38`, not its double expansion),
  and `float64` fields those that round-trip as a 64-bit float.
  Negative zero SHALL be written `-0`, where RFC 8785 would write `0`,
  so the sign survives. WHEN decoding a JSON number into a float field
  the runtime library SHALL accept any number permitted by RFC 8259 §6
  and round it to the nearest value of the field's width. Floats are
  never written as JSON strings; REQ-RT-220's string form applies only
  to integer types. The default float printers of the three target
  languages disagree (`1.0E300`, `1e+300`, `1.0e300`), so without this
  rule the JSON half of the conformance suite (REQ-ARCH-060) could not
  be compared byte-exactly.
- **REQ-RT-179** WHEN encoding a string to JSON — a `tstr` value or an
  object member name — the runtime library SHALL escape only the
  quotation mark (`\"`), the reverse solidus (`\\`), and the characters
  U+0000 to U+001F, using the short forms `\b`, `\f`, `\n`, `\r`, `\t`
  where RFC 8259 §7 defines them and otherwise `\u` followed by four
  lowercase hexadecimal digits; every other character, including all
  non-ASCII characters and U+007F, SHALL be written as raw UTF-8, and
  `/` SHALL NOT be escaped. WHEN decoding, the runtime library SHALL
  accept every escape form RFC 8259 §7 permits. As with REQ-RT-175, a
  fixed emitted form is what makes byte-exact comparison possible.
- **REQ-RT-180** The runtime library SHALL accept non-deterministically
  encoded CBOR input that is otherwise schema-valid (e.g. indefinite-
  length items, non-canonically ordered map keys), so that Lido peers
  can interoperate with encoders that do not apply RFC 8949 §4.2.
- **REQ-RT-190** WHEN a field carries a schema default and its value
  equals that default, the runtime library SHALL still write the field
  explicitly rather than omitting it, so that encoding depends only on
  the DTO's value and not on how it was constructed (REQ-RT-170).

### 9.2 CBOR and JSON representation differences

REQ-RT-050 requires the two encodings to represent the same logical
data, but JSON cannot natively express parts of the §3 subset. The
following rules are normative rather than left to RFC 8949 §6.1's
recommendations:

- **REQ-RT-200** WHEN encoding a `bstr` to JSON, the runtime library
  SHALL emit base64url without padding (per RFC 8949 §6.1), and WHEN
  decoding SHALL accept base64url with or without padding.
- **REQ-RT-210** WHEN encoding a `float16`/`float32`/`float64` value
  that is NaN or ±Infinity to JSON, the runtime library SHALL raise an
  encode error identifying the field, since JSON has no representation
  for these values and silently substituting `null` would corrupt data.
- **REQ-RT-220** WHEN encoding a `uint` or `int` whose magnitude exceeds
  2^53−1 to JSON, the runtime library SHALL emit it as a JSON string
  rather than a JSON number, and WHEN decoding SHALL accept either form
  for integer-typed fields, because many JSON parsers silently lose
  precision on integers outside the IEEE-754 double-exact range.
- **REQ-RT-230** The runtime library SHALL apply the integer-keyed map
  rules of REQ-KEY-030/040 when converting between the two encodings.

### 9.3 Schema constraint validation

- **REQ-RT-240** WHEN decoding a field declared with a numeric range
  (`x..y`), the runtime library SHALL verify the decoded value lies
  within that range and SHALL raise a decode error identifying the
  field if it does not.
- **REQ-RT-250** WHEN encoding a field declared with a numeric range,
  the runtime library SHALL verify the value lies within that range and
  SHALL raise an encode error identifying the field if it does not,
  so that a Lido encoder cannot emit data its own schema rejects.
- **REQ-RT-255** WHEN encoding a field declared `float16` (held as a
  32-bit float per REQ-GEN-140), the runtime library SHALL verify the
  value is exactly representable in half precision and SHALL raise an
  encode error identifying the field if it is not. This makes the
  half-precision form also the shortest form that round-trips the value
  exactly, so REQ-GEN-140 and REQ-RT-160 agree rather than demanding
  different bytes for the same value.
- **REQ-RT-260** WHERE a field's generated type already makes
  out-of-range values unrepresentable (e.g. a `0..255` range on a field
  whose target type cannot hold values outside that range), the runtime
  library MAY omit the corresponding check. Since v1 does not narrow
  integer types (REQ-GEN-130), this applies only where the declared
  range happens to coincide with the mapped type's own limits.

### 9.4 Robustness against malformed and hostile input

Decoders are expected to run on network-facing and embedded targets, so
untrusted input SHALL NOT be able to exhaust memory or stack.

- **REQ-RT-270** The runtime library SHALL enforce a configurable
  maximum nesting depth when decoding CBOR or JSON, and SHALL raise a
  decode error rather than recursing without bound.
- **REQ-RT-280** The runtime library MAY pre-allocate from a length
  field in untrusted input only up to what the remaining input could
  actually supply — i.e. reserved capacity SHALL be clamped to the
  bytes remaining in the input buffer (or, for element counts, to the
  maximum number of elements those bytes could encode), and SHALL
  additionally respect the bounds of REQ-RT-290. A declared length
  larger than the input can satisfy SHALL NOT cause an allocation
  proportional to the declared value. This permits single-allocation
  decoding of strings and collections while closing the
  declared-but-absent-length OOM vector, since an attacker cannot
  inflate the reservation beyond the payload actually transmitted.
- **REQ-RT-290** The runtime library SHALL support configurable upper
  bounds on decoded string/byte-string length and on collection element
  count, and SHALL raise a decode error when a bound is exceeded.
- **REQ-RT-300** IF a decoded map contains duplicate keys, THEN the
  runtime library SHALL raise a decode error rather than silently
  accepting a last-wins or first-wins interpretation.
- **REQ-RT-310** IF CBOR or JSON input is truncated or otherwise
  syntactically malformed, THEN the runtime library SHALL raise a decode
  error and SHALL NOT read beyond the supplied input buffer.
- **REQ-RT-315** WHEN decoding a `tstr` value, the runtime library SHALL
  validate that the input is well-formed UTF-8 and SHALL raise a decode
  error identifying the field if it is not. Without this, the same
  malformed input would be rejected by Rust (whose `String` enforces
  UTF-8), transcoded by Java (UTF-16 `String`), and silently accepted by
  C++ (byte-oriented `std::string`), violating REQ-RT-170's requirement
  that the three runtimes behave equivalently.

### 9.5 Forward-looking portability constraints (C++ and Rust)

Not a v1 target, but the C++ and Rust runtime libraries are intended to
eventually run on FreeRTOS-based targets. Retrofitting exception-free,
threading-free, or `no_std` support after the core API has shipped tends
to be a breaking change, so v1's core encode/decode API SHALL be designed
under the following constraints now. These do not apply to the Java
runtime library, since a JVM is not a realistic FreeRTOS target.

- **REQ-RT-110** The Rust runtime library's core encode/decode logic
  SHALL be `no_std`-compatible (`no_std` + `alloc`), with any
  `std`-only conveniences (e.g. `std::error::Error` impls, filesystem
  helpers) gated behind an optional, non-default `std` feature.
- **REQ-RT-120** The C++ runtime library's core encode/decode API SHALL
  NOT require C++ exceptions to be enabled to report errors; it SHALL
  expose a non-throwing (error-code or result-type) path usable when
  compiled with `-fno-exceptions`, and SHALL NOT rely on RTTI.
- **REQ-RT-130** The C++ and Rust runtime libraries' core encode/decode
  operations SHALL NOT require OS-provided threading primitives (threads,
  mutexes, thread-local storage); any concurrency support SHALL be
  additive and optional.
- **REQ-RT-140** The C++ and Rust runtime libraries SHALL NOT depend on
  filesystem or OS-environment APIs for core encode/decode functionality.
- **REQ-RT-150** WHERE the underlying primitive CBOR/JSON library for C++
  or Rust supports caller-supplied buffers/allocators in place of
  library-internal heap allocation, the runtime library SHALL expose that
  option rather than hiding it behind a mandatory internal allocation
  strategy.

### 9.6 Wire compatibility for additive schema changes

Automated cross-revision compatibility *checking* remains out of scope
for v1 (§2.2). However, the specific, common case of adding a field to a
schema is a first-class, in-scope guarantee of the wire format and
runtime library design: systems evolve by adding fields, and that SHALL
work without regenerating and redeploying every reader and writer in
lockstep.

- **REQ-COMPAT-010** (old-writer / new-reader) WHEN a DTO compiled from a
  newer schema revision decodes CBOR or JSON data written by a DTO
  compiled from an older revision of the same schema that lacked one or
  more of the newer schema's fields, the runtime library SHALL populate
  each missing field from its absent-value representation or schema
  default (per REQ-RT-080) rather than raising an error, PROVIDED each
  such field was added as optional or defaulted.
- **REQ-COMPAT-020** (new-writer / old-reader) WHEN a DTO compiled from an
  older schema revision decodes CBOR or JSON data written by a DTO
  compiled from a newer revision of the same schema that added one or
  more struct fields unknown to the older schema, the runtime library
  SHALL discard the unrecognized map entries and successfully decode the
  fields it does recognize, rather than raising an error.
- **REQ-COMPAT-025** Unrecognized fields discarded under REQ-COMPAT-020
  SHALL NOT be retained or re-emitted on a subsequent encode. A
  consequence, which authors SHALL be warned of in user documentation,
  is that a component built against an older schema that decodes,
  modifies, and re-encodes a payload silently strips fields added by
  newer peers; such read-modify-write intermediaries SHOULD be rebuilt
  against the newest schema revision in use. Retaining unknown fields
  was considered and rejected for v1 because it requires unbounded
  dynamic storage on every DTO, conflicting with the constrained-target
  goals of §9.5.
- **REQ-COMPAT-030** The system SHALL derive struct field wire keys per
  REQ-KEY-050 (from the schema, never from declaration order), so that
  adding a field cannot change the wire key of any pre-existing field.
- **REQ-COMPAT-035** WHERE a struct type uses integer keys (§3.1), the
  compatibility guarantees of REQ-COMPAT-010/020 hold only if newly
  added fields are assigned previously unused integer keys. Reusing the
  integer key of a removed field silently reinterprets old data as the
  new field's type and SHALL be documented as unsafe.
- **REQ-COMPAT-040** This guarantee covers only struct types with newly
  added optional or defaulted fields. It explicitly does NOT cover — and
  Lido does not guarantee compatibility across, nor detect in v1 —
  removing or renaming a field, changing a field's type, changing an
  existing field from optional to required, reusing an integer key
  (REQ-COMPAT-035), inserting or reordering elements of a
  positionally-encoded (array-shaped) type (appending is safe;
  inserting/reordering is not), or adding/removing choice/enum variants.
  Authors making such changes are responsible for the consequences.
- **REQ-COMPAT-050** Table types (§3) carry no added-field compatibility
  concern, since their keys are data rather than schema; changing a
  table's key or value type is a breaking change covered by
  REQ-COMPAT-040.
- **REQ-COMPAT-060** WHEN decoding a fixed-shape array type whose input
  contains more elements than the schema declares, the runtime library
  SHALL decode the declared leading elements and discard the extra
  trailing elements, rather than raising an error. This is what makes
  REQ-COMPAT-040's "appending is safe" claim true for arrays; it is the
  positional analogue of REQ-COMPAT-020's unknown-map-field handling,
  and like it, discarded elements are not retained (REQ-COMPAT-025).
  Input with *fewer* elements than declared remains an error under
  REQ-RT-060 unless the missing trailing elements are optional.

### 9.7 Representation of absent optional fields

This resolves how REQ-RT-080 combines with encoding: whether an absent
(non-defaulted) optional field's key is written at all. It does not
apply to required fields or to defaulted fields (REQ-GEN-170,
REQ-RT-190), which are always written regardless of value.

- **REQ-RT-320** WHEN encoding a struct whose optional, non-defaulted
  field is absent (`None`/`std::nullopt`/unset), the runtime library
  SHALL omit that field's key from the encoded map entirely, rather
  than writing it with an explicit null value.
- **REQ-RT-330** A field's presence (governed by `?`) and a field's
  value-level nullability (governed by a choice type that includes
  `null`, e.g. `? field: T / null`) SHALL remain independently
  representable: an absent field omits the key (REQ-RT-320); a present
  field whose value is the `null` alternative of a choice type writes
  the key with an explicit null value. The system SHALL NOT conflate
  these by using an explicit null to mean "absent."
- **REQ-RT-340** WHEN a struct's encoded form requires its map length to
  be declared before its entries (the definite-length requirement of
  REQ-RT-160), the runtime library SHALL compute that length from the
  fields actually present rather than the number of fields declared in
  the schema, or SHALL use an equivalent single-pass buffering strategy
  that yields the same result.
- **REQ-RT-350** IF a decoder encounters an explicit null value for a
  field declared as a non-nullable optional type (`? field: T`, where
  `T` does not itself admit `null`), THEN the runtime library SHALL
  raise a decode error identifying the field, per REQ-RT-060/070's
  existing type-mismatch handling, rather than silently treating the
  null as equivalent to the field being absent.

### 9.8 Choice and enumeration encoding

CDDL's `A / B / C` is untagged in the abstract, but untagged decoding is
ambiguous whenever two alternatives can match the same input (e.g. two
struct types with overlapping optional fields). Lido therefore encodes
choices explicitly, so that decoding is unambiguous and REQ-RT-060's
"unknown choice discriminant" error has a concrete meaning.

- **REQ-RT-360** WHEN encoding a value of a choice type, the runtime
  library SHALL encode it as a map containing exactly one entry, whose
  key is the selected variant's discriminant and whose value is that
  variant's encoded value.
- **REQ-RT-370** The system SHALL assign each variant of a choice type a
  discriminant derived from the schema — the alternative's type name for
  named alternatives — recorded in the IR and compiled into the
  generated codec, following the same text-or-integer key rules and
  key-stability guarantee as struct fields (§3.1, REQ-KEY-050).
- **REQ-RT-380** IF a decoder encounters a choice-typed value whose map
  does not contain exactly one entry, or whose single key is not a
  discriminant known to the schema, THEN the runtime library SHALL raise
  a decode error identifying the field and the offending discriminant.
  Unknown discriminants SHALL NOT be skipped in the manner of
  REQ-COMPAT-020, because a choice value with no recognized variant has
  no representable value, unlike an unrecognized struct field.
- **REQ-RT-385** WHEN encoding a value of an enumeration type (an
  enumeration of literal values per §3), the runtime library SHALL
  encode the literal value itself — not a wrapper map and not an
  ordinal index — so that enumerations remain readable in JSON and
  independent of variant declaration order.

## 10. Command-line interface requirements

- **REQ-CLI-010** The system SHALL provide a standalone CLI executable
  that performs schema compilation without requiring any build-system
  integration.
- **REQ-CLI-020** WHEN invoked, the CLI SHALL accept one or more CDDL
  input file paths or a directory, which the CLI SHALL search
  recursively for `.cddl` files. All inputs of a single invocation form
  one compilation unit (§4).
- **REQ-CLI-030** WHEN invoked, the CLI SHALL accept a target language
  selector choosing one or more of `cpp`, `java`, `rust`.
- **REQ-CLI-040** WHEN invoked, the CLI SHALL accept an output directory
  path under which generated files are written.
- **REQ-CLI-050** WHERE a namespace/package/module name is relevant to the
  selected target language(s), the CLI SHALL accept it as an option.
- **REQ-CLI-055** WHEN more than one target language is selected in a
  single invocation, the CLI SHALL accept namespace/package/module names
  per target language (e.g. `--java-package`, `--cpp-namespace`,
  `--rust-module`) rather than applying one value across languages
  whose naming conventions differ.
- **REQ-CLI-057** The CLI SHALL write each selected language's output
  into its own subdirectory of the output directory, named for that
  language, regardless of how many languages are selected, so that
  output layout does not change shape between single-target and
  multi-target invocations. WHERE a target language requires a specific
  on-disk layout below that point (notably Java, whose directory
  structure must mirror the package name), the generated files SHALL
  conform to it.
- **REQ-CLI-058** The CLI SHALL accept an opt-in, non-default flag
  requesting native-ecosystem serialization bindings on generated DTOs
  (REQ-GEN-200), selectable per target language.
- **REQ-CLI-060** IF compilation fails for any reason (parse, validation,
  or generation error), THEN the CLI SHALL exit with a non-zero status
  code and SHALL print all collected errors to standard error.
- **REQ-CLI-063** WHEN reporting a parse or validation error, the CLI
  SHALL render the offending source line with an indicator of the
  error's column span, in addition to the file/line/column required by
  REQ-CDDL-050/060, so that diagnostics are actionable without opening
  the schema in a separate editor.
- **REQ-CLI-065** IF generation fails for any selected target language,
  THEN the CLI SHALL leave the output directory in its prior state,
  writing either all generated files or none, so that a failed run
  cannot leave a partially regenerated source tree that a build system
  would then compile.
- **REQ-CLI-070** WHEN compilation succeeds, the CLI SHALL exit with a
  zero status code and SHALL print a summary of generated files to
  standard output.
- **REQ-CLI-080** The CLI SHALL support a `--dry-run` (or equivalent) mode
  that performs parsing and validation without writing output files.
- **REQ-CLI-090** The CLI SHALL be usable identically on Linux, macOS, and
  Windows.
- **REQ-CLI-100** The CLI SHALL provide an `inspect` subcommand that
  decodes a CBOR or JSON payload against a schema and prints it in a
  human-readable form, resolving wire keys back to their schema field
  names. This matters disproportionately for integer-keyed schemas
  (§3.1), whose payloads (`{"1": "abc", "2": 42}`) are otherwise
  unreadable during debugging.
- **REQ-CLI-110** IF `inspect` is given a payload that fails to decode,
  THEN the CLI SHALL report the failure using the path, expected/found,
  and offset information required by REQ-RT-065, and SHALL print the
  portion of the payload decoded successfully before the failure point.

## 11. Extensibility requirements (adding a target language)

- **REQ-EXT-010** The system SHALL define a documented backend interface
  (inputs: IR + generation options; output: generated source files, with
  wire metadata embedded per REQ-GEN-030) that a new language backend must
  implement, without requiring changes to the CDDL parser, validator, or
  IR.
- **REQ-EXT-020** The system SHALL define a documented runtime-library
  contract (§9) that a new language's runtime library must satisfy.
- **REQ-EXT-030** The system SHALL validate a new backend against the
  shared conformance test suite (REQ-ARCH-060) before it is considered
  supported.
- **REQ-EXT-040** *(Deferred — not a v1 requirement.)* A mechanism for a
  backend to declare partial support for the core CDDL subset, so the CLI
  can reject unsupported-feature use rather than mis-generate code. This
  is deferred because REQ-GEN-120 requires every v1 backend to support the
  entire core subset, making the mechanism unreachable in v1; it SHALL be
  specified and implemented when a backend that cannot meet REQ-GEN-120 is
  first proposed. Until then, a backend that cannot support the full
  subset is not a supported backend.

## 12. Non-functional requirements

- **REQ-NFR-010** The system SHALL compile a schema of at most 200 defined
  types to all three initial target languages in under 5 seconds, measured
  as wall-clock time for a single CLI invocation on the project's
  reference CI runner configuration (recorded in the repository so the
  figure is reproducible rather than judged subjectively).
- **REQ-NFR-020** The system's generated DTOs SHALL have no runtime
  dependency beyond the corresponding runtime library and that runtime
  library's own declared dependencies (REQ-RT-100).
- **REQ-NFR-030** The system SHALL target these language baselines unless
  overridden: C++17, Java 17, and Rust 2021 edition. Baselines are pinned
  to specific versions rather than tracking "current stable" so that
  generated code's compatibility surface does not drift silently.
- **REQ-NFR-040** The system's own implementation language is defined in
  §13; its distribution channels are defined in §15.
- **REQ-NFR-050** The system SHALL provide automated tests covering the
  parser, validator, IR, each backend's generated code, and each runtime
  library's encode/decode behavior against the shared conformance suite
  (REQ-ARCH-060).

### 12.1 Runtime performance

Programmer productivity is the project's primary goal; runtime
performance is a supporting goal, pursued where it does not compromise
the generated API's usability. The purpose of this section is to make
performance *measured and non-regressing*, not to commit to an absolute
figure before any data exists.

- **REQ-PERF-010** The system SHALL provide an encode/decode benchmark
  suite covering CBOR and JSON in all three target languages, exercising
  representative payload shapes (small flat structs, wide structs, deeply
  nested structures, large collections, and byte-string-heavy payloads).
- **REQ-PERF-020** The benchmark suite SHALL include comparisons against
  the serialization library each target language's users would otherwise
  reach for (e.g. `serde` with a CBOR/JSON backend in Rust, Jackson in
  Java, `nlohmann/json` in C++), and the results SHALL be published in
  user documentation, so that adoption questions about performance can
  be answered with measurements rather than assertions.
- **REQ-PERF-030** CI SHALL track benchmark results against a recorded
  baseline and SHALL fail on a regression beyond an agreed threshold, so
  that performance is defended continuously rather than audited
  occasionally.
- **REQ-PERF-040** The steady-state encode path SHALL NOT allocate when
  a caller-supplied reusable buffer is used (REQ-RT-098), and the decode
  path SHALL NOT allocate per field beyond the allocations inherent in
  the decoded values themselves.
- **REQ-PERF-050** Tracking which fields have been seen during decode —
  required for duplicate detection (REQ-RT-300) and missing-required
  detection (REQ-RT-060) — SHALL use a fixed-size bit set sized at
  generation time from the struct's field count, not a dynamically
  allocated set or map keyed by field name.

### 12.2 Performance non-goals

Recorded explicitly so they are not reintroduced as optimizations later.
Each trades against the project's primary goal.

- **REQ-PERF-060** The system SHALL NOT generate DTOs that borrow from
  the input buffer (zero-copy string/byte-string fields). Zero-copy
  decoding is measurably faster but would introduce lifetime parameters
  into every generated Rust type and dangling-reference hazards in C++,
  degrading exactly the API usability this project prioritizes.
- **REQ-PERF-070** The runtime libraries SHALL NOT use `unsafe` Rust,
  hand-written SIMD, or hand-rolled floating-point formatting/parsing in
  v1; such work belongs in the underlying primitive libraries
  (REQ-RT-100), where it is shared and independently audited.
- **REQ-PERF-080** The system SHALL NOT introduce arena or custom
  allocator infrastructure beyond the caller-supplied buffer support
  already required by REQ-RT-098/150.

## 13. Implementation language

- **REQ-IMPL-010** Lido itself (the CLI, CDDL parser, validator, IR, and
  all v1 code generation backends) SHALL be implemented in Rust.

Rationale: Rust's algebraic data types and exhaustive pattern matching are
well suited to representing a CDDL AST/IR and to writing per-backend code
generators that match over IR node kinds. Its toolchain produces small,
statically linked, cross-compilable binaries, so the CLI can be handed to
C++, Java, or embedded developers without requiring them to install a
Python interpreter or a JVM. It also shares tooling and ecosystem with the
Rust target backend and runtime library. Alternatives considered and set
aside: Go's weaker sum-type/pattern-matching ergonomics make AST/IR
modeling less natural than Rust's enums; C++ would slow development and
reintroduce memory-safety risk into the compiler itself; a JVM language
(Kotlin/Java) would require every CLI user — including C++/embedded shops
with no JVM installed — to have a JVM just to run the tool; Python
requires a runtime and dependency environment that is friction for a
build-time tool meant to drop into arbitrary pipelines.

## 14. Licensing and third-party dependency requirements

- **REQ-DEP-010** The project SHALL be licensed under the MIT license.
- **REQ-DEP-020** Every third-party dependency used by the compiler or by
  a runtime library SHALL carry an OSI-approved permissive license (e.g.
  MIT, Apache-2.0, BSD-2-Clause, BSD-3-Clause, Boost Software License
  1.0) compatible with MIT redistribution. The system SHALL NOT depend on
  copyleft-licensed code (e.g. GPL, LGPL, AGPL).
- **REQ-DEP-030** Runtime library dependencies SHALL be chosen for
  suitability in embedded/resource-constrained environments: a minimal
  transitive dependency count and, where the target language's ecosystem
  supports it, a `no_std` or no-mandatory-dynamic-allocation build
  configuration.
- **REQ-DEP-040** IF a chosen runtime library dependency does not support
  a constrained/embedded configuration for a given target language, THEN
  the system SHALL document that limitation rather than leave it
  implicit.

### 14.1 Candidate primitive libraries (informative)

Candidates identified against REQ-DEP-020/030, REQ-RT-100, and the
FreeRTOS-motivated constraints in §9.5. Final selection is an
implementation-phase decision, may change after prototyping, and is not
itself a requirement.

| Language | CBOR | JSON | License(s) | Notes |
|---|---|---|---|---|
| Rust | `minicbor` | `serde_json` (alloc-only feature set) | MIT/Apache-2.0 | `minicbor` is purpose-built for `no_std`/embedded use and already satisfies REQ-RT-110. `serde_json` needs at least `alloc`, which is available on FreeRTOS via a `#[global_allocator]` bound to `pvPortMalloc`/`vPortFree` (a standard embedded-Rust pattern) — no need to force pure no-alloc for v1. `serde-json-core` (no-alloc, fixed buffers) remains a fallback for targets that can't or won't provide an allocator. |
| Java | `jackson-dataformat-cbor` | `jackson-databind` | Apache-2.0 | One library family for both formats simplifies REQ-RT-050 (matching CBOR/JSON semantics). Not evaluated against §9.5 — a JVM is not a realistic FreeRTOS target. |
| C++ | `tinycbor` | `nlohmann/json` (built with `JSON_NOEXCEPTION`) | MIT | `tinycbor` is a strong fit as-is: pure C, no exceptions, proven on embedded/IoT, supports no-dynamic-allocation use. `nlohmann/json` normally throws on error; its `JSON_NOEXCEPTION` build mode is required to satisfy REQ-RT-120. `ArduinoJson` (MIT) is a stronger long-term fit for FreeRTOS specifically — no exceptions, no RTTI, no mandatory heap (fixed-capacity or caller-supplied-arena `JsonDocument`), and widely deployed on RTOS/microcontroller targets — and is the preferred candidate to re-evaluate against once FreeRTOS support is actually undertaken, at the cost of a less conventional DOM API than `nlohmann/json`. |

## 15. Distribution requirements

- **REQ-DIST-010** The Rust CLI and the Rust runtime library SHALL be
  published as crates on crates.io.
- **REQ-DIST-020** The system SHALL publish prebuilt CLI binaries for
  Linux, macOS, and Windows (x86_64 and aarch64 where feasible) as
  release artifacts, so consumers without a Rust toolchain can install
  the CLI.
- **REQ-DIST-030** The Java runtime library SHALL be published to Maven
  Central.
- **REQ-DIST-040** The C++ runtime library SHALL be distributed as a
  source archive (tarball/zip) attached to tagged releases, containing
  headers (and any minimal accompanying source) plus a CMake package
  configuration that supports both `find_package` and `FetchContent`
  consumption.
- **REQ-DIST-050** WHERE the C++ runtime library's API has stabilized
  post-v1, the project MAY additionally register vcpkg and/or Conan
  packages. This is explicitly deferred and not required for v1: many
  embedded C++ toolchains vendor sources directly rather than using a
  package manager, and maintaining registry ports for a pre-1.0 API adds
  churn without corresponding benefit yet.

## 16. Open questions

1. Concrete artifact naming: crates.io crate name(s) for the CLI vs. the
   Rust runtime library, Maven `groupId`/`artifactId` for the Java
   runtime library, and the C++ library's namespace/include-path
   convention.
2. Final pin of the underlying CBOR/JSON primitive library per language
   from the shortlist in §14.1, informed by prototyping against at least
   one real embedded target per language where applicable (Rust, C++).
3. Whether/when build-system plugin integration (Maven/Gradle/Cargo
   `build.rs`/CMake) becomes in-scope, deferred from v1 per §2.2.
4. Whether/when FreeRTOS (or another RTOS) becomes an explicit supported
   target (§9.5, §2.2), and which allocation model to target first —
   `alloc` backed by a FreeRTOS heap implementation vs. a strictly
   no-alloc/static-buffer design.
5. Default values for the configurable decode limits in §9.4 (max
   nesting depth, max string/collection size) — these need to be
   permissive enough for realistic payloads yet tight enough to be
   useful on constrained targets.
6. Whether `uint` should map to Java's `long` with documented unsigned
   semantics (current §8.1 choice) or to a boxed unsigned wrapper; the
   current mapping cannot represent values above 2^63−1.
