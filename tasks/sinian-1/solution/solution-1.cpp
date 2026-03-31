#include <cmath>
#include <memory>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <utility>

struct Context {
    std::unordered_map<std::string, double> values;
};

struct Node {
    enum class Kind {
        Const,
        Var,
        Add,
        Mul,
        Sin
    };

    Kind kind;
    double value = 0.0;
    std::string name;
    std::unique_ptr<Node> left;
    std::unique_ptr<Node> right;

    explicit Node(double v) : kind(Kind::Const), value(v) {}
    explicit Node(std::string n) : kind(Kind::Var), name(std::move(n)) {}
    Node(Kind k, std::unique_ptr<Node> a) : kind(k), left(std::move(a)) {}
    Node(Kind k, std::unique_ptr<Node> a, std::unique_ptr<Node> b)
        : kind(k), left(std::move(a)), right(std::move(b)) {}
};

using NodePtr = std::unique_ptr<Node>;

NodePtr var(std::string name) {
    return std::make_unique<Node>(std::move(name));
}

NodePtr make_const(double value) {
    return std::make_unique<Node>(value);
}

NodePtr make_add(NodePtr a, NodePtr b) {
    return std::make_unique<Node>(Node::Kind::Add, std::move(a), std::move(b));
}

NodePtr make_mul(NodePtr a, NodePtr b) {
    return std::make_unique<Node>(Node::Kind::Mul, std::move(a), std::move(b));
}

NodePtr make_sin(NodePtr a) {
    return std::make_unique<Node>(Node::Kind::Sin, std::move(a));
}

double eval(const Node& node, const Context& ctx) {
    switch (node.kind) {
        case Node::Kind::Const:
            return node.value;

        case Node::Kind::Var: {
            auto it = ctx.values.find(node.name);
            if (it == ctx.values.end()) {
                throw std::runtime_error("Variable not found in context: " + node.name);
            }
            return it->second;
        }

        case Node::Kind::Add:
            if (!node.left || !node.right) {
                throw std::runtime_error("Invalid Add node");
            }
            return eval(*node.left, ctx) + eval(*node.right, ctx);

        case Node::Kind::Mul:
            if (!node.left || !node.right) {
                throw std::runtime_error("Invalid Mul node");
            }
            return eval(*node.left, ctx) * eval(*node.right, ctx);

        case Node::Kind::Sin:
            if (!node.left) {
                throw std::runtime_error("Invalid Sin node");
            }
            return std::sin(eval(*node.left, ctx));
    }

    throw std::runtime_error("Unknown node kind");
}
