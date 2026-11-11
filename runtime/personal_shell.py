"""Bound shell execution without holding the GIL inside the Rust bridge."""
import os
from pathlib import Path
import signal
import subprocess
import tempfile


def execute_shell(self, **params):
    from openjarvis.core.types import ToolResult
    from openjarvis.tools.shell_exec import _BASE_ENV_KEYS
    command=params.get('command','')
    if not isinstance(command,str) or not command:
        return ToolResult(tool_name='shell_exec',success=False,content='No command provided.')
    try:timeout=max(1,min(300,int(params.get('timeout',30))))
    except (ValueError,TypeError):timeout=30
    cwd=params.get('working_dir')
    if cwd is not None and not Path(cwd).is_dir():
        return ToolResult(tool_name='shell_exec',success=False,content=f'Working directory is not a directory: {cwd}')
    keys=list(_BASE_ENV_KEYS)
    extra=params.get('env_passthrough') or []
    if isinstance(extra,list):keys.extend(k for k in extra if isinstance(k,str))
    env={key:os.environ[key] for key in keys if key in os.environ}
    meta={'timeout_used':timeout,'working_dir':cwd}
    try:
        # File-backed output prevents a noisy command exhausting server memory.
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            proc=subprocess.Popen(command,shell=True,cwd=cwd,env=env,
                stdout=stdout,stderr=stderr,stdin=subprocess.DEVNULL,start_new_session=True)
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                try:os.killpg(proc.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                proc.wait(timeout=2)
                return ToolResult(tool_name='shell_exec',success=False,
                    content=f'Command timed out after {timeout} seconds.',metadata={**meta,'returncode':-1})
            stdout.seek(0);stderr.seek(0)
            out=stdout.read(102401);err=stderr.read(102401)
        def bounded(data):
            return data[:102400].decode('utf-8',errors='replace')+('\n[Output truncated]' if len(data)>102400 else '')
        content=f'Exit code: {proc.returncode}\n--- stdout ---\n{bounded(out)}\n--- stderr ---\n{bounded(err)}'
        return ToolResult(tool_name='shell_exec',success=proc.returncode==0,content=content,
            metadata={**meta,'returncode':proc.returncode})
    except (OSError,subprocess.SubprocessError) as error:
        return ToolResult(tool_name='shell_exec',success=False,content=f'Shell error: {error}',
            metadata={**meta,'returncode':-1})


def install_shell_tuning():
    from openjarvis.tools.shell_exec import ShellExecTool
    ShellExecTool.execute=execute_shell
