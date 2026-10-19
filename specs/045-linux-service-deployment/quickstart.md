# Quickstart: Linux LAN Bootstrap and Safe Updates

These commands target a disposable Linux host. Production acceptance still requires systemd and a real translation smoke.

## Bootstrap

1. Download and verify the official Linux server archive and its checksum.
2. Extract the archive into a temporary directory.
3. Run the installer as an administrator, pointing it at the extracted bundle and desired root:

   ```sh
   sudo ./install-server-linux.sh --bundle ./ImageLocalizationTool --root /opt/image-localization-tool
   ```

4. Confirm the service and readiness response:

   ```sh
   sudo systemctl status ilt.service
   curl --fail http://127.0.0.1:8765/v1/health
   ```

5. Run bootstrap a second time and confirm projects/settings/models/runtime are unchanged.

## Update and rollback

1. Extract a newer official bundle into a temporary directory.
2. Run `sudo ./update-server-linux.sh --bundle ./ImageLocalizationTool --root /opt/image-localization-tool`.
3. Verify `/v1/health` returns `ready: true` and the candidate version.
4. For an explicit rollback, run `sudo ./rollback-server-linux.sh --root /opt/image-localization-tool`; verify the previous version serves the health API.

The updater never runs component installation. Bootstrap handles component preparation separately.

## Forced failure acceptance

In a disposable Linux systemd environment, use a candidate test release whose executable exits or fails the health probe. Confirm the updater returns nonzero, reactivates the old release, reports the candidate failure, and leaves hashes under `shared/` unchanged.
