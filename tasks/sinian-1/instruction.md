You will implement a C++20 symbolic expression engine.

Create a **single file** `solution.cpp` under `/app` (Docker working directory). It must be one translation unit, use **only** the C++ standard library, target **C++20**, and **must not** define `main()`.

Define these types and functions with **exactly** these names and signatures:

**Types**

- `struct Context` with a public member `std::unordered_map<std::string, double> vars;` (the verifier supplies values via `ctx.vars[...]`).
- `struct Node`
- `using NodePtr = std::unique_ptr<Node>;`

`Node` must be **movable**. Factories take child expressions as `NodePtr` consumed by move.

**API**

- `NodePtr var(std::string name);`
- `NodePtr make_const(double value);`
- `NodePtr make_add(NodePtr a, NodePtr b);`
- `NodePtr make_mul(NodePtr a, NodePtr b);`
- `NodePtr make_sin(NodePtr a);`
- `double eval(const Node& node, const Context& ctx);`

**Behavior (high level)**

- Build expressions from constants, named variables (`var`), add, multiply, and sine (radian argument, same convention as `std::sin`).
- Arithmetic follows normal IEEE-754 `double` rules where applicable.
- Variable lookup uses `ctx.vars`. Any finer rules are enforced by the verifier.
- `var`, the `make_*` functions, and `eval` must be safe when used from **multiple threads at once**.
- For the same tree and the same `Context`, results must be **deterministic** across runs.

You may define private helper types inside `solution.cpp` as needed.

Provide a correct implementation.
