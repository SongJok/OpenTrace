"""Benchmark script for JOIN path heuristic inference accuracy."""

from __future__ import annotations

import asyncio
import time
from kernel.data_cognition.table_graph import TableRelationshipGraph, JoinStep


def _run_sync_benchmark():
    """Run synchronous benchmark for heuristic JOIN matching."""
    graph = TableRelationshipGraph()
    
    # Register test schema with columns
    graph.register_columns("users", ["id", "user_id", "name", "email", "created_at"])
    graph.register_columns("orders", ["id", "order_id", "user_id", "product_id", "amount", "created_at"])
    graph.register_columns("products", ["id", "product_id", "name", "price", "category_id"])
    graph.register_columns("categories", ["id", "category_id", "name", "parent_id"])
    
    # Register only partial FKs (simulating incomplete schema)
    graph.register_fk("orders", "products", "product_id", "product_id")
    # Note: users↔orders FK is MISSING - should use heuristic
    
    test_cases = [
        # (table_a, table_b, expected_success, description)
        ("users", "orders", True, "Heuristic match: user_id ↔ user_id"),
        ("orders", "products", True, "FK match: product_id"),
        ("products", "categories", True, "Heuristic match: category_id ↔ category_id"),
        ("users", "categories", True, "Multi-hop: users→orders→products→categories via heuristics"),
    ]
    
    results = []
    for table_a, table_b, expected, desc in test_cases:
        start = time.monotonic()
        path = graph.find_join_path(table_a, table_b)
        latency_ms = (time.monotonic() - start) * 1000
        
        success = path is not None
        passed = success == expected
        
        results.append({
            "case": desc,
            "tables": f"{table_a} → {table_b}",
            "expected": expected,
            "actual": success,
            "passed": passed,
            "latency_ms": round(latency_ms, 2),
            "path_length": len(path) if path else 0,
            "path_steps": [f"{s.left_table}.{s.left_key}={s.right_table}.{s.right_key}" for s in path] if path else [],
        })
    
    return results


async def _run_async_benchmark(iterations: int = 100):
    """Run async benchmark for cache-integrated parsing (simulated)."""
    graph = TableRelationshipGraph()
    graph.register_columns("events", ["id", "event_id", "user_id", "timestamp"])
    graph.register_columns("users", ["id", "user_id", "name"])
    
    latencies = []
    for _ in range(iterations):
        start = time.monotonic()
        path = graph.find_join_path("events", "users")
        latency_ms = (time.monotonic() - start) * 1000
        latencies.append(latency_ms)
    
    return {
        "iterations": iterations,
        "avg_latency_ms": round(sum(latencies) / len(latencies), 3),
        "p50_latency_ms": round(sorted(latencies)[len(latencies)//2], 3),
        "p99_latency_ms": round(sorted(latencies)[int(len(latencies)*0.99)], 3),
    }


def main():
    print("🔍 JOIN Heuristic Inference Benchmark")
    print("=" * 60)
    
    # Sync accuracy tests
    print("\n📊 Accuracy Tests:")
    results = _run_sync_benchmark()
    passed = sum(1 for r in results if r["passed"])
    total = len(results)
    
    for r in results:
        status = "✓" if r["passed"] else "✗"
        print(f"  {status} {r['case']}")
        print(f"     {r['tables']} | exp={r['expected']}, act={r['actual']}, {r['latency_ms']}ms, depth={r['path_length']}")
        if r['path_steps']:
            print(f"     Path: {' → '.join(r['path_steps'])}")
    
    print(f"\n📈 Accuracy: {passed}/{total} passed ({100*passed/total:.1f}%)")
    
    # Async performance tests
    print("\n⚡ Performance Tests (100 iterations):")
    perf = asyncio.run(_run_async_benchmark(100))
    print(f"  Avg latency: {perf['avg_latency_ms']}ms")
    print(f"  P50 latency: {perf['p50_latency_ms']}ms")
    print(f"  P99 latency: {perf['p99_latency_ms']}ms")
    
    print("\n✅ Benchmark complete")
    return 0 if passed == total else 1


if __name__ == "__main__":
    exit(main())
