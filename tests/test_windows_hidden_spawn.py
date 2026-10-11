"""Background SDK launches must not open Windows console windows."""

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import anyio
import pytest

from claude_agent_sdk._internal.transport.subprocess_cli import SubprocessCLITransport
from claude_agent_sdk.types import ClaudeAgentOptions


@pytest.mark.parametrize(
    "system,expected_flags", [("Windows", 0x08000000), ("Linux", 0)]
)
@pytest.mark.parametrize("phase", ["version", "session"])
def test_subprocess_console_flags(system, expected_flags, phase):
    async def exercise():
        process = MagicMock()
        process.returncode = 0
        process.wait = AsyncMock(return_value=0)
        process.aclose = AsyncMock()
        process.stdin = None
        process.stderr = None
        process.stdout = None
        if phase == "version":
            process.stdout = MagicMock()
            process.stdout.receive = AsyncMock(return_value=b"2.1.296 (Claude Code)")
        transport = SubprocessCLITransport(
            prompt="test",
            options=ClaudeAgentOptions(cli_path="claude.exe", user=None),
        )
        with (
            patch(
                "claude_agent_sdk._internal.transport.subprocess_cli.platform.system",
                return_value=system,
            ),
            patch(
                "anyio.open_process", new_callable=AsyncMock, return_value=process
            ) as opened,
            patch.dict("os.environ", {"CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK": "1"}),
        ):
            if phase == "version":
                await transport._check_claude_version()
            else:
                await transport.connect()
            assert opened.call_count == 1
            args, kwargs = opened.call_args
            assert kwargs.get("creationflags", 0) == expected_flags
            assert "shell" not in kwargs
            if phase == "version":
                assert args[0] == ["claude.exe", "-v"]
            else:
                assert args[0][0] == "claude.exe"
                assert kwargs["user"] is None
                assert kwargs["env"]["CLAUDE_CODE_ENTRYPOINT"] == "sdk-py"
                await transport.close()

    anyio.run(exercise)


@pytest.mark.skipif(os.name != "nt", reason="Checks the Windows console handle")
def test_windows_transport_child_has_no_console():
    async def exercise():
        transport = SubprocessCLITransport(
            prompt="console probe",
            options=ClaudeAgentOptions(cli_path=sys.executable),
        )
        command = [
            sys.executable,
            "-c",
            "import ctypes,json; "
            "print(json.dumps({'console_handle': "
            "ctypes.windll.kernel32.GetConsoleWindow()}))",
        ]
        with (
            patch.object(transport, "_build_command", return_value=command),
            patch.dict("os.environ", {"CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK": "1"}),
        ):
            await transport.connect()
            try:
                messages = [message async for message in transport.read_messages()]
                assert messages == [{"console_handle": 0}]
            finally:
                await transport.close()

    anyio.run(exercise)
