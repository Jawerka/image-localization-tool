# Quickstart: Windows update and rollback

1. Close Image Localization Tool.
2. Extract the portable update archive to a temporary directory.
3. From PowerShell, run `update-windows.ps1 -Bundle <extracted-folder> -InstallRoot <current-install-folder>`.
4. Check that the command reports the active version and a successful local health probe.
5. If the new version fails health validation, the updater restores the previous release automatically.
6. To explicitly return to the saved version, run `rollback-windows.ps1 -InstallRoot <current-install-folder>`.

The scripts need write access to the parent folder of the installation root and enough free space to stage the full application. They do not download files and do not alter model, runtime, project, or settings contents.
