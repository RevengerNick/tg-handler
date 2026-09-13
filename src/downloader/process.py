from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

LineCallback = Callable[[str], Awaitable[None]]


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    stdout: str
    stderr: str


async def run_process(
    arguments: Sequence[str],
    *,
    timeout: int,
    environment: dict[str, str] | None = None,
    on_stdout: LineCallback | None = None,
) -> ProcessResult:
    process = await asyncio.create_subprocess_exec(
        *arguments,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=environment,
        limit=16 * 1024 * 1024,
    )
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []

    async def read_stdout() -> None:
        assert process.stdout is not None
        async for raw_line in process.stdout:
            line = raw_line.decode("utf-8", errors="replace").rstrip()
            stdout_lines.append(line)
            if on_stdout:
                await on_stdout(line)

    async def read_stderr() -> None:
        assert process.stderr is not None
        async for raw_line in process.stderr:
            stderr_lines.append(raw_line.decode("utf-8", errors="replace").rstrip())

    readers = [asyncio.create_task(read_stdout()), asyncio.create_task(read_stderr())]
    try:
        await asyncio.wait_for(process.wait(), timeout=timeout)
        await asyncio.gather(*readers)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        await asyncio.gather(*readers, return_exceptions=True)
        raise
    except BaseException:
        if process.returncode is None:
            process.kill()
            await process.wait()
        for reader in readers:
            reader.cancel()
        raise

    return ProcessResult(
        process.returncode, "\n".join(stdout_lines), "\n".join(stderr_lines)
    )
