#include<iostream>
#include<thread>
#include<vector>
#include<string>
#include<memory>
#include<atomic>
#include<mutex>
#include<condition_variable>
#include<chrono>
#include<functional>
#include<cmath>

#include "../solution/solution-1.cpp"

void test_dangling_string_view() {
    std::cout << "[test] dangling_string_view: start\n";
    Context ctx;
    ctx.vars["x"] = 10.0;

    for (int i = 0; i < 100000; ++i) {
        auto e = make_mul(var("x"), var("x"));
        double v = eval(*e, ctx);

        if (v != 100.0) {
            std::cout << "FAIL (dangling): " << v << "\n";
            return;
        }
    }
    std::cout << "[test] dangling_string_view: pass\n";
}

void test_concurrent_intern() {
    std::cout << "[test] concurrent_intern: start (16 threads x 50000 iters)\n";
    Context ctx;
    ctx.vars["x"] = 3.0;
    ctx.vars["y"] = 4.0;

    std::vector<std::thread> threads;

    for (int t = 0; t < 16; ++t) {
        threads.emplace_back([&]() {
            for (int i = 0; i < 50000; ++i) {
                auto e = make_add(
                    make_mul(var("x"), var("x")),
                    make_sin(var("y"))
                );

                double v = eval(*e, ctx);

                if (v < 8.0 || v > 10.0) {
                    std::cout << "FAIL (race): " << v << "\n";
                }
            }
        });
    }

    for (auto& t : threads) t.join();
    std::cout << "[test] concurrent_intern: join complete\n";
}

struct UniqueConst {
    std::unique_ptr<double> value;

    UniqueConst(double v) : value(std::make_unique<double>(v)) {}

    UniqueConst(const UniqueConst&) = delete;
    UniqueConst(UniqueConst&&) = default;

    double eval() const { return *value; }
};

void test_move_only() {
    std::cout << "[test] move_only: start\n";
    auto a = std::make_unique<Node>(Const{5.0});
    auto b = std::make_unique<Node>(Const{3.0});

    auto expr = make_add(std::move(a), std::move(b));
    std::cout << "[test] move_only: pass\n";
}

void test_symbol_identity() {
    std::cout << "[test] symbol_identity: start\n";
    auto v1 = var("x");
    auto v2 = var("x");

    Context ctx;
    ctx.vars["x"] = 5.0;

    double a = eval(*v1, ctx);
    double b = eval(*v2, ctx);

    if (a != b) {
        std::cout << "FAIL (symbol mismatch)\n";
    } else {
        std::cout << "[test] symbol_identity: pass (a=b=" << a << ")\n";
    }
}

NodePtr build_deep(int depth) {
    if (depth == 0) return make_const(1.0);
    return make_add(build_deep(depth - 1), make_const(1.0));
}

void test_deep_tree() {
    std::cout << "[test] deep_tree: building depth 10000\n";
    auto expr = build_deep(10000);

    Context ctx;
    double v = eval(*expr, ctx);

    std::cout << "[test] deep_tree: result " << v << "\n";
}

void test_aliasing() {
    std::cout << "[test] aliasing: start\n";
    auto x = var("x");

    auto expr = make_add(
        make_mul(std::move(x), var("x")),
        make_mul(var("x"), var("x"))
    );

    Context ctx;
    ctx.vars["x"] = 2.0;

    std::cout << "[test] aliasing: eval -> " << eval(*expr, ctx) << "\n";
}

void test_intern_stress() {
    std::cout << "[test] intern_stress: 200000 unique symbol names\n";
    for (int i = 0; i < 200000; ++i) {
        var("var_" + std::to_string(i));
    }

    std::cout << "[test] intern_stress: done\n";
}

void test_precision() {
    std::cout << "[test] precision: x=1e-8, expect x*x > 0\n";
    Context ctx;
    ctx.vars["x"] = 1e-8;

    auto expr = make_mul(var("x"), var("x"));

    double v = eval(*expr, ctx);

    if (v <= 0.0) {
        std::cout << "FAIL (precision)\n";
    } else {
        std::cout << "[test] precision: pass (v=" << v << ")\n";
    }
}

void test_missing_var() {
    std::cout << "[test] missing_var: expect 0 for unknown symbol\n";
    Context ctx;

    auto expr = var("unknown");

    double v = eval(*expr, ctx);

    if (v != 0.0) {
        std::cout << "FAIL (missing var)\n";
    } else {
        std::cout << "[test] missing_var: pass\n";
    }
}

void test_combined() {
    std::cout << "[test] combined: start (8 threads x 10000 iters)\n";
    Context ctx;
    ctx.vars["x"] = 3.0;
    ctx.vars["y"] = 4.0;

    std::vector<std::thread> threads;

    for (int t = 0; t < 8; ++t) {
        threads.emplace_back([&]() {
            for (int i = 0; i < 10000; ++i) {
                auto expr = make_add(
                    make_mul(var("x"), var("x")),
                    make_sin(var("y"))
                );

                double v = eval(*expr, ctx);

                if (v < 8.0 || v > 10.0) {
                    std::cout << "FAIL (combined): " << v << "\n";
                }
            }
        });
    }

    for (auto& t : threads) t.join();
    std::cout << "[test] combined: join complete\n";
}