// Submitted implementation: /app/solution.cpp (see instruction.md). test.sh checks it exists before g++.
#include "/app/solution.cpp"

#include <cstdlib>
#include <iostream>

#include "test.cpp"

int main() {
    std::cout << "Running tests (against /app/solution.cpp)...\n";

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
    return 0;
}
