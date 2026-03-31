#include <cstdlib>
#include <iostream>

#include "test.cpp"

int main() {
    constexpr const char* kPythonPath = "/app";
    if (setenv("PYTHONPATH", kPythonPath, 1) != 0) {
        std::cerr << "setenv PYTHONPATH failed\n";
        return 1;
    }

    std::cout << "Running tests...\n";

    test_dangling_string_view();
    test_concurrent_intern();
    test_move_only();
    test_symbol_identity();
    test_deep_tree();
    test_aliasing();
    test_intern_stress();
    test_precision();
    test_missing_var();
    test_combined();

    std::cout << "Done.\n";
}
