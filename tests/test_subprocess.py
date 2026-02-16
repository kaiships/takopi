"""Tests for subprocess utilities."""

from __future__ import annotations

import signal
from unittest.mock import MagicMock, patch

import anyio
import pytest

from takopi.utils.subprocess import (
    kill_process,
    manage_subprocess,
    terminate_process,
    wait_for_process,
)


class TestWaitForProcess:
    """Tests for wait_for_process function."""

    @pytest.mark.anyio
    async def test_process_completes_before_timeout(self) -> None:
        """Test when process finishes before timeout."""
        mock_proc = MagicMock()

        async def fast_wait() -> None:
            await anyio.sleep(0)  # Complete immediately

        mock_proc.wait = fast_wait

        timed_out = await wait_for_process(mock_proc, timeout=5.0)
        # Process completed normally
        assert timed_out is False

    @pytest.mark.anyio
    async def test_process_times_out(self) -> None:
        """Test when process exceeds timeout."""
        mock_proc = MagicMock()

        async def slow_wait() -> None:
            await anyio.sleep(10.0)  # Much longer than timeout

        mock_proc.wait = slow_wait

        timed_out = await wait_for_process(mock_proc, timeout=0.01)
        # Process timed out
        assert timed_out is True


class TestSignalProcess:
    """Tests for terminate_process and kill_process functions."""

    def test_terminate_already_finished_process(self) -> None:
        """Test terminating a process that already exited."""
        mock_proc = MagicMock()
        mock_proc.returncode = 0  # Already finished

        # Should return early without calling anything
        terminate_process(mock_proc)

        # Verify no signals were sent
        mock_proc.terminate.assert_not_called()

    def test_kill_already_finished_process(self) -> None:
        """Test killing a process that already exited."""
        mock_proc = MagicMock()
        mock_proc.returncode = 0  # Already finished

        kill_process(mock_proc)

        mock_proc.kill.assert_not_called()

    @patch("os.name", "posix")
    @patch("os.killpg")
    def test_terminate_posix_success(self, mock_killpg: MagicMock) -> None:
        """Test successful SIGTERM on POSIX."""
        mock_proc = MagicMock()
        mock_proc.returncode = None
        mock_proc.pid = 12345

        terminate_process(mock_proc)

        mock_killpg.assert_called_once_with(12345, signal.SIGTERM)
        mock_proc.terminate.assert_not_called()

    @patch("os.name", "posix")
    @patch("os.killpg")
    def test_kill_posix_success(self, mock_killpg: MagicMock) -> None:
        """Test successful SIGKILL on POSIX."""
        mock_proc = MagicMock()
        mock_proc.returncode = None
        mock_proc.pid = 12345

        kill_process(mock_proc)

        mock_killpg.assert_called_once_with(12345, signal.SIGKILL)
        mock_proc.kill.assert_not_called()

    @patch("os.name", "posix")
    @patch("os.killpg")
    def test_terminate_process_lookup_error(self, mock_killpg: MagicMock) -> None:
        """Test handling ProcessLookupError (process already gone)."""
        mock_proc = MagicMock()
        mock_proc.returncode = None
        mock_proc.pid = 12345
        mock_killpg.side_effect = ProcessLookupError()

        # Should not raise
        terminate_process(mock_proc)

        # Fallback not called when ProcessLookupError
        mock_proc.terminate.assert_not_called()

    @patch("os.name", "posix")
    @patch("os.killpg")
    def test_terminate_oserror_falls_back(self, mock_killpg: MagicMock) -> None:
        """Test falling back to proc.terminate on OSError."""
        mock_proc = MagicMock()
        mock_proc.returncode = None
        mock_proc.pid = 12345
        mock_killpg.side_effect = OSError("Permission denied")

        terminate_process(mock_proc)

        # Should fall back to proc.terminate
        mock_proc.terminate.assert_called_once()

    @patch("os.name", "nt")  # Windows
    def test_terminate_non_posix(self) -> None:
        """Test termination on non-POSIX systems uses fallback directly."""
        mock_proc = MagicMock()
        mock_proc.returncode = None
        mock_proc.pid = 12345

        terminate_process(mock_proc)

        mock_proc.terminate.assert_called_once()

    def test_fallback_process_lookup_error(self) -> None:
        """Test fallback handling when process is gone."""
        mock_proc = MagicMock()
        mock_proc.returncode = None
        mock_proc.pid = 12345
        mock_proc.terminate.side_effect = ProcessLookupError()

        with patch("os.name", "nt"):
            # Should not raise
            terminate_process(mock_proc)


class TestManageSubprocess:
    """Tests for manage_subprocess context manager."""

    @pytest.mark.anyio
    async def test_process_completes_normally(self) -> None:
        """Test subprocess that completes within the context."""
        async with manage_subprocess(["echo", "hello"]) as proc:
            await proc.wait()

        # Process should have completed
        assert proc.returncode == 0

    @pytest.mark.anyio
    async def test_cleanup_on_exit(self) -> None:
        """Test that cleanup terminates running process."""
        # Use a process that runs for a while
        async with manage_subprocess(["sleep", "10"]) as proc:
            # Exit early without waiting
            pass

        # Process should have been terminated
        assert proc.returncode is not None

    @pytest.mark.anyio
    async def test_posix_new_session(self) -> None:
        """Test that start_new_session is set on POSIX."""
        with patch("os.name", "posix"), patch("anyio.open_process") as mock_open:
            mock_proc = MagicMock()
            mock_proc.returncode = 0  # Already finished
            mock_open.return_value = mock_proc

            async with manage_subprocess(["echo", "test"]):
                pass

            # Check that start_new_session was passed
            call_kwargs = mock_open.call_args[1]
            assert call_kwargs.get("start_new_session") is True
