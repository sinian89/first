#include <cmath>
#include <deque>
#include <iostream>
#include <memory>
#include <mutex>
#include <string>
#include <string_view>
#include <thread>
#include <unordered_map>
#include <utility>
#include <variant>

struct Context {
    std::unordered_map<std::string, double> vars;
};

struct Node;
using NodePtr = std::unique_ptr<Node>;

struct Var {
    std::string_view name;
};

struct Const {
    double value;
};

struct Add;
struct Mul;
struct Sin;

struct Add {
    NodePtr left;
    NodePtr right;
};

struct Mul {
    NodePtr left;
    NodePtr right;
};

struct Sin {
    NodePtr arg;
};

struct Node {
    std::variant<Var, Const, Add, Mul, Sin> data;

    template <class T>
    Node(T v) : data(std::move(v)) {}
};

double eval(const Node& n, const Context& ctx);

double eval_var(const Var& v, const Context& ctx) {
    auto it = ctx.vars.find(std::string(v.name));
    if (it == ctx.vars.end()) return 0.0;
    return it->second;
}

double eval(const Node& n, const Context& ctx) {
    return std::visit([&](const auto& x) -> double {
        using T = std::decay_t<decltype(x)>;
        if constexpr (std::is_same_v<T, Var>) {
            return eval_var(x, ctx);
        } else if constexpr (std::is_same_v<T, Const>) {
            return x.value;
        } else if constexpr (std::is_same_v<T, Add>) {
            return eval(*x.left, ctx) + eval(*x.right, ctx);
        } else if constexpr (std::is_same_v<T, Mul>) {
            return eval(*x.left, ctx) * eval(*x.right, ctx);
        } else {
            return std::sin(eval(*x.arg, ctx));
        }
    }, n.data);
}

NodePtr make_var(std::string_view name) {
    return std::make_unique<Node>(Var{name});
}

NodePtr make_const(double v) {
    return std::make_unique<Node>(Const{v});
}

NodePtr make_add(NodePtr a, NodePtr b) {
    return std::make_unique<Node>(Add{std::move(a), std::move(b)});
}

NodePtr make_mul(NodePtr a, NodePtr b) {
    return std::make_unique<Node>(Mul{std::move(a), std::move(b)});
}

NodePtr make_sin(NodePtr a) {
    return std::make_unique<Node>(Sin{std::move(a)});
}

class InternTable {
    mutable std::mutex mu_;
    // References to deque elements stay valid when we push_back (unlike vector reallocation).
    std::deque<std::string> pool_;

    struct StringHash {
        using is_transparent = void;
        std::size_t operator()(std::string_view sv) const noexcept {
            return std::hash<std::string_view>{}(sv);
        }
    };
    struct StringEq {
        using is_transparent = void;
        bool operator()(std::string_view a, std::string_view b) const noexcept {
            return a == b;
        }
    };
    std::unordered_map<std::string_view, std::string_view, StringHash, StringEq> by_name_;

public:
    std::string_view intern(std::string s) {
        std::lock_guard<std::mutex> lock(mu_);
        const std::string_view probe(s);
        if (auto it = by_name_.find(probe); it != by_name_.end()) {
            return it->second;
        }
        pool_.push_back(std::move(s));
        std::string_view stable(pool_.back());
        by_name_.emplace(stable, stable);
        return stable;
    }
};

InternTable g_intern;

NodePtr var(std::string name) {
    return make_var(g_intern.intern(std::move(name)));
}

// int main() {
//     Context ctx;
//     ctx.vars["x"] = 3.0;
//     ctx.vars["y"] = 4.0;

//     auto expr = make_add(
//         make_mul(var("x"), var("x")),
//         make_sin(var("y"))
//     );

//     std::vector<std::thread> threads;
//     for (int i = 0; i < 8; ++i) {
//         threads.emplace_back([&]() {
//             for (int j = 0; j < 10000; ++j) {
//                 auto e = make_add(
//                     make_mul(var("x"), var("x")),
//                     make_sin(var("y"))
//                 );
//                 double v = eval(*e, ctx);
//                 if (v < 8.0 || v > 10.0) {
//                     std::cout << "bad: " << v << "\n";
//                 }
//             }
//         });
//     }

//     for (auto& t : threads) t.join();

//     std::cout << eval(*expr, ctx) << "\n";
// }