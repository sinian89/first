You will implement a C++20 symbolic expression engine.

=== REQUIRED CODE STRUCTURE ===

Your code must compile as a single translation unit and must define the following types and functions exactly in a single file named solution.cpp:

Types:
- struct Context
- struct Node
- using NodePtr = std::unique_ptr<Node>

Required API:
- NodePtr var(std::string name);
- NodePtr make_const(double value);
- NodePtr make_add(NodePtr a, NodePtr b);
- NodePtr make_mul(NodePtr a, NodePtr b);
- NodePtr make_sin(NodePtr a);

Evaluation:
- double eval(const Node& node, const Context& ctx);

General requirements:
- Code must compile with C++20.
- Use only C++ standard library.
- Do not include a main() function.
- All functionality must be implemented within the provided interfaces.
- Results must be consistent across repeated executions.
- Expressions must evaluate to correct numeric results.

Provide a correct implementation.
And your current path is /app/ in docker. You can create solution.cpp file here.