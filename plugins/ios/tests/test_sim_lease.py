"""sim-lease CLI の公開契約を、実際のシミュレータに触れず検証する。"""

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "skills/ios-sim-check/scripts/sim-lease"
UDIDS = tuple(f"00000000-0000-0000-0000-{number:012d}" for number in range(1, 6))
DEVICE_LIST = f"""== Devices ==
-- iOS 27.2 --
    iPhone 18 Pro ({UDIDS[0]}) (Shutdown)
    iPad Pro ({UDIDS[3]}) (Shutdown)
-- iOS 27.0 --
    iPhone SE (3rd generation) ({UDIDS[1]}) (Shutdown)
-- Unavailable: com.apple.CoreSimulator.SimRuntime.iOS-26-0 --
"""


class SimLeaseTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)
        self.pool = self.root / "config/pool.txt"
        self.locks = self.root / "locks"
        self.env = os.environ.copy()
        self.env.update(SIM_LEASE_POOL=str(self.pool),
                        SIM_LEASE_LOCKS=str(self.locks), SIM_LEASE_TTL="7200",
                        TMPDIR=str(self.root), XDG_CONFIG_HOME=str(self.root / "config"))

    def run_cli(self, *args, env=None):
        return subprocess.run(
            ["bash", str(SCRIPT), *args], cwd=self.root,
            env=self.env if env is None else env, capture_output=True,
            text=True, encoding="utf-8", check=False, timeout=15,
        )

    def assert_success(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def write_list(self, content=DEVICE_LIST):
        path = self.root / "devices.txt"
        path.write_text(content, encoding="utf-8")
        return str(path)

    def write_pool(self, count=2, content=None):
        self.pool.parent.mkdir(parents=True, exist_ok=True)
        self.pool.write_text(
            content if content is not None else "".join(
                f"{udid} iPhone-test-{number}\n"
                for number, udid in enumerate(UDIDS[:count])), encoding="utf-8")

    def acquire(self, label="test", *, env=None):
        return self.assert_success(self.run_cli("acquire", label, "0", env=env)).strip()

    def test_init_registers_only_iphones_with_normalized_versioned_names(self):
        self.assert_success(self.run_cli("init", self.write_list()))
        self.assertEqual(self.pool.read_text(encoding="utf-8").splitlines(), [
            f"{UDIDS[0]} iPhone-18-Pro-iOS27.2",
            f"{UDIDS[1]} iPhone-SE-3rd-generation-iOS27.0",
        ])

    def test_init_preserves_existing_pool(self):
        self.write_pool()
        original = self.pool.read_bytes()
        result = self.run_cli("init", self.write_list())
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.pool.read_bytes(), original)

    def test_init_missing_argument_exits_two(self):
        self.assertEqual(self.run_cli("init").returncode, 2)
        self.assertFalse(self.pool.exists())

    def test_init_nonexistent_file_exits_two(self):
        self.assertEqual(self.run_cli("init", str(self.root / "missing")).returncode, 2)
        self.assertFalse(self.pool.exists())

    def test_init_without_iphones_does_not_create_pool(self):
        result = self.run_cli("init", self.write_list(
            f"-- iOS 27.2 --\n    iPad Pro ({UDIDS[3]}) (Shutdown)\n"))
        self.assertEqual(result.returncode, 1)
        self.assertFalse(self.pool.exists())

    def test_acquire_returns_first_free_udid_only_and_then_next(self):
        self.write_pool()
        for udid in UDIDS[:2]:
            result = self.run_cli("acquire", "worker", "0")
            self.assertEqual(self.assert_success(result), udid + "\n")

    def test_acquire_udid_selects_requested_device_and_records_owner(self):
        self.write_pool(count=3)
        udid = UDIDS[2]
        result = self.run_cli("acquire", "--udid", udid, "target-worker", "0")
        self.assertEqual(self.assert_success(result), udid + "\n")
        self.assertEqual({p.name for p in self.locks.iterdir()}, {udid})
        self.assertTrue((self.locks / udid).is_dir())
        self.assertEqual((self.locks / udid / "owner").read_text().strip(),
                         "target-worker")

    def test_acquire_udid_busy_waits_then_times_out_without_fallback(self):
        self.write_pool(count=3)
        udid = self.acquire("current-owner")
        before = time.monotonic()
        result = self.run_cli("acquire", "--udid", udid, "waiting", "1")
        elapsed = time.monotonic() - before
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertGreaterEqual(elapsed, 1)
        self.assertEqual({p.name for p in self.locks.iterdir()}, {udid})
        self.assertEqual((self.locks / udid / "owner").read_text().strip(),
                         "current-owner")

    def test_acquire_udid_waits_until_requested_device_is_released(self):
        self.write_pool(count=3)
        udid = self.acquire("current-owner")
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(
                self.run_cli, "acquire", "--udid", udid, "waiting", "12")
            time.sleep(1.1)
            returned_before_release = pending.done()
            self.assert_success(self.run_cli("release", udid))
            result = pending.result(timeout=13)
        self.assertFalse(returned_before_release,
                         "指定台が返却されるまで取得処理が待機すること")
        self.assertEqual(self.assert_success(result), udid + "\n")
        self.assertEqual({p.name for p in self.locks.iterdir()}, {udid})
        self.assertEqual((self.locks / udid / "owner").read_text().strip(), "waiting")

    def test_acquire_udid_outside_pool_exits_two_without_locks(self):
        self.write_pool(count=3)
        result = self.run_cli("acquire", "--udid", UDIDS[4], "worker", "0")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(list(self.locks.glob("*")), [])

    def test_acquire_udid_missing_value_exits_two_without_locks(self):
        self.write_pool(count=3)
        result = self.run_cli("acquire", "--udid")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(list(self.locks.glob("*")), [])

    def test_acquire_exhausted_pool_exits_one_with_reason(self):
        self.write_pool(count=1)
        self.acquire()
        result = self.run_cli("acquire", "waiting", "1")
        self.assertEqual(result.returncode, 1)
        self.assertIn("空いているシミュレータが無い", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_acquire_missing_pool_exits_two_with_reason(self):
        result = self.run_cli("acquire", "worker", "0")
        self.assertEqual(result.returncode, 2)
        self.assertIn("登録簿が無い", result.stderr)

    def test_acquire_skips_empty_lines_and_comments(self):
        self.write_pool(content=f"\n# comment\n\n{UDIDS[0]} iPhone-test\n")
        self.assertEqual(self.acquire(), UDIDS[0])
        self.assertEqual({p.name for p in self.locks.iterdir()}, {UDIDS[0]})

    def test_acquire_records_owner_and_epoch_time(self):
        self.write_pool(count=1)
        before = int(time.time())
        udid = self.acquire("worker-label")
        after = int(time.time())
        self.assertEqual((self.locks / udid / "owner").read_text().strip(), "worker-label")
        timestamp = int((self.locks / udid / "time").read_text().strip())
        self.assertLessEqual(before, timestamp)
        self.assertLessEqual(timestamp, after)

    def test_acquire_reclaims_lease_older_than_zero_ttl(self):
        self.write_pool(count=1)
        env = dict(self.env, SIM_LEASE_TTL="0")
        first = self.acquire("first", env=env)
        time.sleep(1.1)
        self.assertEqual(self.acquire("second", env=env), first)
        self.assertEqual((self.locks / first / "owner").read_text().strip(), "second")

    def test_four_parallel_acquires_return_four_distinct_udids(self):
        self.write_pool(count=4)
        barrier = threading.Barrier(4)

        def acquire_together(number):
            barrier.wait(timeout=5)
            return self.run_cli("acquire", f"worker-{number}", "0")

        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(acquire_together, range(4)))
        leased = [self.assert_success(result).strip() for result in results]
        self.assertEqual(len(set(leased)), 4)
        self.assertEqual(set(leased), set(UDIDS[:4]))

    def test_release_makes_device_available_again(self):
        self.write_pool(count=1)
        udid = self.acquire()
        self.assert_success(self.run_cli("release", udid))
        self.assertFalse((self.locks / udid).exists())
        self.assertEqual(self.acquire("next"), udid)

    def test_release_unknown_udid_exits_two(self):
        self.write_pool()
        self.assertEqual(self.run_cli("release", UDIDS[4]).returncode, 2)

    def test_release_unborrowed_device_is_idempotent(self):
        self.write_pool(count=1)
        for _ in range(2):
            self.assert_success(self.run_cli("release", UDIDS[0]))
        self.assertEqual(self.acquire(), UDIDS[0])

    def test_status_lists_each_device_and_its_state_and_owner(self):
        self.write_pool()
        self.acquire("status-worker")
        lines = self.assert_success(self.run_cli("status")).splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual([line.split()[0] for line in lines], list(UDIDS[:2]))
        self.assertIn("使用中", lines[0])
        self.assertIn("owner=status-worker", lines[0])
        self.assertIn("空き", lines[1])

    def test_all_subcommands_avoid_xcrun(self):
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        marker = self.root / "xcrun-was-called"
        xcrun = bin_dir / "xcrun"
        xcrun.write_text('#!/bin/sh\n: > "$SIM_LEASE_XCRUN_MARKER"\nexit 99\n')
        xcrun.chmod(0o755)
        env = dict(self.env, PATH=str(bin_dir) + os.pathsep + self.env["PATH"],
                   SIM_LEASE_XCRUN_MARKER=str(marker))
        self.assert_success(self.run_cli("init", self.write_list(), env=env))
        udid = self.acquire(env=env)
        self.assert_success(self.run_cli("status", env=env))
        self.assert_success(self.run_cli("release", udid, env=env))
        self.assertFalse(marker.exists(), "sim-lease must not invoke xcrun")


if __name__ == "__main__":
    unittest.main()
