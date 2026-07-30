# Lido — Generated Code Style Guide

Status: Draft v0.1

## Purpose

This document defines the API style Lido's code generators follow when
emitting DTOs for each target language. It complements `doc/specs.md`,
which defines *what* Lido must do (EARS-format functional requirements);
this document defines *how the generated code should look and feel* to a
consumer. Where the two overlap, `specs.md` requirements (e.g.
REQ-GEN-020's "language-idiomatic accessors/constructors") take
precedence, and this document elaborates what "idiomatic" means per
language.

Scope note: this covers the style of Lido's **generated output** only,
not the style of Lido's own Rust implementation. A separate document
could cover the latter if wanted.

## General principles

- Generated DTOs are value types: prefer immutability after
  construction. There are no in-place setters on a fully constructed
  instance.
- Generated codecs construct DTOs through a crate/package-private path,
  not the public builder. Decoding reads fields in whatever order the
  input presents them and can only know all required fields are present
  once the map ends, so it cannot use a builder whose required fields
  are constructor parameters. The public API optimizes for the user;
  the decode path is an internal detail.
- Prefer each target language's own conventions over cross-language
  surface consistency. A Java DTO should look like idiomatic Java; a
  Rust DTO should look like idiomatic Rust. Consistency of *behavior and
  wire format* across languages matters (specs.md); surface-API shape
  does not need to match.
- **A schema change that is wire-compatible must not be source-breaking
  where that is avoidable.** Adding an optional field is safe on the
  wire (§9.6 of specs.md); it should not silently reshape the
  construction API and break every call site. This rules out
  heuristics that switch API style based on a type's size or field
  count.
- Required fields are constructor/builder-factory *parameters*; only
  optional and defaulted fields are set fluently. Forgetting a required
  field is then a compile error rather than a runtime failure.

## Encoding and decoding: the user-facing API

DTOs contain no encoding logic (REQ-GEN-020), so encode/decode is
reached through free functions in the runtime library rather than
methods on the DTO. This is the first API any user touches, so it is
one line in every language:

```rust
let bytes  = lido::to_cbor(&person)?;
let person = lido::from_cbor::<Person>(&bytes)?;
let text   = lido::to_json(&person)?;
```

```java
byte[] bytes  = LidoCbor.encode(person);
Person person = LidoCbor.decode(Person.CODEC, bytes);
String text   = LidoJson.encode(person);
```

```cpp
auto bytes  = lido::to_cbor(person);      // result<std::vector<uint8_t>>
auto person = lido::from_cbor<Person>(b); // result<Person>
```

The generated per-type codec (`Person::CODEC` and equivalents) is public
so advanced callers can configure decode limits or reuse a codec, but
the free functions cover the common case with defaults.

## Documentation comments

CDDL comments carry through to generated doc comments (REQ-GEN-180), so
schema intent reaches the IDE:

```cddl
; A registered user of the system.
Person = {
  ; Display name, shown in the UI.
  name: tstr,
}
```

becomes `///` in Rust, `/** … */` Javadoc in Java, and `///` Doxygen in
C++. A comment immediately preceding a type or field definition
documents it; the schema file's leading comment block documents the
generated module/package.

## C++

Generated DTOs use a **fluent builder** for construction and plain
`const`-qualified accessors for reading:

```cpp
class Person {
 public:
  class Builder {
   public:
    // Required fields (name, age) are constructor parameters.
    Builder(std::string name, std::uint64_t age);
    // Only optional/defaulted fields are fluent.
    Builder& email(std::optional<std::string> email) &;
    Person build() &&;
   private:
    ...
  };

  static Builder builder(std::string name, std::uint64_t age);

  const std::string& name() const;
  std::uint64_t age() const;
  const std::optional<std::string>& email() const;

  // Member-wise; `= default` is C++20 and the baseline is C++17
  // (specs.md REQ-NFR-030), so both operators are generated explicitly.
  bool operator==(const Person&) const;
  bool operator!=(const Person&) const;

 private:
  explicit Person(...);  // only constructible via Builder
  ...
};

Person p = Person::builder("Alice", 30).email("a@example.com").build();
```

- Required fields are `builder()` parameters, so omitting one fails to
  compile. Only optional and defaulted fields are fluent setters — a
  builder for a type with no optional fields is therefore just
  `Person::builder(...).build()`.
- Fluent setters are named after the field (no `set` prefix) and
  return `Builder&`, so calls chain: `.email(...).nickname(...)`.
- Accessors on the constructed DTO are also named after the field, no
  `get` prefix (`p.name()`, not `p.getName()`) — modern C++ convention
  (cf. `std::optional::value()`) — and return `const&` for non-trivial
  types to avoid copies.
- `Person` has no public constructor other than via `Builder` and no
  setters, so instances are immutable after `build()`.
- `operator==`/`operator!=` are generated member-wise, satisfying
  REQ-GEN-020's equality requirement. Defaulted comparison
  (`= default`, and compiler-synthesized `!=`) is C++20 and so is not
  used at the C++17 baseline.
- Concrete field types follow the normative mapping table in specs.md
  §8.1 — `std::optional<T>` for optionals, `std::vector<T>` for
  sequences, `std::map<K, V>` for tables, `std::variant<...>` for
  choices.
- Exact move-semantics qualification of builder setters (value- vs.
  rvalue-qualified) is a C++ backend implementation detail, not fixed
  by this style guide, and must stay compatible with the non-throwing
  API path required by REQ-RT-120.

## Java

Generated DTOs are **`record`** types (Java 17 baseline, per
REQ-NFR-030) — the idiomatic modern representation of an immutable data
carrier — paired with a fluent **`Builder`**:

```java
public record Person(String name, long age, Optional<String> email) {

  /** Required fields are builder() parameters; optionals are fluent. */
  public static Builder builder(String name, long age) {
    return new Builder(name, age);
  }

  public static final class Builder {
    Builder(String name, long age) { ... }
    public Builder email(Optional<String> email) { ...; return this; }
    public Person build() { return new Person(...); }
  }
}

Person p = Person.builder("Alice", 30).email(Optional.of("a@x.com")).build();
```

- Required fields are `builder()` parameters, so omitting one fails to
  compile rather than throwing at `build()`. Only optional and
  defaulted fields are fluent setters.
- Fluent setters are named after the field (no `set` prefix) and
  return `Builder`, chaining.
- Accessors come for free from `record` (`p.name()`, `p.age()`), named
  after the field with no `get` prefix — already what REQ-GEN-020 calls
  for.
- `equals`/`hashCode`/`toString` come for free from `record`, except for
  DTOs containing a `bstr`-derived `byte[]` field, where the record's
  generated equality would be identity-based; those get explicit
  value-based `equals`/`hashCode` per REQ-GEN-160.
- Concrete field types follow the normative mapping table in specs.md
  §8.1 — `java.util.Optional<T>` for optionals, an immutable
  `java.util.List<T>` (e.g. via `List.copyOf`) for sequences, an
  immutable `java.util.Map<K, V>` for tables, and a `sealed interface`
  with one `record` implementation per alternative for choices.
- The canonical (record) constructor stays available for tools that
  need it (e.g. reflection-based frameworks), but application code and
  the runtime library's decode path SHOULD use `Builder`.

## Rust

Generated DTOs are **plain structs with public fields** — Rust's own
idiom, rather than a fluent builder:

```rust
#[derive(Debug, Clone, PartialEq, Default)]
pub struct Person {
    pub name: String,
    pub age: u64,
    pub email: Option<String>,
}

let p = Person { name: "Alice".into(), age: 30, ..Default::default() };
```

- Fields are `pub`; there are no generated getters/setters — direct
  field access is idiomatic Rust and matches how hand-written and
  `serde`-derived structs are conventionally written.
- `#[derive(Default)]` is generated whenever every field is optional or
  has a schema default, enabling struct-update syntax
  (`..Default::default()`) as Rust's idiomatic answer to "construct
  with only some fields set" — the same need a fluent builder addresses
  in C++/Java.
- Concrete field types follow the normative mapping table in specs.md
  §8.1 — `Option<T>` for optionals, `Vec<T>` for sequences,
  `BTreeMap<K, V>` for tables, and an `enum` with one variant per
  alternative for choices.
- `#[derive(PartialEq)]` (and `Eq` where every field is `Eq`) covers the
  equality requirement from REQ-GEN-020.
- **No builder is generated for Rust, ever, regardless of field count.**
  An earlier draft made this a per-type judgment call above some
  optional-field threshold; that was removed because crossing the
  threshold — which an additive, wire-compatible schema change can
  cause — would rewrite the construction API and break every call site.
  A predictable API that is occasionally verbose beats one that changes
  shape underneath users.

Note the deliberate asymmetry with C++/Java: those get builders because
they lack struct-update syntax, while Rust's `..Default::default()`
already solves the same problem idiomatically.

## Optional ecosystem interop

An opt-in CLI flag (REQ-CLI-058) adds native-ecosystem serialization
support alongside Lido's own: `#[derive(Serialize, Deserialize)]` for
Rust, Jackson annotations for Java. This exists to lower the cost of
adopting Lido types into a codebase already built on serde or Jackson.

It is **off by default and carries a documented caveat**: encoding a DTO
through serde or Jackson bypasses Lido's codec entirely, so none of the
canonical-encoding (§9.1), constraint-validation (§9.3), or
cross-language byte-identity guarantees apply to that path. Use it for
interop at the edges, not as the primary encode path.

## Open questions

1. Whether a separate style document should cover Lido's own Rust
   implementation (the compiler codebase itself), distinct from the
   generated-code style covered here.
2. C++ builder move-semantics/qualification details — deferred to C++
   backend design.
3. Naming-conversion rules for CDDL identifiers that collide with a
   target language's keywords/casing conventions are normative in
   `specs.md` (REQ-GEN-010/090) and not restated here.
4. Whether a type whose fields are *all* required should generate a
   builder at all, or just a plain constructor — `Person::builder(a, b)
   .build()` is arguably worse than `Person(a, b)`.
