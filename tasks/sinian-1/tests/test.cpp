#include <atomic>
#include <cmath>
#include <cstdlib>
#include <iostream>
#include <memory>
#include <string>
#include <thread>
#include <vector>

[[noreturn]] static void test_fail(const char* msg) {
    std::cerr << "FAIL: " << msg << '\n';
    std::exit(1);
}

static void test_expect(bool ok, const char* msg) {
    if (!ok) {
        test_fail(msg);
    }
}

void test_dangling_string_view() {
    std::cout << "[test] dangling_string_view: start\n";
    Context ctx;
    ctx.vars["x"] = 10.0;

    for (int i = 0; i < 100000; ++i) {
        auto e = make_mul(var("x"), var("x"));
        double v = eval(*e, ctx);
        if (v != 100.0) {
            test_fail("dangling_string_view: expected 100.0");
        }
    }
    std::cout << "[test] dangling_string_view: pass\n";
}

void test_concurrent_intern() {
    std::cout << "[test] concurrent_intern: start (16 threads x 50000 iters)\n";
    Context ctx;
    ctx.vars["x"] = 3.0;
    ctx.vars["y"] = 4.0;

    std::atomic<bool> bad{false};
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
                    bad.store(true, std::memory_order_relaxed);
                }
            }
        });
    }

    for (auto& t : threads) {
        t.join();
    }
    test_expect(!bad.load(), "concurrent_intern: eval out of expected range [8,10]");
    std::cout << "[test] concurrent_intern: pass\n";
}

void test_move_only() {
    std::cout << "[test] move_only: start\n";
    auto expr = make_add(make_const(5.0), make_const(3.0));
    Context ctx;
    double v = eval(*expr, ctx);
    test_expect(v == 8.0, "move_only: expected 5+3=8");
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

    test_expect(a == b, "symbol_identity: two var(\"x\") must agree");
    std::cout << "[test] symbol_identity: pass (a=b=" << a << ")\n";
}

NodePtr build_deep(int depth) {
    if (depth == 0) {
        return make_const(1.0);
    }
    return make_add(build_deep(depth - 1), make_const(1.0));
}

void test_deep_tree() {
    std::cout << "[test] deep_tree: building depth 10000\n";
    auto expr = build_deep(10000);

    Context ctx;
    double v = eval(*expr, ctx);

    test_expect(v == 10001.0, "deep_tree: expected 10001");
    std::cout << "[test] deep_tree: pass (v=" << v << ")\n";
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

    double v = eval(*expr, ctx);
    test_expect(v == 8.0, "aliasing: expected 2*2+2*2=8");
    std::cout << "[test] aliasing: pass\n";
}

void test_intern_stress() {
    std::cout << "[test] intern_stress: 200000 unique symbol names\n";
    for (int i = 0; i < 200000; ++i) {
        var("var_" + std::to_string(i));
    }

    Context ctx;
    ctx.vars["var_42"] = 7.0;
    ctx.vars["var_199999"] = -1.5;

    auto e1 = var("var_42");
    auto e2 = var("var_199999");
    test_expect(eval(*e1, ctx) == 7.0, "intern_stress: lookup var_42 after mass intern");
    test_expect(eval(*e2, ctx) == -1.5, "intern_stress: lookup var_199999 after mass intern");

    std::cout << "[test] intern_stress: pass\n";
}

void test_precision() {
    std::cout << "[test] precision: x=1e-8, expect x*x > 0\n";
    Context ctx;
    ctx.vars["x"] = 1e-8;

    auto expr = make_mul(var("x"), var("x"));

    double v = eval(*expr, ctx);

    test_expect(v > 0.0, "precision: x*x must be > 0 for x=1e-8");
    std::cout << "[test] precision: pass (v=" << v << ")\n";
}

void test_missing_var() {
    std::cout << "[test] missing_var: expect 0 for unknown symbol\n";
    Context ctx;

    auto expr = var("unknown");

    double v = eval(*expr, ctx);

    test_expect(v == 0.0, "missing_var: unknown symbol must evaluate to 0.0");
    std::cout << "[test] missing_var: pass\n";
}

void test_combined() {
    std::cout << "[test] combined: start (8 threads x 10000 iters)\n";
    Context ctx;
    ctx.vars["x"] = 3.0;
    ctx.vars["y"] = 4.0;

    std::atomic<bool> bad{false};
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
                    bad.store(true, std::memory_order_relaxed);
                }
            }
        });
    }

    for (auto& t : threads) {
        t.join();
    }
    test_expect(!bad.load(), "combined: eval out of expected range [8,10]");
    std::cout << "[test] combined: pass\n";
}
