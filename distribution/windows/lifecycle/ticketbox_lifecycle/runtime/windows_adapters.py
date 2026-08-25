from __future__ import annotations

from ticketbox_lifecycle.runtime.command import CommandRunner, SubprocessCommandRunner
from ticketbox_lifecycle.runtime.windows_alembic import WindowsAlembicAdapter
from ticketbox_lifecycle.runtime.windows_dataset import WindowsDatasetAdapter
from ticketbox_lifecycle.runtime.windows_files import WindowsFilesAdapter
from ticketbox_lifecycle.runtime.windows_postgres import WindowsPostgresAdapter
from ticketbox_lifecycle.runtime.windows_scm import WindowsScmAdapter
from ticketbox_lifecycle.runtime.windows_security import WindowsSecurityAdapter


class WindowsAdapterBundle:
    def __init__(self, runner: CommandRunner | None = None) -> None:
        command_runner = runner or SubprocessCommandRunner()
        self.files = WindowsFilesAdapter()
        self.security = WindowsSecurityAdapter(command_runner)
        self.postgres = WindowsPostgresAdapter(command_runner)
        self.alembic = WindowsAlembicAdapter(command_runner)
        self.scm = WindowsScmAdapter(command_runner, self.security)
        self.dataset = WindowsDatasetAdapter(command_runner, self.security)
