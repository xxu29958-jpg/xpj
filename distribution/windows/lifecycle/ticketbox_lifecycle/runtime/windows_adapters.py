from __future__ import annotations

from ticketbox_lifecycle.runtime.command import CommandRunner
from ticketbox_lifecycle.runtime.windows_alembic import WindowsAlembicAdapter
from ticketbox_lifecycle.runtime.windows_dataset import WindowsDatasetAdapter
from ticketbox_lifecycle.runtime.windows_file_security import FileSecurity
from ticketbox_lifecycle.runtime.windows_files import WindowsFilesAdapter
from ticketbox_lifecycle.runtime.windows_postgres import WindowsPostgresAdapter
from ticketbox_lifecycle.runtime.windows_scm import WindowsScmAdapter
from ticketbox_lifecycle.runtime.windows_scm_observation import ScmObserver
from ticketbox_lifecycle.runtime.windows_security import WindowsSecurityAdapter


class WindowsAdapterBundle:
    def __init__(
        self,
        runner: CommandRunner,
        file_security: FileSecurity,
        scm_observer: ScmObserver,
    ) -> None:
        self.files = WindowsFilesAdapter()
        self.security = WindowsSecurityAdapter(runner, file_security)
        self.postgres = WindowsPostgresAdapter(runner, self.security)
        self.alembic = WindowsAlembicAdapter(runner)
        self.scm = WindowsScmAdapter(runner, self.security, scm_observer)
        self.dataset = WindowsDatasetAdapter(runner, self.security)
